"""
Deep learning visual embedding service.

Primary model (CPU + GPU): MobileNetV3-Small (576-dim avg-pool features)
  - 8 MB weights, fast on CPU, faster on CUDA
  - Auto-selects CUDA if available

GPU upgrade path: DINOv2 ViT-S/8 (384-dim)
  - Uncomment the DINOv2 block below once GPU is confirmed
  - Requires: pip install transformers

ONNX Runtime path (optional, for faster CPU inference):
  - Export MobileNetV3 to ONNX once, load with onnxruntime for lower latency
  - Useful for high-throughput deployments without GPU

The module is import-safe: torch is loaded lazily only when embed_frames() is
called for the first time, so container startup is not slowed.
"""

import logging
import threading
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Fixed embedding dimension for FAISS compatibility.
# Changing this requires rebuilding the DL FAISS index.
MOBILENET_DIM = 576   # MobileNetV3-Small avgpool output
DINOV2_DIM    = 384   # DINOv2-small CLS token (future upgrade)

DL_EMBEDDING_DIM = MOBILENET_DIM  # active dimension


class _MobileNetExtractor:
    """Thin wrapper around MobileNetV3-Small for feature extraction."""

    def __init__(self) -> None:
        import torch
        import torchvision.models as models
        import torchvision.transforms as T

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        base = models.mobilenet_v3_small(
            weights=models.MobileNet_V3_Small_Weights.IMAGENET1K_V1
        )

        import torch.nn as nn

        class _Extractor(nn.Module):
            def __init__(self, base):
                super().__init__()
                self.features = base.features
                self.avgpool  = base.avgpool

            def forward(self, x):
                x = self.features(x)
                x = self.avgpool(x)
                return x.flatten(1)  # (batch, 576)

        self.model = _Extractor(base).to(self.device)
        self.model.eval()

        self.transform = T.Compose([
            T.Resize(256),
            T.CenterCrop(224),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])

        self.dim = MOBILENET_DIM
        self.name = "mobilenet_v3_small"
        logger.info(f"MobileNetV3-Small loaded on {self.device}")

    def embed(self, frame_path: Path) -> Optional[np.ndarray]:
        import torch
        from PIL import Image

        try:
            img = Image.open(frame_path).convert("RGB")
            tensor = self.transform(img).unsqueeze(0).to(self.device)
            with torch.no_grad():
                vec = self.model(tensor).squeeze().cpu().numpy()
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            return vec.astype(np.float32)
        except Exception as e:
            logger.debug(f"Frame embed failed {frame_path}: {e}")
            return None


# ---------------------------------------------------------------------------
# FUTURE UPGRADE: DINOv2 on GPU
# ---------------------------------------------------------------------------
# class _DINOv2Extractor:
#     def __init__(self):
#         from transformers import AutoImageProcessor, AutoModel
#         import torch
#         self.device = torch.device("cuda")
#         self.processor = AutoImageProcessor.from_pretrained("facebook/dinov2-small")
#         self.model = AutoModel.from_pretrained("facebook/dinov2-small").to(self.device)
#         self.model.eval()
#         self.dim = DINOV2_DIM
#         self.name = "dinov2-small"
#
#     def embed(self, frame_path):
#         ...  # same L2-normalize pattern as above
# ---------------------------------------------------------------------------


class EmbeddingModel:
    """
    Lazy-loaded, thread-safe DL embedding model.
    Singleton: shared across all requests.
    """

    def __init__(self) -> None:
        self._extractor: Optional[_MobileNetExtractor] = None
        self._available: bool = False
        self._init_attempted: bool = False
        self._lock = threading.Lock()

    def warmup(self) -> None:
        """Pre-load the model (call from startup thread)."""
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._init_attempted:
                return
            self._init_attempted = True
            try:
                self._extractor = _MobileNetExtractor()
                self._available = True
            except ImportError:
                logger.warning(
                    "PyTorch not available — DL embeddings disabled. "
                    "Install: pip install torch torchvision"
                )
            except Exception as e:
                logger.warning(f"DL embedding model failed to load: {e}")

    @property
    def available(self) -> bool:
        if not self._init_attempted:
            self._ensure_loaded()
        return self._available

    @property
    def dim(self) -> int:
        return DL_EMBEDDING_DIM

    @property
    def model_name(self) -> str:
        if self._extractor:
            return self._extractor.name
        return "none"

    @property
    def device(self) -> str:
        if self._extractor:
            return str(self._extractor.device)
        return "cpu"

    def embed_frame(self, frame_path: Path) -> Optional[np.ndarray]:
        """
        L2-normalized embedding for one frame.
        Returns float32 array of shape (DL_EMBEDDING_DIM,), or None.
        """
        if not self.available or self._extractor is None:
            return None
        return self._extractor.embed(frame_path)

    def embed_frames(
        self, frame_paths: list[Path], max_frames: int = 30
    ) -> Optional[np.ndarray]:
        """
        Mean L2-normalized embedding across sampled frames.
        Returns float32 array of shape (DL_EMBEDDING_DIM,), or None.
        """
        if not self.available:
            return None

        if len(frame_paths) > max_frames:
            step = max(1, len(frame_paths) // max_frames)
            frame_paths = frame_paths[::step][:max_frames]

        embeddings = []
        for fp in frame_paths:
            emb = self.embed_frame(fp)
            if emb is not None:
                embeddings.append(emb)

        if not embeddings:
            return None

        mean_emb = np.mean(embeddings, axis=0).astype(np.float32)
        norm = np.linalg.norm(mean_emb)
        if norm > 0:
            mean_emb = mean_emb / norm
        return mean_emb


_model_instance: Optional[EmbeddingModel] = None
_model_lock = threading.Lock()


def get_embedding_model() -> EmbeddingModel:
    global _model_instance
    with _model_lock:
        if _model_instance is None:
            _model_instance = EmbeddingModel()
    return _model_instance


def get_device_info() -> dict:
    """Return hardware + model status for /api/system-info."""
    model = get_embedding_model()
    device_type = "cpu"
    gpu_name = None

    try:
        import torch
        if torch.cuda.is_available():
            device_type = "cuda"
            gpu_name = torch.cuda.get_device_name(0)
        torch_version = torch.__version__
    except ImportError:
        torch_version = "not installed"

    return {
        "device": device_type,
        "gpu_name": gpu_name,
        "torch_version": torch_version,
        "model_name": model.model_name if model.available else "none",
        "embedding_dim": model.dim if model.available else 0,
        "dl_available": model.available,
    }

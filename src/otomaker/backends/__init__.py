"""Backend selection.

OTOMAKER_BACKEND = sa3-tflite (default) | sa3-comfy
  sa3-tflite = Stable Audio 3 on the CPU (the default; runs on any Windows PC),
  sa3-comfy  = a running ComfyUI, usually on an NVIDIA GPU (text-to-audio only).
OTOMAKER_FALLBACK = backend name (default: off, e.g. sa3-tflite). When sa3-comfy
  cannot reach ComfyUI, that generate_audio call runs on it instead; the result
  and metadata say so. Other ComfyUI errors are not retried elsewhere.
"""
from __future__ import annotations

import importlib
import os

from .base import Backend, BackendUnavailable, GenerationRequest, GenerationResult

__all__ = ["Backend", "BackendUnavailable", "GenerationRequest", "GenerationResult", "BACKENDS",
           "create_backend", "resolve_backend_name"]

DEFAULT_BACKEND = "sa3-tflite"

# name → (module in this package, class). Add a backend with one line here.
_REGISTRY: dict[str, tuple[str, str]] = {
    "sa3-tflite": (".sa3_tflite", "SA3TFLiteBackend"),
    "sa3-comfy": (".sa3_comfy", "SA3ComfyBackend"),
}
BACKENDS = tuple(_REGISTRY)


def resolve_backend_name(name: str | None = None) -> str:
    name = (name or os.environ.get("OTOMAKER_BACKEND") or DEFAULT_BACKEND).strip().lower()
    if name not in _REGISTRY:
        raise RuntimeError(f"unknown OTOMAKER_BACKEND {name!r}; choose one of {', '.join(BACKENDS)}")
    return name


def create_backend(name: str | None = None) -> Backend:
    name = resolve_backend_name(name)
    module, cls = _REGISTRY[name]
    return getattr(importlib.import_module(module, __package__), cls)()

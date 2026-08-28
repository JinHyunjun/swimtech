"""Hardware-aware runtime selection for the offline pose experiment.

The deployed SwimMate API does not import this module.  It exists so local
video experiments can use Intel hardware without silently changing the
production dependency set.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


_VALID_PROFILES = {"auto", "quality", "balanced", "portable"}
_VALID_BACKENDS = {"auto", "openvino", "onnxruntime"}
_VALID_DEVICES = {"auto", "cpu", "gpu", "npu"}
_VALID_MODES = {"auto", "lightweight", "balanced", "performance"}


@dataclass(frozen=True)
class PoseRuntimeConfig:
    """Resolved pose model and inference engine configuration."""

    profile: str
    backend: str
    device: str
    mode: str
    available_openvino_devices: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["available_openvino_devices"] = list(self.available_openvino_devices)
        return data


def discover_openvino_devices() -> tuple[str, ...]:
    """Return normalized OpenVINO devices without making it a dependency."""

    try:
        from openvino import Core
    except (ImportError, OSError):
        return ()
    try:
        return tuple(str(item).lower() for item in Core().available_devices)
    except Exception:
        # A broken or stale Intel driver must not break the CPU fallback.
        return ()


def _normalize_devices(devices: Iterable[str] | None) -> tuple[str, ...]:
    source = discover_openvino_devices() if devices is None else devices
    return tuple(dict.fromkeys(str(item).lower() for item in source))


def select_pose_runtime(
    profile: str = "auto",
    backend: str = "auto",
    device: str = "auto",
    mode: str = "auto",
    *,
    available_devices: Iterable[str] | None = None,
) -> PoseRuntimeConfig:
    """Resolve an explicit, reproducible runtime configuration.

    ``auto`` uses RTMPose-M on an available Intel GPU because it preserves
    enough throughput for temporal analysis. ``quality`` explicitly selects
    RTMPose-X for slower single-lane/offline review. CPU-only systems use
    RTMPose-M. ``portable`` retains the smallest ONNX Runtime CPU
    configuration. NPU is never selected automatically because current
    RTMPose ONNX files expose a dynamic batch dimension that is not accepted
    by every NPU driver/compiler combination.
    """

    profile = profile.lower()
    backend = backend.lower()
    device = device.lower()
    mode = mode.lower()
    if profile not in _VALID_PROFILES:
        raise ValueError(f"profile must be one of {sorted(_VALID_PROFILES)}")
    if backend not in _VALID_BACKENDS:
        raise ValueError(f"backend must be one of {sorted(_VALID_BACKENDS)}")
    if device not in _VALID_DEVICES:
        raise ValueError(f"device must be one of {sorted(_VALID_DEVICES)}")
    if mode not in _VALID_MODES:
        raise ValueError(f"mode must be one of {sorted(_VALID_MODES)}")

    devices = _normalize_devices(available_devices)
    has_gpu = "gpu" in devices
    has_cpu = "cpu" in devices

    if profile == "portable":
        default_backend, default_device, default_mode = "onnxruntime", "cpu", "lightweight"
        reason = "portable profile: smallest model with the universal CPU runtime"
    elif profile in {"auto", "balanced"}:
        default_backend = "openvino" if has_gpu or has_cpu else "onnxruntime"
        default_device = "gpu" if has_gpu else "cpu"
        default_mode = "balanced"
        reason = "RTMPose-M preserves temporal and multi-lane throughput"
    else:
        default_backend = "openvino" if has_gpu or has_cpu else "onnxruntime"
        default_device = "gpu" if has_gpu else "cpu"
        default_mode = "performance" if has_gpu else "balanced"
        reason = (
            "quality profile: slower RTMPose-X on the Intel GPU"
            if has_gpu
            else "CPU fallback: RTMPose-M avoids impractical RTMPose-X latency"
        )

    resolved_backend = default_backend if backend == "auto" else backend
    resolved_device = default_device if device == "auto" else device
    resolved_mode = default_mode if mode == "auto" else mode

    if resolved_backend == "onnxruntime" and resolved_device != "cpu":
        raise ValueError(
            "this offline ONNX Runtime profile is CPU-only; use OpenVINO for the Intel GPU"
        )
    if resolved_backend == "openvino":
        if not devices:
            raise RuntimeError("OpenVINO is unavailable; install openvino or use --backend onnxruntime")
        if resolved_device not in devices:
            raise RuntimeError(
                f"OpenVINO device {resolved_device!r} is unavailable; detected {list(devices)}"
            )
        if resolved_device == "npu":
            raise RuntimeError(
                "current RTMPose ONNX files use a dynamic batch dimension; "
                "use cpu/gpu until a fixed-shape NPU export is validated"
            )

    return PoseRuntimeConfig(
        profile=profile,
        backend=resolved_backend,
        device=resolved_device,
        mode=resolved_mode,
        available_openvino_devices=devices,
        reason=reason,
    )

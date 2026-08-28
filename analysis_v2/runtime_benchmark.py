"""Benchmark RTMPose inference engines on one representative local frame."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import time

from .rtmpose_provider import RTMPoseTopDownProvider
from .runtime import discover_openvino_devices


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark offline RTMPose runtimes")
    parser.add_argument("video", type=Path)
    parser.add_argument("--timestamp-sec", type=float, default=1.0)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--lane-count", type=int, default=1)
    parser.add_argument("--target-fps", type=float, default=15.0)
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=("lightweight", "balanced", "performance"),
        default=("lightweight", "balanced", "performance"),
    )
    parser.add_argument(
        "--devices",
        nargs="+",
        choices=("cpu", "gpu", "npu"),
        default=("cpu", "gpu", "npu"),
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _load_frame(video: Path, timestamp_sec: float):
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - offline dependency
        raise RuntimeError("OpenCV is required for the runtime benchmark") from exc
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open {video}")
    capture.set(cv2.CAP_PROP_POS_MSEC, max(timestamp_sec, 0.0) * 1000.0)
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise RuntimeError(f"cannot read {video} at {timestamp_sec:.3f}s")
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def benchmark_runtime(
    rgb_frame,
    mode: str,
    device: str,
    iterations: int,
    warmup: int,
    lane_count: int,
) -> dict[str, object]:
    started = time.perf_counter()
    if device == "npu":
        # The upstream RTMPose ONNX files expose a dynamic batch dimension.
        # On the current Intel NPU compiler this terminates model import before
        # Python can reliably recover, so record the incompatibility instead
        # of taking down the entire benchmark process.
        return {
            "mode": mode,
            "backend": "openvino",
            "device": device,
            "available": False,
            "compile_sec": 0.0,
            "single_lane_fps": None,
            "estimated_all_lanes_fps": None,
            "last_detection_count": 0,
            "last_pose_confidence": None,
            "error": "RTMPose dynamic batch is incompatible with the current NPU compiler",
        }
    try:
        provider = RTMPoseTopDownProvider(mode=mode, backend="openvino", device=device)
        compile_sec = time.perf_counter() - started
        for index in range(warmup):
            provider.detect(rgb_frame, index)
        measured = time.perf_counter()
        result = []
        for index in range(iterations):
            result = provider.detect(rgb_frame, index)
        elapsed = time.perf_counter() - measured
        fps = iterations / elapsed if elapsed > 0 else 0.0
        return {
            "mode": mode,
            "backend": "openvino",
            "device": device,
            "available": True,
            "compile_sec": round(compile_sec, 4),
            "single_lane_fps": round(fps, 4),
            "estimated_all_lanes_fps": round(fps / max(lane_count, 1), 4),
            "last_detection_count": len(result),
            "last_pose_confidence": round(result[0].confidence, 4) if result else None,
            "error": None,
        }
    except Exception as exc:
        return {
            "mode": mode,
            "backend": "openvino",
            "device": device,
            "available": False,
            "compile_sec": round(time.perf_counter() - started, 4),
            "single_lane_fps": None,
            "estimated_all_lanes_fps": None,
            "last_detection_count": 0,
            "last_pose_confidence": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def choose_recommendation(rows: list[dict[str, object]], target_fps: float) -> dict[str, object] | None:
    usable = [
        row
        for row in rows
        if row["available"] and float(row["estimated_all_lanes_fps"] or 0.0) >= target_fps
    ]
    if not usable:
        available = [row for row in rows if row["available"]]
        return (
            max(available, key=lambda row: float(row["estimated_all_lanes_fps"] or 0.0))
            if available
            else None
        )
    quality_rank = {"lightweight": 1, "balanced": 2, "performance": 3}
    return max(
        usable,
        key=lambda row: (
            quality_rank[str(row["mode"])],
            float(row["estimated_all_lanes_fps"] or 0.0),
        ),
    )


def main() -> int:
    args = build_parser().parse_args()
    if not args.video.is_file():
        raise SystemExit(f"Video not found: {args.video}")
    if args.iterations < 1 or args.warmup < 0 or args.lane_count < 1:
        raise SystemExit("iterations/lane-count must be positive and warmup cannot be negative")
    frame = _load_frame(args.video, args.timestamp_sec)
    available_devices = discover_openvino_devices()
    rows = []
    for mode in args.modes:
        for device in args.devices:
            if device not in available_devices:
                continue
            print(f"benchmarking {mode} / openvino:{device}", flush=True)
            rows.append(
                benchmark_runtime(
                    frame,
                    mode,
                    device,
                    args.iterations,
                    args.warmup,
                    args.lane_count,
                )
            )
    recommendation = choose_recommendation(rows, args.target_fps)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "video": args.video.name,
        "timestamp_sec": args.timestamp_sec,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "available_openvino_devices": list(available_devices),
        "iterations": args.iterations,
        "warmup": args.warmup,
        "lane_count": args.lane_count,
        "target_fps": args.target_fps,
        "results": rows,
        "recommendation": recommendation,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved benchmark to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

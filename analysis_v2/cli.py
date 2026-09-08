"""Run the experimental multi-swimmer counter against a local video."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time

from .lanes import LaneCropPoseProvider, LaneLayout, LaneMosaicPoseProvider
from .mediapipe_provider import MediaPipeMultiPoseProvider, MediaPipeTiledPoseProvider
from .pipeline import MultiSwimmerAnalyzer
from .distance import DistanceSegment
from .pose_cache import deserialize_detections, read_pose_cache, serialize_frame, video_sha256, write_pose_cache
from .rtmpose_provider import RTMPoseProvider, RTMPoseTopDownProvider
from .runtime import select_pose_runtime
from .tracking import TrackerConfig
from .types import StrokeKind, StrokeSource


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Experimental SwimMate multi-swimmer counter")
    parser.add_argument("video", type=Path)
    parser.add_argument("--stroke", choices=[item.value for item in StrokeKind], required=True)
    parser.add_argument(
        "--stroke-source",
        choices=(StrokeSource.USER_CONFIRMED.value, StrokeSource.EVENT_METADATA.value),
        default=StrokeSource.USER_CONFIRMED.value,
        help="Provenance of the explicit label; directory-name inference is intentionally unsupported",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=Path("analysis/pose_landmarker.task"))
    parser.add_argument("--max-swimmers", type=int, default=10)
    parser.add_argument("--lane-axis", choices=("x", "y"), default="y")
    parser.add_argument("--frame-step", type=int, default=1, help="Default: all source frames to preserve kick motion")
    parser.add_argument("--start-sec", type=float)
    parser.add_argument("--end-sec", type=float)
    distance = parser.add_mutually_exclusive_group()
    distance.add_argument("--distance-m", type=float, help="Measured distance for the explicit start/end interval")
    distance.add_argument("--distance-segments", type=Path, help="JSON list of per-swimmer measured intervals")
    parser.add_argument("--distance-track-id", help="Explicit swimmer, e.g. L01; required with --distance-m")
    parser.add_argument("--distance-basis", choices=("interval_total", "surface_swimming"), default="interval_total")
    cache = parser.add_mutually_exclusive_group()
    cache.add_argument("--pose-cache-out", type=Path, help="Save private compressed poses for repeatable counter evaluation")
    cache.add_argument("--pose-cache-in", type=Path, help="Reuse poses after validating the source video hash")
    parser.add_argument(
        "--provider",
        choices=(
            "tiled",
            "whole-frame",
            "rtmpose",
            "lane-tiled",
            "lane-rtmpose",
            "lane-mosaic-rtmpose",
            "lane-rtmpose-topdown",
        ),
        default="tiled",
    )
    parser.add_argument("--lane-layout", type=Path, help="JSON file containing perspective lane polygons")
    parser.add_argument(
        "--lane-rotation",
        choices=("none", "clockwise", "counterclockwise"),
        default="clockwise",
        help="Rotate horizontal lane crops before pose estimation",
    )
    parser.add_argument("--lane-crop-padding", type=float, default=0.20)
    parser.add_argument("--tile-grid", default="3x3", help="Tiled provider grid, for example 3x3")
    parser.add_argument("--tile-overlap", type=float, default=0.28)
    parser.add_argument(
        "--pool-roi",
        default="0,0,1,1",
        help="Normalized x1,y1,x2,y2 pool bounds; excludes spectators and officials",
    )
    parser.add_argument("--orientation", choices=("any", "horizontal", "vertical"), default="horizontal")
    parser.add_argument(
        "--runtime-profile",
        choices=("auto", "quality", "balanced", "portable"),
        default="auto",
        help="Hardware/model profile for RTMPose providers",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "openvino", "onnxruntime"),
        default="auto",
    )
    parser.add_argument("--device", choices=("auto", "cpu", "gpu", "npu"), default="auto")
    parser.add_argument(
        "--pose-mode",
        choices=("auto", "lightweight", "balanced", "performance"),
        default="auto",
    )
    return parser


def _parse_grid(value: str) -> tuple[int, int]:
    try:
        columns, rows = (int(part) for part in value.lower().split("x", 1))
    except (TypeError, ValueError) as exc:
        raise SystemExit("--tile-grid must look like 3x3") from exc
    if columns < 1 or rows < 1:
        raise SystemExit("--tile-grid values must be positive")
    return columns, rows


def _parse_roi(value: str) -> tuple[float, float, float, float]:
    try:
        roi = tuple(float(part) for part in value.split(","))
    except ValueError as exc:
        raise SystemExit("--pool-roi must contain normalized x1,y1,x2,y2") from exc
    if len(roi) != 4:
        raise SystemExit("--pool-roi must contain normalized x1,y1,x2,y2")
    return roi  # Geometry validation is performed by the provider.


def main() -> int:
    args = build_parser().parse_args()
    if not args.video.is_file():
        raise SystemExit(f"Video not found: {args.video}")
    if args.frame_step < 1:
        raise SystemExit("--frame-step must be at least 1")
    if any(value is not None and (not math.isfinite(value) or value < 0)
           for value in (args.start_sec, args.end_sec)):
        raise SystemExit("--start-sec/--end-sec must be nonnegative and finite")
    if args.start_sec is not None and args.end_sec is not None and args.end_sec <= args.start_sec:
        raise SystemExit("--end-sec must be after --start-sec")
    distance_segments = parse_distance_segments(args)
    source_hash = video_sha256(args.video)
    analyzer = MultiSwimmerAnalyzer(
        args.stroke,
        tracker_config=TrackerConfig(max_swimmers=args.max_swimmers, lane_axis=args.lane_axis),
        stroke_source=args.stroke_source,
    )
    if args.pose_cache_in:
        started = time.perf_counter()
        cache = read_pose_cache(args.pose_cache_in, source_hash)
        for frame in cache["frames"]:
            timestamp = frame["timestamp_sec"]
            if args.start_sec is not None and timestamp < args.start_sec:
                continue
            if args.end_sec is not None and timestamp >= args.end_sec:
                break
            if frame["frame_index"] % args.frame_step == 0:
                analyzer.process_frame(deserialize_detections(frame), frame["frame_index"], timestamp)
        result = analyzer.finalize(distance_segments).to_dict()
        result["source_video_sha256"] = source_hash
        result["run"] = {"provider": "pose-cache-replay", "inference": cache["inference"],
                         "elapsed_sec": round(time.perf_counter() - started, 3),
                         "source_fps": cache["source_fps"], "analyzed_frames": analyzer.processed_frames}
        save_result(args.output, result)
        return 0

    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - optional offline dependency
        raise SystemExit("OpenCV is required for the offline video CLI") from exc

    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise SystemExit(f"Cannot open video: {args.video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if not math.isfinite(fps) or fps <= 0:
        capture.release()
        raise SystemExit("Video source FPS is missing or invalid; event timing cannot be calibrated")

    frame_index = 0
    columns, rows = _parse_grid(args.tile_grid)
    pool_roi = _parse_roi(args.pool_roi)
    lane_layout = LaneLayout.load(args.lane_layout) if args.lane_layout else None
    runtime = None
    if "rtmpose" in args.provider:
        runtime = select_pose_runtime(
            args.runtime_profile,
            args.backend,
            args.device,
            args.pose_mode,
        )
        print(
            f"RTMPose runtime: {runtime.mode} / {runtime.backend}:{runtime.device} "
            f"({runtime.reason})"
        )
    if args.provider.startswith("lane-") and lane_layout is None:
        raise SystemExit("--lane-layout is required for lane providers")
    if args.provider in {"tiled", "lane-tiled"}:
        provider_factory = lambda: MediaPipeTiledPoseProvider(
            args.model,
            max_swimmers=args.max_swimmers,
            tile_columns=columns if args.provider == "tiled" else 1,
            tile_rows=rows if args.provider == "tiled" else 1,
            tile_overlap=args.tile_overlap,
            pool_roi=pool_roi if args.provider == "tiled" else (0.0, 0.0, 1.0, 1.0),
            orientation=args.orientation,
        )
    elif args.provider == "whole-frame":
        provider_factory = lambda: MediaPipeMultiPoseProvider(args.model, max_swimmers=args.max_swimmers)
    elif args.provider == "lane-rtmpose-topdown":
        provider_factory = lambda: RTMPoseTopDownProvider(
            mode=runtime.mode,
            backend=runtime.backend,
            device=runtime.device,
        )
    else:
        provider_factory = lambda: RTMPoseProvider(
            mode=runtime.mode,
            backend=runtime.backend,
            device=runtime.device,
            max_swimmers=args.max_swimmers,
        )
    if args.provider == "lane-mosaic-rtmpose":
        inner_factory = provider_factory
        provider_factory = lambda: LaneMosaicPoseProvider(  # type: ignore[arg-type]
            inner_factory(),
            lane_layout,
            crop_padding=args.lane_crop_padding,
            rotation=args.lane_rotation,
        )
    elif args.provider.startswith("lane-"):
        inner_factory = provider_factory
        provider_factory = lambda: LaneCropPoseProvider(  # type: ignore[arg-type]
            inner_factory(),
            lane_layout,
            crop_padding=args.lane_crop_padding,
            rotation=args.lane_rotation,
        )
    started = time.perf_counter()
    analyzed_frames = 0
    cached_frames = []
    try:
        with provider_factory() as provider:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if frame_index % args.frame_step == 0:
                    timestamp_sec = frame_index / fps
                    if args.start_sec is not None and timestamp_sec < args.start_sec:
                        frame_index += 1
                        continue
                    if args.end_sec is not None and timestamp_sec >= args.end_sec:
                        break
                    if lane_layout is not None:
                        if (
                            lane_layout.active_start_sec is not None
                            and timestamp_sec < lane_layout.active_start_sec
                        ):
                            frame_index += 1
                            continue
                        if lane_layout.active_end_sec is not None and timestamp_sec > lane_layout.active_end_sec:
                            break
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    detections = provider.detect(rgb, int(timestamp_sec * 1000))
                    if args.pose_cache_out:
                        cached_frames.append(serialize_frame(frame_index, timestamp_sec, detections))
                    analyzer.process_frame(detections, frame_index, timestamp_sec)
                    analyzed_frames += 1
                frame_index += 1
    finally:
        capture.release()

    result = analyzer.finalize(distance_segments).to_dict()
    result["source_video_sha256"] = source_hash
    elapsed = time.perf_counter() - started
    result["run"] = {
        "provider": args.provider,
        "source_fps": fps,
        "frame_step": args.frame_step,
        "analyzed_frames": analyzed_frames,
        "elapsed_sec": round(elapsed, 3),
        "frames_per_sec": round(analyzed_frames / elapsed, 3) if elapsed > 0 else None,
        "lane_layout": str(args.lane_layout) if args.lane_layout else None,
        "runtime": runtime.to_dict() if runtime is not None else None,
    }
    if args.pose_cache_out:
        write_pose_cache(args.pose_cache_out, source_hash, fps, cached_frames, result["run"])
    save_result(args.output, result)
    return 0


def parse_distance_segments(args: argparse.Namespace) -> list[DistanceSegment]:
    if args.distance_segments:
        rows = json.loads(args.distance_segments.read_text(encoding="utf-8"))
        return [DistanceSegment(**row) for row in rows]
    if args.distance_m is None:
        if args.distance_track_id:
            raise ValueError("--distance-track-id requires --distance-m")
        return []
    if args.start_sec is None or args.end_sec is None or not args.distance_track_id:
        raise ValueError("--distance-m requires --start-sec, --end-sec and --distance-track-id")
    return [DistanceSegment(args.distance_track_id, args.start_sec, args.end_sec,
                            args.distance_m, args.distance_basis)]


def save_result(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(f"Saved {result['detected_track_count']} tracks to {path}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""Run the experimental multi-swimmer counter against a local video."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .mediapipe_provider import MediaPipeMultiPoseProvider, MediaPipeTiledPoseProvider
from .pipeline import MultiSwimmerAnalyzer
from .tracking import TrackerConfig
from .types import StrokeKind


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Experimental SwimMate multi-swimmer counter")
    parser.add_argument("video", type=Path)
    parser.add_argument("--stroke", choices=[item.value for item in StrokeKind], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=Path("analysis/pose_landmarker.task"))
    parser.add_argument("--max-swimmers", type=int, default=10)
    parser.add_argument("--lane-axis", choices=("x", "y"), default="y")
    parser.add_argument("--frame-step", type=int, default=2)
    parser.add_argument("--provider", choices=("tiled", "whole-frame"), default="tiled")
    parser.add_argument("--tile-grid", default="3x3", help="Tiled provider grid, for example 3x3")
    parser.add_argument("--tile-overlap", type=float, default=0.28)
    parser.add_argument(
        "--pool-roi",
        default="0,0,1,1",
        help="Normalized x1,y1,x2,y2 pool bounds; excludes spectators and officials",
    )
    parser.add_argument("--orientation", choices=("any", "horizontal", "vertical"), default="horizontal")
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

    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - optional offline dependency
        raise SystemExit("OpenCV is required for the offline video CLI") from exc

    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise SystemExit(f"Cannot open video: {args.video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    analyzer = MultiSwimmerAnalyzer(
        args.stroke,
        tracker_config=TrackerConfig(max_swimmers=args.max_swimmers, lane_axis=args.lane_axis),
    )

    frame_index = 0
    columns, rows = _parse_grid(args.tile_grid)
    pool_roi = _parse_roi(args.pool_roi)
    if args.provider == "tiled":
        provider_factory = lambda: MediaPipeTiledPoseProvider(
            args.model,
            max_swimmers=args.max_swimmers,
            tile_columns=columns,
            tile_rows=rows,
            tile_overlap=args.tile_overlap,
            pool_roi=pool_roi,
            orientation=args.orientation,
        )
    else:
        provider_factory = lambda: MediaPipeMultiPoseProvider(args.model, max_swimmers=args.max_swimmers)
    try:
        with provider_factory() as provider:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if frame_index % args.frame_step == 0:
                    timestamp_sec = frame_index / fps
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    detections = provider.detect(rgb, int(timestamp_sec * 1000))
                    analyzer.process_frame(detections, frame_index, timestamp_sec)
                frame_index += 1
    finally:
        capture.release()

    result = analyzer.finalize().to_dict()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {result['detected_track_count']} tracks to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

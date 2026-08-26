"""Generate close-up frame sheets for independent human count review.

The benchmark deliberately keeps model predictions separate from the labels.
This module uses a pose only to keep a selected swimmer near the centre of the
crop; it does not draw keypoints or predicted events on the review images.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from .benchmark import BenchmarkSample, load_manifest
from .lanes import LaneCropPoseProvider, LaneLayout
from .rtmpose_provider import RTMPoseTopDownProvider


def _selected_lane_layout(sample: BenchmarkSample, lane_id: int) -> LaneLayout:
    lane = next((item for item in sample.layout.lanes if item.lane_id == lane_id), None)
    if lane is None:
        raise ValueError(f"lane {lane_id} is not present in {sample.sample_id}")
    return LaneLayout((lane,), source=sample.sample_id)


def _crop_around_swimmer(
    frame: np.ndarray,
    centre: np.ndarray,
    sample: BenchmarkSample,
    lane_id: int,
) -> np.ndarray:
    height, width = frame.shape[:2]
    lane = next(item for item in sample.layout.lanes if item.lane_id == lane_id)
    x1, y1, x2, y2 = lane.bounds
    lane_width = max(1.0, (x2 - x1) * width)
    lane_height = max(1.0, (y2 - y1) * height)
    if sample.lane_axis == "x":
        crop_width = min(width, max(120.0, lane_width * 1.55))
        crop_height = min(height, max(260.0, crop_width * 2.2))
    else:
        crop_height = min(height, max(110.0, lane_height * 1.65))
        crop_width = min(width, max(260.0, crop_height * 2.25))

    centre_x = float(centre[0] * width)
    centre_y = float(centre[1] * height)
    left = int(np.clip(round(centre_x - crop_width / 2), 0, max(0, width - crop_width)))
    top = int(np.clip(round(centre_y - crop_height / 2), 0, max(0, height - crop_height)))
    right = min(width, left + int(round(crop_width)))
    bottom = min(height, top + int(round(crop_height)))
    return frame[top:bottom, left:right]


def generate_review_sheets(
    sample: BenchmarkSample,
    lane_id: int,
    output_dir: str | Path,
    sample_fps: float = 6.0,
    columns: int = 6,
    rows: int = 3,
    tile_size: tuple[int, int] = (400, 225),
) -> list[Path]:
    """Create chronological close-up sheets without prediction overlays."""

    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - optional offline dependency
        raise RuntimeError("OpenCV is required to generate review sheets") from exc
    if sample_fps <= 0 or columns < 1 or rows < 1:
        raise ValueError("sample_fps, columns, and rows must be positive")

    capture = cv2.VideoCapture(str(sample.video))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open {sample.video}")
    source_fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    frame_step = max(1, int(round(source_fps / sample_fps)))
    start_frame = max(0, int(round(sample.start_sec * source_fps)))
    end_frame = int(round(sample.end_sec * source_fps))
    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    selected_layout = _selected_lane_layout(sample, lane_id)
    provider = LaneCropPoseProvider(
        RTMPoseTopDownProvider(mode="lightweight"),
        selected_layout,
        crop_padding=0.25,
        rotation=sample.rotation,
    )
    lane = selected_layout.lanes[0]
    smoothed_centre = np.mean(lane.polygon, axis=0)
    tiles: list[np.ndarray] = []
    frame_index = start_frame
    try:
        while frame_index <= end_frame:
            ok, frame = capture.read()
            if not ok:
                break
            if (frame_index - start_frame) % frame_step == 0:
                timestamp_sec = frame_index / source_fps
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                detections = provider.detect(rgb, int(timestamp_sec * 1000))
                if detections:
                    smoothed_centre = 0.65 * smoothed_centre + 0.35 * detections[0].centroid
                crop = _crop_around_swimmer(frame, smoothed_centre, sample, lane_id)
                tile = cv2.resize(crop, tile_size, interpolation=cv2.INTER_CUBIC)
                cv2.rectangle(tile, (0, 0), (152, 25), (0, 0, 0), -1)
                cv2.putText(
                    tile,
                    f"{timestamp_sec:.2f}s",
                    (7, 18),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.52,
                    (80, 255, 255),
                    1,
                    cv2.LINE_AA,
                )
                tiles.append(tile)
            frame_index += 1
    finally:
        capture.release()
        provider.close()

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    page_size = columns * rows
    written: list[Path] = []
    for page_index in range(0, len(tiles), page_size):
        page_tiles = tiles[page_index : page_index + page_size]
        canvas = np.zeros((rows * tile_size[1], columns * tile_size[0], 3), dtype=np.uint8)
        for index, tile in enumerate(page_tiles):
            row, column = divmod(index, columns)
            y, x = row * tile_size[1], column * tile_size[0]
            canvas[y : y + tile_size[1], x : x + tile_size[0]] = tile
        page_number = page_index // page_size + 1
        path = output / f"{sample.sample_id}-lane{lane_id}-page{page_number:02d}.jpg"
        if not cv2.imwrite(str(path), canvas, [cv2.IMWRITE_JPEG_QUALITY, 94]):
            raise RuntimeError(f"failed to write {path}")
        written.append(path)
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate swimmer-centred manual review sheets")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("analysis/train/data/competition"))
    parser.add_argument("--sample", required=True, help="Benchmark sample ID")
    parser.add_argument("--lane", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sample-fps", type=float, default=6.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    _, samples = load_manifest(args.manifest, args.data_root)
    sample = next((item for item in samples if item.sample_id == args.sample), None)
    if sample is None:
        raise ValueError(f"unknown sample: {args.sample}")
    written = generate_review_sheets(
        sample,
        args.lane,
        args.output_dir,
        sample_fps=args.sample_fps,
    )
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

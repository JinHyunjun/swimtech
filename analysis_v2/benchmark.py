"""Reproducible offline benchmark for multi-swimmer race clips."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Callable

import numpy as np

from .counting import CounterConfig
from .lanes import LaneCropPoseProvider, LaneLayout, assign_detections_to_lanes
from .mediapipe_provider import MediaPipeTiledPoseProvider
from .pipeline import MultiSwimmerAnalyzer
from .rtmpose_provider import RTMPoseTopDownProvider
from .runtime import PoseRuntimeConfig, select_pose_runtime
from .tracking import TrackerConfig


@dataclass(frozen=True)
class BenchmarkSample:
    sample_id: str
    stroke_kind: str
    video: Path
    start_sec: float
    end_sec: float
    lane_axis: str
    rotation: str
    evaluation_lane_id: int
    layout: LaneLayout
    ground_truth: tuple[dict[str, object], ...]


def _resolve_video(root: Path, kind: str, prefix: str) -> Path:
    directory = root / f"competition_{kind}"
    matches = sorted(path for path in directory.glob("*.mp4") if path.name.startswith(prefix))
    if len(matches) != 1:
        raise ValueError(f"{kind}/{prefix!r} resolved to {len(matches)} videos")
    return matches[0]


def load_manifest(path: str | Path, data_root: str | Path) -> tuple[dict[str, object], list[BenchmarkSample]]:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    root = Path(data_root)
    samples: list[BenchmarkSample] = []
    for item in manifest["samples"]:
        kind = str(item["stroke_kind"])
        layout_data = dict(item["layout"])
        layout_data["active_interval_sec"] = item["interval_sec"]
        samples.append(
            BenchmarkSample(
                sample_id=str(item["id"]),
                stroke_kind=kind,
                video=_resolve_video(root, kind, str(item["video_prefix"])),
                start_sec=float(item["interval_sec"][0]),
                end_sec=float(item["interval_sec"][1]),
                lane_axis=str(item.get("lane_axis", "y")),
                rotation=str(item.get("rotation", "clockwise")),
                evaluation_lane_id=int(item["evaluation_lane_id"]),
                layout=LaneLayout.from_dict(layout_data),
                ground_truth=tuple(item.get("ground_truth", [])),
            )
        )
    return manifest, samples


def _create_provider(
    name: str,
    layout: LaneLayout,
    rotation: str,
    runtime: PoseRuntimeConfig | None = None,
):
    if name == "baseline-mediapipe-tiled":
        return MediaPipeTiledPoseProvider(
            "analysis/pose_landmarker.task",
            max_swimmers=10,
            tile_columns=3,
            tile_rows=3,
            tile_overlap=0.28,
            pool_roi=(0.0, 0.0, 1.0, 1.0),
            orientation="any",
        )
    if name == "lane-rtmpose-topdown":
        runtime = runtime or select_pose_runtime("portable")
        return LaneCropPoseProvider(
            RTMPoseTopDownProvider(
                mode=runtime.mode,
                backend=runtime.backend,
                device=runtime.device,
            ),
            layout,
            crop_padding=0.25,
            rotation=rotation,
        )
    raise ValueError(f"unsupported provider: {name}")


def analyze_sample(
    sample: BenchmarkSample,
    provider_name: str,
    sample_fps: float = 6.0,
    runtime: PoseRuntimeConfig | None = None,
) -> dict[str, object]:
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - offline dependency
        raise RuntimeError("OpenCV is required for the offline benchmark") from exc
    capture = cv2.VideoCapture(str(sample.video))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open {sample.video}")
    source_fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    frame_step = max(1, int(round(source_fps / sample_fps)))
    start_frame = max(0, int(round(sample.start_sec * source_fps)))
    end_frame = int(round(sample.end_sec * source_fps))
    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    counter_config = CounterConfig(
        smoothing_window=3,
        min_track_frames=max(12, int(round(sample_fps * 2.5))),
    )
    if provider_name == "lane-rtmpose-topdown":
        counter_config = CounterConfig(
            smoothing_window=3,
            min_track_frames=max(12, int(round(sample_fps * 2.5))),
            min_landmark_confidence=0.12,
            min_arm_visibility=0.45,
            min_leg_visibility=0.50,
        )
    analyzer = MultiSwimmerAnalyzer(
        sample.stroke_kind,
        tracker_config=TrackerConfig(
            max_swimmers=len(sample.layout.lanes),
            lane_axis=sample.lane_axis,
            max_missing_frames=max(3, int(round(sample_fps * 1.5))),
        ),
        counter_config=counter_config,
    )
    lane_hits = {lane.lane_id: 0 for lane in sample.layout.lanes}
    detections_per_frame: list[int] = []
    processed = 0
    previous_histogram: np.ndarray | None = None
    scene_change_scores: list[tuple[float, float]] = []
    frame_index = start_frame
    started = time.perf_counter()
    provider = _create_provider(provider_name, sample.layout, sample.rotation, runtime)
    try:
        while frame_index <= end_frame:
            ok, frame = capture.read()
            if not ok:
                break
            if (frame_index - start_frame) % frame_step == 0:
                timestamp_sec = frame_index / source_fps
                preview = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
                hsv = cv2.cvtColor(preview, cv2.COLOR_BGR2HSV)
                histogram = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
                cv2.normalize(histogram, histogram)
                if previous_histogram is not None:
                    score = float(
                        cv2.compareHist(
                            previous_histogram,
                            histogram,
                            cv2.HISTCMP_BHATTACHARYYA,
                        )
                    )
                    scene_change_scores.append((timestamp_sec, score))
                previous_histogram = histogram
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                detections = provider.detect(rgb, int(timestamp_sec * 1000))
                if provider_name == "baseline-mediapipe-tiled":
                    assigned = assign_detections_to_lanes(detections, sample.layout)
                    # Use the same physical-lane identity for an apples-to-apples
                    # counting comparison while retaining the previous detector.
                    analyzer_detections = assigned
                else:
                    assigned = detections
                    analyzer_detections = detections
                for detection in assigned:
                    if detection.lane_hint in lane_hits:
                        lane_hits[int(detection.lane_hint)] += 1
                detections_per_frame.append(len(assigned))
                analyzer.process_frame(analyzer_detections, frame_index, timestamp_sec)
                processed += 1
            frame_index += 1
    finally:
        capture.release()
        provider.close()
    elapsed = time.perf_counter() - started
    result = analyzer.finalize().to_dict()
    result["benchmark"] = {
        "sample_id": sample.sample_id,
        "video": sample.video.name,
        "interval_sec": [sample.start_sec, sample.end_sec],
        "provider": provider_name,
        "source_fps": round(source_fps, 3),
        "sample_fps": sample_fps,
        "processed_frames": processed,
        "elapsed_sec": round(elapsed, 3),
        "inference_fps": round(processed / elapsed, 3) if elapsed else None,
        "mean_detected_lanes": round(float(np.mean(detections_per_frame)), 3)
        if detections_per_frame
        else 0.0,
        "lane_detection_coverage": {
            str(lane_id): round(hits / max(processed, 1), 3) for lane_id, hits in lane_hits.items()
        },
        "scene_stability": {
            "max_change_score": round(max((score for _, score in scene_change_scores), default=0.0), 4),
            "suspected_cuts": [
                {"timestamp_sec": round(timestamp, 3), "score": round(score, 4)}
                for timestamp, score in scene_change_scores
                if score >= 0.35
            ],
            "threshold": 0.35,
        },
        "runtime": runtime.to_dict() if runtime is not None else None,
    }
    return result


def _prediction_by_lane(result: dict[str, object]) -> dict[int, dict[str, object]]:
    predictions: dict[int, dict[str, object]] = {}
    for track in result.get("tracks", []):
        lane_id = int(track["lane_id"])
        existing = predictions.get(lane_id)
        if existing is None or int(track["observed_frames"]) > int(existing["observed_frames"]):
            predictions[lane_id] = track
    return predictions


def match_events(
    expected: list[float] | tuple[float, ...],
    predicted: list[float] | tuple[float, ...],
    tolerance_sec: float = 0.25,
) -> dict[str, object]:
    """Greedily match predicted event timestamps to independent labels."""

    truth = sorted(float(item) for item in expected)
    candidates = sorted(float(item) for item in predicted)
    unused = set(range(len(candidates)))
    errors: list[float] = []
    for target in truth:
        possible = [
            index
            for index in unused
            if abs(candidates[index] - target) <= tolerance_sec
        ]
        if not possible:
            continue
        selected = min(possible, key=lambda index: abs(candidates[index] - target))
        unused.remove(selected)
        errors.append(abs(candidates[selected] - target))
    matched = len(errors)
    precision = matched / len(candidates) if candidates else (1.0 if not truth else 0.0)
    recall = matched / len(truth) if truth else (1.0 if not candidates else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "expected_events": len(truth),
        "predicted_events": len(candidates),
        "matched_events": matched,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "timing_mae_sec": round(float(np.mean(errors)), 4) if errors else None,
        "tolerance_sec": tolerance_sec,
    }


def score_result(sample: BenchmarkSample, result: dict[str, object]) -> dict[str, object] | None:
    if not sample.ground_truth:
        return None
    predicted = _prediction_by_lane(result)
    metrics: dict[str, object] = {}
    for truth_key, prediction_key in (("arm_strokes", "arm_strokes"), ("kicks", "kicks")):
        event_key = "arm_event_times_sec" if truth_key == "arm_strokes" else "kick_event_times_sec"
        rows: list[dict[str, object]] = []
        for truth in sample.ground_truth:
            expected = truth.get(truth_key)
            expected_events = truth.get(event_key)
            if expected is None and isinstance(expected_events, list):
                expected = len(expected_events)
            if expected is None:
                continue
            lane_id = int(truth["lane_id"])
            event = predicted.get(lane_id, {}).get(prediction_key, {})
            available = bool(event.get("available", False))
            value = int(event["count"]) if available else None
            error = abs(value - int(expected)) if value is not None else None
            normalized_accuracy = (
                max(0.0, 1.0 - error / max(int(expected), 1)) if error is not None else 0.0
            )
            rows.append(
                {
                    "lane_id": lane_id,
                    "expected": int(expected),
                    "predicted": value,
                    "absolute_error": error,
                    "normalized_accuracy": round(normalized_accuracy, 4),
                    "event_timing": match_events(
                        expected_events,
                        event.get("event_times_sec", []) if available else [],
                    )
                    if isinstance(expected_events, list)
                    else None,
                }
            )
        available_rows = [row for row in rows if row["predicted"] is not None]
        metrics[truth_key] = {
            "labeled": len(rows),
            "available": len(available_rows),
            "coverage": round(len(available_rows) / max(len(rows), 1), 4),
            "mae_when_available": round(
                float(np.mean([row["absolute_error"] for row in available_rows])), 4
            )
            if available_rows
            else None,
            "within_one_rate": round(
                sum(int(row["absolute_error"]) <= 1 for row in available_rows)
                / max(len(available_rows), 1),
                4,
            ),
            "end_to_end_accuracy": round(
                float(np.mean([row["normalized_accuracy"] for row in rows])), 4
            )
            if rows
            else None,
            "rows": rows,
        }
    return metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SwimMate multi-swimmer offline benchmark")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("analysis/train/data/competition"),
    )
    parser.add_argument(
        "--provider",
        choices=("baseline-mediapipe-tiled", "lane-rtmpose-topdown"),
        required=True,
    )
    parser.add_argument("--sample-fps", type=float, default=6.0)
    parser.add_argument(
        "--runtime-profile",
        choices=("auto", "quality", "balanced", "portable"),
        default="portable",
        help="Portable preserves the v0.2 benchmark; use quality for this machine",
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
    parser.add_argument("--only", nargs="*", help="Optional sample IDs")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest, samples = load_manifest(args.manifest, args.data_root)
    runtime = None
    if args.provider == "lane-rtmpose-topdown":
        runtime = select_pose_runtime(
            args.runtime_profile,
            args.backend,
            args.device,
            args.pose_mode,
        )
    if args.only:
        requested = set(args.only)
        samples = [sample for sample in samples if sample.sample_id in requested]
    results: list[dict[str, object]] = []
    for sample in samples:
        # Some source filenames contain emoji that the default Windows cp949
        # console cannot encode. Keep progress output ASCII-only so a long
        # benchmark does not fail after inference has already started.
        print(f"[{args.provider}] {sample.sample_id}", flush=True)
        result = analyze_sample(sample, args.provider, args.sample_fps, runtime)
        score = score_result(sample, result)
        if score is not None:
            result["score"] = score
        results.append(result)
    payload = {
        "benchmark_version": "multiswimmer-benchmark-v0.1.0",
        "manifest_seed": manifest.get("seed"),
        "provider": args.provider,
        "runtime": runtime.to_dict() if runtime is not None else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_count": len(results),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(results)} samples to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

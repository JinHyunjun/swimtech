"""Offline regression tests for the experimental multi-swimmer counter."""

from __future__ import annotations

import math
import json
from pathlib import Path

import numpy as np
import pytest

from analysis_v2 import (
    CounterConfig,
    MultiSwimmerAnalyzer,
    MultiSwimmerTracker,
    PoseDetection,
    StrokeKind,
    TrackerConfig,
)
from analysis_v2.types import KeypointIndex
from analysis_v2.mediapipe_provider import build_overlapping_tiles, deduplicate_detections
from analysis_v2.lanes import LaneLayout, LaneRegion, assign_detections_to_lanes
from analysis_v2.rtmpose_provider import coco_pose_to_detection
from analysis_v2.benchmark import BenchmarkSample, score_result


def _synthetic_swimmer(
    center_x: float,
    lane_y: float,
    timestamp: float,
    stroke_hz: float = 0.5,
    kick_hz: float = 0.65,
    synchronous_arms: bool = False,
    leg_visibility: float = 0.95,
) -> PoseDetection:
    """Build a horizontal swimmer with controllable periodic limbs."""

    points = np.zeros((33, 4), dtype=np.float64)
    points[:, 0] = center_x - 0.04
    points[:, 1] = lane_y
    points[:, 3] = 0.05

    hip_mid = np.array([center_x - 0.06, lane_y])
    shoulder_mid = np.array([center_x, lane_y])
    arm_phase = 2.0 * math.pi * stroke_hz * timestamp
    right_phase = arm_phase if synchronous_arms else arm_phase + math.pi
    kick_phase = 2.0 * math.pi * kick_hz * timestamp

    def put(index: int, x: float, y: float, confidence: float = 0.95) -> None:
        points[int(index)] = [x, y, 0.0, confidence]

    put(KeypointIndex.NOSE, center_x + 0.045, lane_y)
    put(KeypointIndex.LEFT_SHOULDER, shoulder_mid[0], lane_y - 0.018)
    put(KeypointIndex.RIGHT_SHOULDER, shoulder_mid[0], lane_y + 0.018)
    put(KeypointIndex.LEFT_HIP, hip_mid[0], lane_y - 0.016)
    put(KeypointIndex.RIGHT_HIP, hip_mid[0], lane_y + 0.016)
    put(KeypointIndex.LEFT_ELBOW, center_x + 0.055, lane_y - 0.026)
    put(KeypointIndex.RIGHT_ELBOW, center_x + 0.055, lane_y + 0.026)
    put(
        KeypointIndex.LEFT_WRIST,
        hip_mid[0] + 0.13 + 0.075 * math.sin(arm_phase),
        lane_y - 0.032,
    )
    put(
        KeypointIndex.RIGHT_WRIST,
        hip_mid[0] + 0.13 + 0.075 * math.sin(right_phase),
        lane_y + 0.032,
    )
    put(KeypointIndex.LEFT_KNEE, hip_mid[0] - 0.07, lane_y - 0.012, leg_visibility)
    put(KeypointIndex.RIGHT_KNEE, hip_mid[0] - 0.07, lane_y + 0.012, leg_visibility)
    put(
        KeypointIndex.LEFT_ANKLE,
        hip_mid[0] - 0.14,
        lane_y + 0.04 * math.sin(kick_phase),
        leg_visibility,
    )
    put(
        KeypointIndex.RIGHT_ANKLE,
        hip_mid[0] - 0.14,
        lane_y - 0.04 * math.sin(kick_phase),
        leg_visibility,
    )
    return PoseDetection.from_keypoints(points)


def test_tracker_keeps_lane_ids_when_detection_order_changes_and_pose_is_missing() -> None:
    tracker = MultiSwimmerTracker(
        TrackerConfig(max_swimmers=8, max_missing_frames=3, max_centroid_distance=0.30)
    )

    tracker.update(
        [_synthetic_swimmer(0.20, 0.25, 0.0), _synthetic_swimmer(0.18, 0.75, 0.0)],
        0,
        0.0,
    )
    tracker.update(
        [_synthetic_swimmer(0.21, 0.75, 0.1), _synthetic_swimmer(0.23, 0.25, 0.1)],
        1,
        0.1,
    )
    tracker.update([_synthetic_swimmer(0.24, 0.75, 0.2)], 2, 0.2)
    tracker.update(
        [_synthetic_swimmer(0.27, 0.25, 0.3), _synthetic_swimmer(0.27, 0.75, 0.3)],
        3,
        0.3,
    )

    tracks = tracker.all_tracks()
    assert len(tracks) == 2
    assert tracks[0][0].track_id == "S001"
    assert tracks[1][0].track_id == "S002"
    assert [row.detection.centroid[1] for row in tracks[0]] == pytest.approx([0.25, 0.25, 0.25])
    assert [row.detection.centroid[1] for row in tracks[1]] == pytest.approx([0.75, 0.75, 0.75, 0.75])


def test_pipeline_counts_each_swimmer_independently() -> None:
    analyzer = MultiSwimmerAnalyzer(
        StrokeKind.FREESTYLE,
        tracker_config=TrackerConfig(max_swimmers=8, max_centroid_distance=0.24),
        counter_config=CounterConfig(smoothing_window=3),
    )
    fps = 10.0
    for frame_index in range(121):
        timestamp = frame_index / fps
        first = _synthetic_swimmer(0.15 + frame_index * 0.001, 0.28, timestamp, 0.50, 0.65)
        second = _synthetic_swimmer(0.12 + frame_index * 0.001, 0.72, timestamp, 0.33, 0.45)
        # A pose detector does not promise a stable result order.
        detections = [second, first] if frame_index % 2 else [first, second]
        analyzer.process_frame(detections, frame_index, timestamp)

    result = analyzer.finalize()
    assert result.experimental is True
    assert result.detected_track_count == 2
    first, second = result.tracks
    assert first.track_id == "S001" and second.track_id == "S002"
    assert first.arm_strokes.available and second.arm_strokes.available
    assert first.kicks.available and second.kicks.available
    assert first.arm_strokes.count > second.arm_strokes.count
    assert first.kicks.count > second.kicks.count
    assert first.complete_cycles >= 5
    assert second.complete_cycles >= 3
    assert first.arm_strokes.count == len(first.left_arm_events) + len(first.right_arm_events)


def test_synchronous_butterfly_arms_are_not_double_counted() -> None:
    analyzer = MultiSwimmerAnalyzer(
        StrokeKind.BUTTERFLY,
        counter_config=CounterConfig(smoothing_window=3),
    )
    for frame_index in range(101):
        timestamp = frame_index / 10.0
        pose = _synthetic_swimmer(
            0.30 + frame_index * 0.0005,
            0.50,
            timestamp,
            stroke_hz=0.45,
            kick_hz=0.9,
            synchronous_arms=True,
        )
        analyzer.process_frame([pose], frame_index, timestamp)

    track = analyzer.finalize().tracks[0]
    assert track.arm_strokes.available
    assert track.complete_cycles == track.arm_strokes.count
    assert track.arm_strokes.count <= max(len(track.left_arm_events), len(track.right_arm_events)) + 1


def test_kick_count_is_withheld_when_legs_are_not_visible() -> None:
    analyzer = MultiSwimmerAnalyzer(
        StrokeKind.FREESTYLE,
        counter_config=CounterConfig(smoothing_window=3),
    )
    for frame_index in range(81):
        timestamp = frame_index / 10.0
        analyzer.process_frame(
            [_synthetic_swimmer(0.25, 0.5, timestamp, leg_visibility=0.10)],
            frame_index,
            timestamp,
        )

    track = analyzer.finalize().tracks[0]
    assert track.arm_strokes.available
    assert track.kicks.available is False
    assert track.kicks.reason == "legs_not_visible"
    assert "kick_count_withheld_low_leg_visibility" in track.warnings


def test_counts_are_withheld_for_a_fragmented_track() -> None:
    analyzer = MultiSwimmerAnalyzer(
        StrokeKind.FREESTYLE,
        tracker_config=TrackerConfig(max_missing_frames=4),
        counter_config=CounterConfig(smoothing_window=3),
    )
    for frame_index in range(100):
        timestamp = frame_index / 10.0
        # A pose exists often enough to keep an ID but not enough to claim a full-race count.
        detections = (
            [_synthetic_swimmer(0.25 + frame_index * 0.0005, 0.5, timestamp)]
            if frame_index % 3 == 0
            else []
        )
        analyzer.process_frame(detections, frame_index, timestamp)

    track = analyzer.finalize().tracks[0]
    assert track.track_coverage < 0.60
    assert track.arm_strokes.available is False
    assert track.arm_strokes.reason == "track_coverage_too_low"
    assert track.kicks.reason == "track_coverage_too_low"
    assert "counts_withheld_fragmented_track" in track.warnings


def test_non_monotonic_video_input_is_rejected() -> None:
    analyzer = MultiSwimmerAnalyzer(StrokeKind.FREESTYLE)
    analyzer.process_frame([_synthetic_swimmer(0.2, 0.5, 0.0)], 0, 0.0)
    with pytest.raises(ValueError, match="frame_index"):
        analyzer.process_frame([_synthetic_swimmer(0.2, 0.5, 0.1)], 0, 0.1)


def test_overlapping_tile_detections_are_deduplicated() -> None:
    original = _synthetic_swimmer(0.40, 0.35, 0.0)
    shifted_points = original.keypoints.copy()
    shifted_points[:, 0] += 0.004
    duplicate = PoseDetection.from_keypoints(shifted_points, confidence=0.80)
    other = _synthetic_swimmer(0.40, 0.72, 0.0)

    kept = deduplicate_detections([duplicate, other, original])
    assert len(kept) == 2
    assert any(abs(item.centroid[1] - 0.35) < 0.01 for item in kept)
    assert any(abs(item.centroid[1] - 0.72) < 0.01 for item in kept)


def test_pool_tiles_stay_inside_roi_and_cover_grid() -> None:
    tiles = build_overlapping_tiles(1000, 500, 3, 2, 0.30, (0.1, 0.2, 0.9, 0.8))
    assert len(tiles) == 6
    assert all(100 <= x1 < x2 <= 900 for x1, _, x2, _ in tiles)
    assert all(100 <= y1 < y2 <= 400 for _, y1, _, y2 in tiles)


def test_perspective_lane_polygons_assign_fixed_lane_ids() -> None:
    layout = LaneLayout(
        (
            LaneRegion(3, np.asarray([[0.0, 0.15], [1.0, 0.05], [1.0, 0.35], [0.0, 0.45]])),
            LaneRegion(4, np.asarray([[0.0, 0.45], [1.0, 0.35], [1.0, 0.65], [0.0, 0.75]])),
        )
    )
    lane_three = _synthetic_swimmer(0.45, 0.25, 0.0)
    lane_four = _synthetic_swimmer(0.45, 0.55, 0.0)
    spectator = _synthetic_swimmer(0.45, 0.90, 0.0)

    assigned = assign_detections_to_lanes([spectator, lane_four, lane_three], layout)

    assert [item.lane_hint for item in assigned] == [3, 4]


def test_tracker_uses_physical_lane_id_across_long_detection_gap() -> None:
    tracker = MultiSwimmerTracker(TrackerConfig(max_missing_frames=1, max_centroid_distance=0.10))
    first = _synthetic_swimmer(0.20, 0.30, 0.0)
    first = PoseDetection.from_keypoints(first.keypoints, lane_hint=6)
    tracker.update([first], 0, 0.0)
    tracker.update([], 1, 0.1)
    tracker.update([], 2, 0.2)
    returned = _synthetic_swimmer(0.70, 0.25, 0.3)
    returned = PoseDetection.from_keypoints(returned.keypoints, lane_hint=6)
    tracker.update([returned], 3, 0.3)

    tracks = tracker.all_tracks()
    assert len(tracks) == 1
    assert tracks[0][0].track_id == "L06"
    assert tracks[0][-1].track_id == "L06"
    assert len(tracks[0]) == 2


def test_coco_rtmpose_output_maps_to_counter_keypoints() -> None:
    keypoints = np.zeros((17, 2), dtype=np.float64)
    scores = np.full(17, 0.9, dtype=np.float64)
    keypoints[5] = [100, 40]
    keypoints[6] = [120, 40]
    keypoints[11] = [95, 80]
    keypoints[12] = [125, 80]
    keypoints[15] = [70, 100]
    keypoints[16] = [150, 100]

    detection = coco_pose_to_detection(keypoints, scores, 200, 120)

    assert detection is not None
    assert detection.keypoints[KeypointIndex.LEFT_SHOULDER, :2] == pytest.approx([0.5, 1 / 3])
    assert detection.keypoints[KeypointIndex.RIGHT_ANKLE, :2] == pytest.approx([0.75, 5 / 6])
    assert detection.confidence == pytest.approx(0.9)


def test_lane_trapezoid_generates_horizontal_and_vertical_regions() -> None:
    corners = np.asarray([[0.1, 0.2], [0.9, 0.1], [1.0, 0.9], [0.0, 0.8]])
    horizontal = LaneLayout.from_trapezoid((1, 2, 3, 4), corners, "horizontal")
    vertical = LaneLayout.from_trapezoid((5, 6), corners, "vertical")

    assert len(horizontal.lanes) == 4
    assert horizontal.lane_for_point(np.asarray([0.5, 0.3])).lane_id in {1, 2}
    assert len(vertical.lanes) == 2
    assert vertical.lane_for_point(np.asarray([0.25, 0.5])).lane_id == 5
    assert vertical.lane_for_point(np.asarray([0.75, 0.5])).lane_id == 6


def test_real_video_benchmark_manifest_has_five_samples_per_stroke() -> None:
    manifest_path = Path("analysis_v2/evaluation/benchmark_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    samples = manifest["samples"]

    assert len(samples) == 20
    for stroke_kind in ("freestyle", "backstroke", "breaststroke", "butterfly"):
        assert sum(item["stroke_kind"] == stroke_kind for item in samples) == 5
    assert len({item["id"] for item in samples}) == 20
    for item in samples:
        layout = LaneLayout.from_dict(item["layout"])
        assert item["evaluation_lane_id"] in {lane.lane_id for lane in layout.lanes}
        assert item["interval_sec"][1] - item["interval_sec"][0] >= 2.5


def test_benchmark_scoring_counts_abstention_as_zero_end_to_end_accuracy() -> None:
    layout = LaneLayout(
        (LaneRegion(1, np.asarray([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])),)
    )
    sample = BenchmarkSample(
        sample_id="fixture",
        stroke_kind="freestyle",
        video=Path("fixture.mp4"),
        start_sec=0.0,
        end_sec=5.0,
        lane_axis="y",
        rotation="clockwise",
        evaluation_lane_id=1,
        layout=layout,
        ground_truth=({"lane_id": 1, "arm_strokes": 8, "kicks": 12},),
    )
    result = {
        "tracks": [
            {
                "lane_id": 1,
                "observed_frames": 30,
                "arm_strokes": {"available": True, "count": 7},
                "kicks": {"available": False, "count": 0},
            }
        ]
    }

    score = score_result(sample, result)

    assert score is not None
    assert score["arm_strokes"]["mae_when_available"] == 1.0
    assert score["arm_strokes"]["end_to_end_accuracy"] == 0.875
    assert score["kicks"]["coverage"] == 0.0
    assert score["kicks"]["end_to_end_accuracy"] == 0.0

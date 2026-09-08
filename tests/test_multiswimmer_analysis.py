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
    StrokeSource,
    TrackerConfig,
)
from analysis_v2.counting import _reconcile_events, _find_peak_events
from analysis_v2.distance import DistanceSegment
from analysis_v2.cli import main as counter_cli, build_parser as counter_parser, parse_distance_segments
from analysis_v2.pose_cache import video_sha256, serialize_frame, write_pose_cache, read_pose_cache
from analysis_v2.types import KeypointIndex
from analysis_v2.mediapipe_provider import build_overlapping_tiles, deduplicate_detections
from analysis_v2.lanes import (
    LaneCropPoseProvider,
    LaneLayout,
    LaneRegion,
    assign_detections_to_lanes,
    lane_direction,
    pose_lane_alignment,
)
from analysis_v2.rtmpose_provider import coco_pose_to_detection
from analysis_v2.annotation import build_annotation
from analysis_v2.adjudication import build_review_report, compare_annotations
from analysis_v2.benchmark import BenchmarkSample, match_events, score_result
from analysis_v2.runtime import select_pose_runtime
from analysis_v2.runtime_benchmark import choose_recommendation


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
        counter_config=CounterConfig(
            smoothing_window=3,
            minimum_flutter_kick_sample_hz=0.0,
        ),
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
    assert first.arm_strokes.count <= len(first.left_arm_events) + len(first.right_arm_events)
    assert first.complete_cycles == first.arm_strokes.count // 2


def test_alternating_stroke_identity_swap_withholds_ambiguous_count() -> None:
    analyzer = MultiSwimmerAnalyzer(
        StrokeKind.FREESTYLE,
        counter_config=CounterConfig(smoothing_window=3),
    )
    for frame_index in range(101):
        timestamp = frame_index / 10.0
        # Simulate the common underwater failure where both detected wrist
        # identities follow the same physical arm phase.
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
    raw_events = len(track.left_arm_events) + len(track.right_arm_events)
    assert raw_events > 0
    assert track.arm_pattern == "synchronous"
    assert track.arm_strokes.available is False
    assert track.arm_strokes.reason == "arm_identity_ambiguous"
    assert "alternating_arm_count_withheld_synchronous_pose_artifact" in track.warnings


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


def test_alternating_motion_is_rejected_when_labeled_as_synchronous_stroke() -> None:
    analyzer = MultiSwimmerAnalyzer(
        StrokeKind.BUTTERFLY,
        counter_config=CounterConfig(smoothing_window=3),
        stroke_source=StrokeSource.USER_CONFIRMED,
    )
    for frame_index in range(121):
        timestamp = frame_index / 20.0
        analyzer.process_frame(
            [_synthetic_swimmer(0.30, 0.50, timestamp, stroke_hz=0.65)],
            frame_index,
            timestamp,
        )

    track = analyzer.finalize().tracks[0]
    assert track.arm_pattern == "alternating"
    assert track.arm_strokes.available is False
    assert track.arm_strokes.reason == "stroke_pattern_conflict"
    assert "selected_stroke_conflicts_with_observed_arm_pattern" in track.warnings


def test_near_duplicate_events_are_reconciled_before_counting() -> None:
    assert _reconcile_events([1.0, 1.08, 1.31, 2.0], 0.22) == [1.04, 1.31, 2.0]


def test_flutter_kicks_are_withheld_when_temporal_sampling_is_too_low() -> None:
    analyzer = MultiSwimmerAnalyzer(
        StrokeKind.FREESTYLE,
        counter_config=CounterConfig(smoothing_window=3),
    )
    for frame_index in range(81):
        timestamp = frame_index / 10.0
        analyzer.process_frame(
            [_synthetic_swimmer(0.25, 0.5, timestamp)],
            frame_index,
            timestamp,
        )

    result = analyzer.finalize()
    track = result.tracks[0]
    assert result.sample_rate_hz == pytest.approx(10.0)
    assert track.kicks.available is False
    assert track.kicks.reason == "sample_rate_too_low_for_kicks"
    assert "kick_count_withheld_low_sample_rate" in track.warnings


def test_kicks_require_knees_as_well_as_ankles() -> None:
    analyzer = MultiSwimmerAnalyzer(
        StrokeKind.FREESTYLE,
        counter_config=CounterConfig(smoothing_window=3),
    )
    for frame_index in range(121):
        timestamp = frame_index / 20.0
        pose = _synthetic_swimmer(0.25, 0.5, timestamp)
        points = pose.keypoints.copy()
        points[int(KeypointIndex.LEFT_KNEE), 3] = 0.05
        points[int(KeypointIndex.RIGHT_KNEE), 3] = 0.05
        analyzer.process_frame(
            [PoseDetection.from_keypoints(points)],
            frame_index,
            timestamp,
        )

    track = analyzer.finalize().tracks[0]
    assert track.kicks.available is False
    assert track.kicks.reason == "legs_not_visible"


def test_implausible_freestyle_kick_to_stroke_ratio_is_withheld() -> None:
    analyzer = MultiSwimmerAnalyzer(
        StrokeKind.FREESTYLE,
        counter_config=CounterConfig(smoothing_window=3),
    )
    for frame_index in range(241):
        timestamp = frame_index / 20.0
        analyzer.process_frame(
            [
                _synthetic_swimmer(
                    0.25,
                    0.5,
                    timestamp,
                    stroke_hz=0.60,
                    kick_hz=0.20,
                )
            ],
            frame_index,
            timestamp,
        )

    track = analyzer.finalize().tracks[0]
    assert track.arm_strokes.available
    assert track.complete_cycles > 0
    assert track.kicks.available is False
    assert track.kicks.reason == "kick_stroke_ratio_implausible"
    assert "kick_count_withheld_implausible_stroke_ratio" in track.warnings


def test_output_retains_stroke_label_provenance() -> None:
    analyzer = MultiSwimmerAnalyzer(
        StrokeKind.FREESTYLE,
        stroke_source=StrokeSource.USER_CONFIRMED,
    )
    for frame_index in range(3):
        timestamp = frame_index / 20.0
        analyzer.process_frame([_synthetic_swimmer(0.25, 0.5, timestamp)], frame_index, timestamp)

    output = analyzer.finalize().to_dict()
    assert output["stroke_source"] == "user_confirmed"
    assert output["sample_rate_hz"] == pytest.approx(20.0)


def test_arm_count_is_stable_across_supported_sampling_rates() -> None:
    counts: list[int] = []
    for fps in (10.0, 20.0, 30.0):
        analyzer = MultiSwimmerAnalyzer(
            StrokeKind.FREESTYLE,
            counter_config=CounterConfig(
                minimum_flutter_kick_sample_hz=0.0,
            ),
        )
        for frame_index in range(int(fps * 12) + 1):
            timestamp = frame_index / fps
            analyzer.process_frame(
                [_synthetic_swimmer(0.25, 0.5, timestamp, stroke_hz=0.5)],
                frame_index,
                timestamp,
            )
        track = analyzer.finalize().tracks[0]
        assert track.arm_strokes.available
        counts.append(track.arm_strokes.count)

    assert max(counts) - min(counts) <= 1


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


def test_lane_crop_rejects_pose_with_torso_anchors_outside_lane() -> None:
    class StubProvider:
        def detect(self, rgb_frame: np.ndarray, timestamp_ms: int) -> list[PoseDetection]:
            del rgb_frame, timestamp_ms
            pose = _synthetic_swimmer(0.50, 0.50, 0.0)
            points = pose.keypoints.copy()
            points[KeypointIndex.LEFT_SHOULDER, 1] = 0.10
            points[KeypointIndex.RIGHT_SHOULDER, 1] = 0.10
            points[KeypointIndex.LEFT_HIP, 1] = 0.90
            points[KeypointIndex.RIGHT_HIP, 1] = 0.90
            return [PoseDetection.from_keypoints(points)]

    layout = LaneLayout(
        (LaneRegion(1, np.asarray([[0.0, 0.4], [1.0, 0.4], [1.0, 0.6], [0.0, 0.6]])),)
    )
    provider = LaneCropPoseProvider(
        StubProvider(),
        layout,
        crop_padding=0.5,
        min_anchor_inside_ratio=0.75,
    )

    assert provider.detect(np.zeros((100, 200, 3), dtype=np.uint8), 0) == []


def test_lane_alignment_rejects_upright_spectator_and_accepts_swimmer() -> None:
    lane = LaneRegion(
        1,
        np.asarray([[0.0, 0.35], [1.0, 0.35], [1.0, 0.65], [0.0, 0.65]]),
    )
    swimmer = _synthetic_swimmer(0.50, 0.50, 0.0)
    upright_points = swimmer.keypoints.copy()
    upright_points[KeypointIndex.LEFT_SHOULDER, :2] = [0.48, 0.40]
    upright_points[KeypointIndex.RIGHT_SHOULDER, :2] = [0.52, 0.40]
    upright_points[KeypointIndex.LEFT_HIP, :2] = [0.48, 0.58]
    upright_points[KeypointIndex.RIGHT_HIP, :2] = [0.52, 0.58]
    upright = PoseDetection.from_keypoints(upright_points)

    assert lane_direction(lane) == pytest.approx([1.0, 0.0])
    assert pose_lane_alignment(swimmer, lane) >= 0.95
    assert pose_lane_alignment(upright, lane) <= 0.05


def test_runtime_auto_uses_balanced_model_on_intel_gpu_class_device() -> None:
    runtime = select_pose_runtime("auto", available_devices=("CPU", "GPU", "NPU"))

    assert runtime.backend == "openvino"
    assert runtime.device == "gpu"
    assert runtime.mode == "balanced"

    quality = select_pose_runtime("quality", available_devices=("CPU", "GPU", "NPU"))
    assert (quality.backend, quality.device, quality.mode) == (
        "openvino",
        "gpu",
        "performance",
    )


def test_runtime_cpu_and_portable_fallbacks_are_deterministic() -> None:
    cpu = select_pose_runtime("auto", available_devices=("CPU",))
    portable = select_pose_runtime("portable", available_devices=())

    assert (cpu.backend, cpu.device, cpu.mode) == ("openvino", "cpu", "balanced")
    assert (portable.backend, portable.device, portable.mode) == (
        "onnxruntime",
        "cpu",
        "lightweight",
    )


def test_runtime_benchmark_recommends_highest_quality_that_meets_target() -> None:
    rows = [
        {
            "mode": "performance",
            "available": True,
            "estimated_all_lanes_fps": 8.0,
        },
        {
            "mode": "balanced",
            "available": True,
            "estimated_all_lanes_fps": 18.0,
        },
        {
            "mode": "lightweight",
            "available": True,
            "estimated_all_lanes_fps": 30.0,
        },
    ]

    assert choose_recommendation(rows, 15.0)["mode"] == "balanced"
    assert choose_recommendation(rows, 40.0)["mode"] == "lightweight"


def test_annotation_cannot_be_self_verified_and_bounds_events() -> None:
    draft = build_annotation(
        "fixture.mp4",
        "freestyle",
        1,
        2.0,
        8.0,
        [4.0, 3.0, 4.0],
        [3.5, 5.5],
        "annotator-a",
    )
    assert draft["verified"] is False
    assert draft["schema_version"] == "swimmate-event-label-v2"
    assert draft["prediction_visible"] is False
    assert draft["arm_event_times_sec"] == [3.0, 4.0]
    with pytest.raises(ValueError, match="cannot verify itself"):
        build_annotation(
            "fixture.mp4",
            "freestyle",
            1,
            2.0,
            8.0,
            [3.0, 4.0],
            [3.5, 5.5],
            "annotator-a",
            "reviewer-b",
        )
    with pytest.raises(ValueError, match="outside"):
        build_annotation(
            "fixture.mp4", "freestyle", 1, 2.0, 8.0, [8.1], [], "annotator-a"
        )


def test_two_blinded_annotations_build_verified_consensus_and_score_prediction() -> None:
    first = build_annotation(
        "fixture.mp4",
        "freestyle",
        1,
        2.0,
        8.0,
        [3.0, 4.0, 5.0],
        [3.5, 4.5],
        "annotator-a",
        video_sha256="a" * 64,
    )
    second = build_annotation(
        "fixture.mp4",
        "freestyle",
        1,
        2.0,
        8.0,
        [3.05, 4.05, 5.05],
        [3.55, 4.55],
        "annotator-b",
        video_sha256="a" * 64,
    )
    prediction = {
        "tracks": [
            {
                "lane_id": 1,
                "observed_frames": 80,
                "arm_strokes": {
                    "available": True,
                    "count": 2,
                    "event_times_sec": [3.02, 5.02],
                    "reason": None,
                },
                "kicks": {
                    "available": False,
                    "count": 0,
                    "event_times_sec": [],
                    "reason": "legs_not_visible",
                },
            }
        ]
    }

    report = build_review_report(first, second, prediction)
    comparison = report["comparison"]
    assert comparison["verified_independent_consensus"] is True
    assert comparison["consensus_ground_truth"]["arm_event_times_sec"] == [3.025, 4.025, 5.025]
    assert report["model_evaluation"]["arm"]["absolute_count_error"] == 1
    assert report["model_evaluation"]["arm"]["event_timing"]["f1"] == pytest.approx(0.8)
    assert report["model_evaluation"]["kick"]["withheld_reason"] == "legs_not_visible"


def test_annotation_disagreement_blocks_model_accuracy() -> None:
    first = build_annotation(
        "fixture.mp4",
        "freestyle",
        1,
        2.0,
        8.0,
        [3.0, 4.0],
        [3.5],
        "annotator-a",
        video_sha256="a" * 64,
    )
    second = build_annotation(
        "fixture.mp4",
        "freestyle",
        1,
        2.0,
        8.0,
        [3.0],
        [3.5],
        "annotator-b",
        video_sha256="a" * 64,
    )

    report = build_review_report(first, second, {"tracks": []})
    assert report["comparison"]["agreement_status"] == "adjudication_required"
    assert report["comparison"]["events"]["arm"]["first_only_event_times_sec"] == [4.0]
    assert report["model_evaluation"]["status"] == "blocked_by_annotation_disagreement"


def test_independent_annotation_comparison_rejects_same_annotator() -> None:
    first = build_annotation(
        "fixture.mp4",
        "freestyle",
        1,
        2.0,
        8.0,
        [3.0],
        [],
        "annotator-a",
        video_sha256="a" * 64,
    )
    second = build_annotation(
        "fixture.mp4",
        "freestyle",
        1,
        2.0,
        8.0,
        [3.1],
        [],
        "annotator-a",
        video_sha256="a" * 64,
    )

    with pytest.raises(ValueError, match="distinct annotators"):
        compare_annotations(first, second)


def test_unresolvable_kicks_are_not_interpreted_as_zero() -> None:
    first = build_annotation(
        "fixture.mp4",
        "freestyle",
        1,
        2.0,
        8.0,
        [3.0, 4.0],
        [],
        "annotator-a",
        video_sha256="a" * 64,
        kick_label_status="unresolvable",
    )
    second = build_annotation(
        "fixture.mp4",
        "freestyle",
        1,
        2.0,
        8.0,
        [3.05, 4.05],
        [],
        "annotator-b",
        video_sha256="a" * 64,
        kick_label_status="unresolvable",
    )

    report = build_review_report(first, second, {"tracks": []})
    truth = report["comparison"]["consensus_ground_truth"]
    assert report["comparison"]["verified_independent_consensus"] is True
    assert truth["kicks"] is None
    assert truth["kick_event_times_sec"] is None
    assert report["model_evaluation"]["kick"]["status"] == "unscored_unresolvable"


def test_event_metric_penalizes_duplicates_and_missed_events() -> None:
    score = match_events([1.0, 2.0, 3.0], [1.05, 1.08, 3.2], tolerance_sec=0.25)

    assert score["matched_events"] == 2
    assert score["precision"] == pytest.approx(2 / 3, abs=0.0001)
    assert score["recall"] == pytest.approx(2 / 3, abs=0.0001)
    assert score["f1"] == pytest.approx(2 / 3, abs=0.0001)


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


@pytest.mark.parametrize("fps", [20, 30, 60])
@pytest.mark.parametrize("frequency", [1.0, 2.0, 3.0])
def test_fast_kicks_preserve_each_visible_beat(fps: int, frequency: float) -> None:
    # Analytic ground truth: each positive and negative extremum is one beat.
    timestamps = np.arange(0.0, 12.0, 1.0 / fps)
    expected = np.arange(1 / (4 * frequency), timestamps[-1], 1 / (2 * frequency))
    cfg = CounterConfig()
    predicted = _find_peak_events(
        timestamps, np.sin(2 * np.pi * frequency * timestamps), cfg.kick_min_interval_sec,
        cfg, include_troughs=True, smoothing_window_sec=cfg.kick_smoothing_window_sec,
        max_gap_sec=cfg.kick_max_interpolation_gap_sec,
    )
    # A cut may not show enough of the final beat to confirm its prominence.
    assert abs(len(predicted) - len(expected)) <= 1
    assert match_events(expected, predicted, tolerance_sec=1 / fps)["f1"] >= 0.97


def test_missing_time_cannot_create_a_synthetic_stroke_peak() -> None:
    # No peak in either visible portion; the old concatenation made a peak
    # across the four-second hole. Exercise missing rows and explicit NaNs.
    t = np.arange(0, 10, 1 / 30)
    visible = (t < 3) | (t >= 7)
    values = np.where(t < 3, t, 10 - t)
    cfg = CounterConfig()
    assert _find_peak_events(t[visible], values[visible], .28, cfg) == []
    values[~visible] = np.nan
    assert _find_peak_events(t, values, .28, cfg) == []


def test_short_occlusion_preserves_known_stroke_timestamps() -> None:
    t = np.arange(0, 12, 1 / 30)
    signal = np.sin(np.pi * t)
    signal[(t > 4.42) & (t < 4.55)] = np.nan
    events = _find_peak_events(t, signal, .28, CounterConfig())
    score = match_events([.5, 2.5, 4.5, 6.5, 8.5, 10.5], events, tolerance_sec=.1)
    assert score["f1"] == 1


def test_one_visible_arm_cannot_be_reported_as_both_arms() -> None:
    analyzer = MultiSwimmerAnalyzer("freestyle")
    for frame in range(361):
        pose = _synthetic_swimmer(.5, .5, frame / 30)
        pose.keypoints[KeypointIndex.RIGHT_WRIST, 3] = .01
        analyzer.process_frame([pose], frame, frame / 30)
    result = analyzer.finalize().tracks[0]
    assert not result.arm_strokes.available
    assert result.arm_strokes.reason == "arms_not_visible"


def test_reported_camera_fps_cannot_hide_missing_pose_samples() -> None:
    analyzer = MultiSwimmerAnalyzer("freestyle")
    for frame in range(361):
        detections = [_synthetic_swimmer(.5, .5, frame / 30)] if frame % 3 != 0 else []
        analyzer.process_frame(detections, frame, frame / 30)
    result = analyzer.finalize().tracks[0]
    assert result.sample_rate_hz == pytest.approx(20, abs=.1)


@pytest.mark.parametrize("kind", ["freestyle", "backstroke", "breaststroke", "butterfly"])
def test_dps_uses_explicit_stroke_units_for_all_four_strokes(kind: str) -> None:
    synchronous = kind in {"breaststroke", "butterfly"}
    analyzer = MultiSwimmerAnalyzer(kind)
    for frame in range(361):
        analyzer.process_frame([_synthetic_swimmer(.5, .5, frame / 30, synchronous_arms=synchronous)], frame, frame / 30)
    # 12 arm events (6 pairs) or 6 synchronized cycles in this 12 s interval.
    metrics = analyzer.finalize([DistanceSegment("S001", 0, 12, 24)]).distance_metrics[0]
    assert metrics["available"] is True
    assert metrics["stroke_count"] == (6 if synchronous else 12)
    assert metrics["dps_m_per_stroke"] == (4 if synchronous else 2)
    assert metrics["distance_per_cycle_m"] == 4
    assert metrics["stroke_count_unit"] == ("synchronized_arm_cycle" if synchronous else "single_arm_action")
    assert metrics["accuracy_status"] == "unverified_model_prediction"


def test_dps_keeps_half_cycle_and_does_not_require_visible_kicks() -> None:
    analyzer = MultiSwimmerAnalyzer("freestyle")
    for frame in range(391):
        analyzer.process_frame([_synthetic_swimmer(.5, .5, frame / 30, leg_visibility=.01)], frame, frame / 30)
    result = analyzer.finalize([DistanceSegment("S001", 0, 13, 13, "surface_swimming")])
    assert not result.tracks[0].kicks.available
    metrics = result.distance_metrics[0]
    assert metrics["available"] is True
    assert metrics["cycle_equivalents"] == 6.5
    assert metrics["dps_m_per_stroke"] == 1
    assert metrics["distance_per_cycle_m"] == 2


def test_dps_separates_swimmers_and_recounts_only_the_measured_interval() -> None:
    analyzer = MultiSwimmerAnalyzer("freestyle")
    for frame in range(361):
        t = frame / 30
        analyzer.process_frame([_synthetic_swimmer(.5, .3, t), _synthetic_swimmer(.5, .7, t, stroke_hz=.75)], frame, t)
    result = analyzer.finalize([
        DistanceSegment("S001", 2, 10, 16),
        DistanceSegment("S002", 0, 12, 18),
        DistanceSegment("S099", 0, 12, 25),
    ])
    a, b, missing = result.distance_metrics
    assert a["stroke_count"] == 8 and a["dps_m_per_stroke"] == 2
    assert b["stroke_count"] == 18 and b["dps_m_per_stroke"] == 1
    assert not missing["available"] and missing["dps_m_per_stroke"] is None
    assert analyzer.finalize().distance_metrics == ()


def test_dps_refuses_unobserved_distance_and_hidden_arm_sections() -> None:
    analyzer = MultiSwimmerAnalyzer("freestyle")
    for frame in range(361):
        t = frame / 30
        pose = _synthetic_swimmer(.5, .5, t)
        if 4 < t < 4.8:
            pose.keypoints[[KeypointIndex.LEFT_WRIST, KeypointIndex.RIGHT_WRIST], 3] = .01
        analyzer.process_frame([pose], frame, t)
    result = analyzer.finalize([DistanceSegment("S001", 0, 12, 24), DistanceSegment("S001", 0, 16, 25)])
    assert not result.tracks[0].arm_strokes.available
    assert result.tracks[0].arm_strokes.reason == "arm_signal_gaps"
    assert result.tracks[0].diagnostics["arm_candidate_count"] > 0
    assert result.distance_metrics[0]["reason"] == "stroke_count_unavailable:arm_signal_gaps"
    assert not result.distance_metrics[1]["available"]
    assert all(item["dps_m_per_stroke"] is None for item in result.distance_metrics)


def test_incomplete_arm_count_cannot_invalidate_visible_kicks() -> None:
    analyzer = MultiSwimmerAnalyzer("freestyle")
    for frame in range(361):
        t = frame / 30
        pose = _synthetic_swimmer(.5, .5, t, kick_hz=3)
        if 4 < t < 8:
            pose.keypoints[[KeypointIndex.LEFT_WRIST, KeypointIndex.RIGHT_WRIST], 3] = .01
        analyzer.process_frame([pose], frame, t)
    track = analyzer.finalize().tracks[0]
    assert track.arm_strokes.reason == "arm_signal_gaps"
    assert track.kicks.available
    assert abs(track.kicks.count - 72) <= 1
    assert track.kicks_per_cycle is None


def test_dps_refuses_a_distance_covering_unfilmed_time() -> None:
    analyzer = MultiSwimmerAnalyzer("freestyle")
    for frame in range(180, 361):
        analyzer.process_frame([_synthetic_swimmer(.5, .5, frame / 30)], frame, frame / 30)
    result = analyzer.finalize([DistanceSegment("S001", 0, 12, 24)])
    assert result.tracks[0].arm_strokes.available
    assert result.distance_metrics[0]["reason"] == "distance_interval_not_fully_observed"


@pytest.mark.parametrize("distance", [0, -1, float("nan"), float("inf")])
def test_dps_rejects_invalid_distances(distance: float) -> None:
    with pytest.raises(ValueError):
        DistanceSegment("S001", 0, 12, distance)


def test_distance_cli_requires_swimmer_and_matching_time_bounds() -> None:
    args = counter_parser().parse_args(["video.mp4", "--stroke", "freestyle", "--output", "out.json", "--distance-m", "25"])
    assert args.frame_step == 1
    with pytest.raises(ValueError, match="--start-sec"):
        parse_distance_segments(args)


def test_pose_replay_runs_counter_and_dps_without_inference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "fixture.mp4"
    video.write_bytes(b"private source fixture; replay does not decode video")
    source_hash = video_sha256(video)
    frames = [serialize_frame(frame, frame / 30, [_synthetic_swimmer(.5, .5, frame / 30)]) for frame in range(361)]
    cache = tmp_path / "poses.json.gz"
    output = tmp_path / "result.json"
    write_pose_cache(cache, source_hash, 30, frames, {"provider": "analytic_fixture"})
    with pytest.raises(ValueError, match="different source"):
        read_pose_cache(cache, "f" * 64)
    monkeypatch.setattr("sys.argv", [
        "counter", str(video), "--stroke", "freestyle", "--output", str(output),
        "--pose-cache-in", str(cache), "--start-sec", "0", "--end-sec", "12",
        "--distance-m", "24", "--distance-track-id", "S001",
    ])
    assert counter_cli() == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["source_video_sha256"] == source_hash
    assert result["run"]["provider"] == "pose-cache-replay"
    assert result["distance_metrics"][0]["dps_m_per_stroke"] == 2
    assert result["tracks"][0]["arm_strokes"]["count"] == 12

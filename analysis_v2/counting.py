"""Per-track temporal stroke and kick event counting."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np

from .types import KeypointIndex, StrokeKind, TrackObservation


@dataclass(frozen=True)
class CounterConfig:
    min_track_frames: int = 24
    min_track_duration_sec: float = 2.5
    min_track_coverage: float = 0.60
    min_landmark_confidence: float = 0.25
    min_arm_visibility: float = 0.50
    min_leg_visibility: float = 0.58
    smoothing_window: int = 5
    smoothing_window_sec: float = 0.30
    kick_smoothing_window_sec: float = 0.09
    max_interpolation_gap: int = 5
    max_interpolation_gap_sec: float = 0.35
    kick_max_interpolation_gap_sec: float = 0.10
    stroke_min_interval_sec: float = 0.28
    alternating_merge_sec: float = 0.12
    alternating_min_event_interval_sec: float = 0.22
    kick_min_interval_sec: float = 0.16
    synchronous_merge_sec: float = 0.24
    synchronous_min_cycle_interval_sec: float = 0.40
    minimum_sync_pattern_events: int = 3
    minimum_sync_pattern_ratio: float = 0.50
    maximum_alternating_synchrony_ratio: float = 0.70
    synchronous_pattern_tolerance_sec: float = 0.18
    minimum_flutter_kick_sample_hz: float = 18.0
    minimum_synchronous_kick_sample_hz: float = 10.0
    minimum_alternating_kicks_per_cycle: float = 1.50
    maximum_alternating_kicks_per_cycle: float = 8.00
    minimum_breaststroke_kicks_per_cycle: float = 0.65
    maximum_breaststroke_kicks_per_cycle: float = 1.50
    minimum_butterfly_kicks_per_cycle: float = 1.00
    maximum_butterfly_kicks_per_cycle: float = 3.00
    minimum_peak_prominence_ratio: float = 0.18
    minimum_absolute_prominence: float = 0.035
    prominence_window_sec: float = 1.0


@dataclass(frozen=True)
class EventCount:
    available: bool
    count: int
    event_times_sec: tuple[float, ...]
    rate_per_min: float | None
    confidence: float
    visibility: float
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["event_times_sec"] = list(self.event_times_sec)
        return data


@dataclass(frozen=True)
class TrackCountResult:
    track_id: str
    lane_id: int
    started_at_sec: float
    ended_at_sec: float
    duration_sec: float
    observed_frames: int
    track_coverage: float
    stroke_kind: str
    sample_rate_hz: float | None
    arm_pattern: str
    arm_pattern_synchrony: float | None
    arm_strokes: EventCount
    complete_cycles: int
    left_arm_events: tuple[float, ...]
    right_arm_events: tuple[float, ...]
    kicks: EventCount
    kicks_per_cycle: float | None
    warnings: tuple[str, ...]
    diagnostics: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "track_id": self.track_id,
            "lane_id": self.lane_id,
            "started_at_sec": self.started_at_sec,
            "ended_at_sec": self.ended_at_sec,
            "duration_sec": self.duration_sec,
            "observed_frames": self.observed_frames,
            "track_coverage": self.track_coverage,
            "stroke_kind": self.stroke_kind,
            "sample_rate_hz": self.sample_rate_hz,
            "arm_pattern": self.arm_pattern,
            "arm_pattern_synchrony": self.arm_pattern_synchrony,
            "arm_strokes": self.arm_strokes.to_dict(),
            "complete_cycles": self.complete_cycles,
            "left_arm_events": list(self.left_arm_events),
            "right_arm_events": list(self.right_arm_events),
            "kicks": self.kicks.to_dict(),
            "kicks_per_cycle": self.kicks_per_cycle,
            "warnings": list(self.warnings),
            "diagnostics": self.diagnostics,
            "stroke_count_unit": (
                "single_arm_action" if self.stroke_kind in {"freestyle", "backstroke", "unknown"}
                else "synchronized_arm_cycle"
            ),
            "cycle_equivalents": (
                self.arm_strokes.count / 2.0
                if self.stroke_kind in {"freestyle", "backstroke"} and self.arm_strokes.available
                else self.arm_strokes.count if self.arm_strokes.available and self.stroke_kind != "unknown"
                else None
            ),
        }


def _visible_point(points: np.ndarray, index: int, threshold: float) -> np.ndarray | None:
    point = points[int(index)]
    return point[:2] if point[3] >= threshold else None


def _body_frame(
    points: np.ndarray, threshold: float
) -> tuple[np.ndarray, np.ndarray, float, np.ndarray] | None:
    left_shoulder = _visible_point(points, KeypointIndex.LEFT_SHOULDER, threshold)
    right_shoulder = _visible_point(points, KeypointIndex.RIGHT_SHOULDER, threshold)
    left_hip = _visible_point(points, KeypointIndex.LEFT_HIP, threshold)
    right_hip = _visible_point(points, KeypointIndex.RIGHT_HIP, threshold)
    if any(point is None for point in (left_shoulder, right_shoulder, left_hip, right_hip)):
        return None
    shoulder_mid = (left_shoulder + right_shoulder) / 2.0
    hip_mid = (left_hip + right_hip) / 2.0
    longitudinal = shoulder_mid - hip_mid
    torso_length = float(np.linalg.norm(longitudinal))
    shoulder_width = float(np.linalg.norm(left_shoulder - right_shoulder))
    scale = max(torso_length, shoulder_width, 0.025)
    if torso_length < 0.012:
        return None
    longitudinal /= torso_length
    transverse = np.array([-longitudinal[1], longitudinal[0]], dtype=np.float64)
    return hip_mid, longitudinal, scale, transverse


def _projected_signal(
    observations: list[TrackObservation],
    keypoint_index: int,
    axis: str,
    config: CounterConfig,
) -> tuple[np.ndarray, np.ndarray]:
    values = np.full(len(observations), np.nan, dtype=np.float64)
    confidences = np.zeros(len(observations), dtype=np.float64)
    for row_index, observation in enumerate(observations):
        points = observation.detection.keypoints
        frame = _body_frame(points, config.min_landmark_confidence)
        point = _visible_point(points, keypoint_index, config.min_landmark_confidence)
        if frame is None or point is None:
            continue
        hip_mid, longitudinal, scale, transverse = frame
        direction = longitudinal if axis == "longitudinal" else transverse
        values[row_index] = float(np.dot(point - hip_mid, direction) / scale)
        confidences[row_index] = float(points[int(keypoint_index), 3])
    return values, confidences


def _ankle_difference_signal(
    observations: list[TrackObservation], config: CounterConfig
) -> tuple[np.ndarray, np.ndarray]:
    values = np.full(len(observations), np.nan, dtype=np.float64)
    confidences = np.zeros(len(observations), dtype=np.float64)
    for row_index, observation in enumerate(observations):
        points = observation.detection.keypoints
        frame = _body_frame(points, config.min_landmark_confidence)
        left_knee = _visible_point(points, KeypointIndex.LEFT_KNEE, config.min_landmark_confidence)
        right_knee = _visible_point(points, KeypointIndex.RIGHT_KNEE, config.min_landmark_confidence)
        left = _visible_point(points, KeypointIndex.LEFT_ANKLE, config.min_landmark_confidence)
        right = _visible_point(points, KeypointIndex.RIGHT_ANKLE, config.min_landmark_confidence)
        if frame is None or left_knee is None or right_knee is None or left is None or right is None:
            continue
        _, _, scale, transverse = frame
        values[row_index] = float(np.dot(left - right, transverse) / scale)
        confidences[row_index] = float(
            min(
                points[int(KeypointIndex.LEFT_KNEE), 3],
                points[int(KeypointIndex.RIGHT_KNEE), 3],
                points[int(KeypointIndex.LEFT_ANKLE), 3],
                points[int(KeypointIndex.RIGHT_ANKLE), 3],
            )
        )
    return values, confidences


def _synchronous_kick_signal(
    observations: list[TrackObservation], stroke_kind: StrokeKind, config: CounterConfig
) -> tuple[np.ndarray, np.ndarray]:
    values = np.full(len(observations), np.nan, dtype=np.float64)
    confidences = np.zeros(len(observations), dtype=np.float64)
    for row_index, observation in enumerate(observations):
        points = observation.detection.keypoints
        frame = _body_frame(points, config.min_landmark_confidence)
        left_knee = _visible_point(points, KeypointIndex.LEFT_KNEE, config.min_landmark_confidence)
        right_knee = _visible_point(points, KeypointIndex.RIGHT_KNEE, config.min_landmark_confidence)
        left = _visible_point(points, KeypointIndex.LEFT_ANKLE, config.min_landmark_confidence)
        right = _visible_point(points, KeypointIndex.RIGHT_ANKLE, config.min_landmark_confidence)
        if frame is None or left_knee is None or right_knee is None or left is None or right is None:
            continue
        hip_mid, longitudinal, scale, transverse = frame
        if stroke_kind == StrokeKind.BREASTSTROKE:
            values[row_index] = float(np.linalg.norm(left - right) / scale)
        else:
            mean_ankle = (left + right) / 2.0
            values[row_index] = float(np.dot(mean_ankle - hip_mid, transverse) / scale)
        confidences[row_index] = float(
            min(
                points[int(KeypointIndex.LEFT_KNEE), 3],
                points[int(KeypointIndex.RIGHT_KNEE), 3],
                points[int(KeypointIndex.LEFT_ANKLE), 3],
                points[int(KeypointIndex.RIGHT_ANKLE), 3],
            )
        )
    return values, confidences


def _interpolate_short_gaps(values: np.ndarray, max_gap: int) -> np.ndarray:
    result = values.copy()
    valid = np.isfinite(result)
    if valid.sum() < 2:
        return result
    missing_indexes = np.flatnonzero(~valid)
    for index in missing_indexes:
        left = index - 1
        while left >= 0 and not valid[left]:
            left -= 1
        right = index + 1
        while right < len(result) and not valid[right]:
            right += 1
        if left >= 0 and right < len(result) and right - left - 1 <= max_gap:
            fraction = (index - left) / (right - left)
            result[index] = result[left] + fraction * (result[right] - result[left])
    return result


def _smooth(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return values.copy()
    result = np.full_like(values, np.nan)
    radius = window // 2
    for index in range(len(values)):
        part = values[max(0, index - radius) : min(len(values), index + radius + 1)]
        finite = part[np.isfinite(part)]
        if finite.size:
            result[index] = float(np.mean(finite))
    return result


def _regularity_confidence(event_times: list[float]) -> float:
    if len(event_times) < 3:
        return 0.45 if event_times else 0.0
    intervals = np.diff(np.asarray(event_times, dtype=np.float64))
    mean_interval = float(np.mean(intervals))
    if mean_interval <= 0:
        return 0.0
    coefficient = float(np.std(intervals) / mean_interval)
    return float(np.clip(1.0 - coefficient, 0.0, 1.0))


def _find_peak_events(
    timestamps: np.ndarray,
    raw_values: np.ndarray,
    min_interval_sec: float,
    config: CounterConfig,
    include_troughs: bool = False,
    *,
    smoothing_window_sec: float | None = None,
    max_gap_sec: float | None = None,
) -> list[float]:
    """Count observed extrema on continuous, uniformly timed signal segments.

    Missing detections have missing *timestamps*, not just NaNs. Never smooth
    across those holes or use an array-index gap as a proxy for elapsed time.
    A kick has a shorter period than an arm cycle and needs its own filter.
    """
    if len(timestamps) < 3:
        return []
    delta = np.diff(timestamps)
    if not np.isfinite(timestamps).all() or np.any(delta <= 0):
        raise ValueError("signal timestamps must be finite and strictly increasing")
    step = float(np.median(delta))
    window_sec = config.smoothing_window_sec if smoothing_window_sec is None else smoothing_window_sec
    gap_sec = config.max_interpolation_gap_sec if max_gap_sec is None else max_gap_sec
    smoothing_window = max(1, int(round(window_sec / step)))
    if smoothing_window % 2 == 0:
        smoothing_window += 1
    valid_indexes = np.flatnonzero(np.isfinite(raw_values))
    if len(valid_indexes) < max(config.min_track_frames // 2, 8):
        return []
    split_indexes = np.flatnonzero(
        np.diff(timestamps[valid_indexes]) > max(gap_sec, step * 1.5)
    ) + 1
    events: list[float] = []
    for indexes in np.split(valid_indexes, split_indexes):
        if len(indexes) < 3:
            continue
        start, end = timestamps[indexes[0]], timestamps[indexes[-1]]
        grid = np.linspace(start, end, max(3, int(round((end - start) / step)) + 1))
        values = _smooth(np.interp(grid, timestamps[indexes], raw_values[indexes]), smoothing_window)
        events.extend(_segment_peak_events(grid, values, min_interval_sec, config,
                                           smoothing_window, include_troughs))
    return sorted(events)


def _segment_peak_events(
    timestamps: np.ndarray,
    values: np.ndarray,
    min_interval_sec: float,
    config: CounterConfig,
    smoothing_window: int,
    include_troughs: bool,
) -> list[float]:
    finite = values[np.isfinite(values)]
    if finite.size < 3:
        return []
    amplitude = float(np.percentile(finite, 95) - np.percentile(finite, 5))
    if amplitude < config.minimum_absolute_prominence:
        return []
    prominence_threshold = max(
        config.minimum_absolute_prominence,
        amplitude * config.minimum_peak_prominence_ratio,
    )

    candidates: list[tuple[float, float]] = []
    signals = (values, -values) if include_troughs else (values,)
    step = float(np.median(np.diff(timestamps)))
    prominence_radius = max(int(round(config.prominence_window_sec / step)), smoothing_window * 2, 3)
    for signal in signals:
        finite_signal = signal[np.isfinite(signal)]
        center_threshold = float(np.median(finite_signal))
        for index in range(1, len(signal) - 1):
            if not np.isfinite(signal[index - 1 : index + 2]).all():
                continue
            if not (signal[index] > signal[index - 1] and signal[index] >= signal[index + 1]):
                continue
            if signal[index] < center_threshold:
                continue
            left = signal[max(0, index - prominence_radius) : index]
            right = signal[index + 1 : min(len(signal), index + prominence_radius + 1)]
            left = left[np.isfinite(left)]
            right = right[np.isfinite(right)]
            if not left.size or not right.size:
                continue
            # A higher neighbour bounds prominence; a ripple on a large peak
            # must not borrow that peak's distant valley and become a stroke.
            higher_left = np.flatnonzero(left > signal[index])
            higher_right = np.flatnonzero(right > signal[index])
            if higher_left.size:
                left = left[higher_left[-1]:]
            if higher_right.size:
                right = right[:higher_right[0] + 1]
            prominence = float(signal[index] - max(np.min(left), np.min(right)))
            if prominence >= prominence_threshold:
                a, b, c = signal[index - 1:index + 2]
                curvature = a - 2.0 * b + c
                offset = float(np.clip(0.5 * (a - c) / curvature, -0.5, 0.5)) if curvature < -1e-12 else 0.0
                candidates.append((float(timestamps[index] + offset * step), prominence))

    candidates.sort(key=lambda item: item[1], reverse=True)
    accepted: list[float] = []
    for timestamp, _ in candidates:
        if all(abs(timestamp - other) >= min_interval_sec for other in accepted):
            accepted.append(timestamp)
    accepted.sort()
    return [round(timestamp, 3) for timestamp in accepted]


def _merge_nearby_events(event_groups: Iterable[Iterable[float]], tolerance_sec: float) -> list[float]:
    flattened = sorted(float(value) for group in event_groups for value in group)
    if not flattened:
        return []
    clusters: list[list[float]] = [[flattened[0]]]
    for value in flattened[1:]:
        if value - clusters[-1][-1] <= tolerance_sec:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return [round(float(np.mean(cluster)), 3) for cluster in clusters]


def _reconcile_events(events: Iterable[float], minimum_interval_sec: float) -> list[float]:
    """Collapse physiologically impossible near-duplicate temporal events."""

    ordered = sorted(float(value) for value in events)
    if not ordered:
        return []
    clusters: list[list[float]] = [[ordered[0]]]
    for value in ordered[1:]:
        if value - clusters[-1][-1] < minimum_interval_sec:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return [round(float(np.mean(cluster)), 3) for cluster in clusters]


def _arm_synchrony_ratio(
    left_events: list[float],
    right_events: list[float],
    tolerance_sec: float,
) -> float | None:
    """Return a one-to-one temporal match ratio for the two arms."""

    if not left_events or not right_events:
        return None
    available = set(range(len(right_events)))
    matched = 0
    for left in left_events:
        candidates = [index for index in available if abs(right_events[index] - left) <= tolerance_sec]
        if not candidates:
            continue
        best = min(candidates, key=lambda index: abs(right_events[index] - left))
        available.remove(best)
        matched += 1
    return float(matched / max(min(len(left_events), len(right_events)), 1))


def _sampling_rate_hz(timestamps: np.ndarray, provided: float | None) -> float | None:
    if provided is not None and np.isfinite(provided) and provided > 0:
        return float(provided)
    if len(timestamps) < 2:
        return None
    duration = float(timestamps[-1] - timestamps[0])
    if duration <= 0:
        return None
    return float((len(timestamps) - 1) / duration)


def _unavailable(visibility: float, reason: str) -> EventCount:
    return EventCount(False, 0, (), None, 0.0, round(visibility, 3), reason)


def _longest_signal_gap(timestamps: np.ndarray, values: np.ndarray) -> float:
    valid_times = timestamps[np.isfinite(values)]
    if not len(valid_times):
        return float(timestamps[-1] - timestamps[0])
    return float(np.max(np.diff(np.r_[timestamps[0], valid_times, timestamps[-1]])))


def count_track(
    observations: Iterable[TrackObservation],
    stroke_kind: StrokeKind | str,
    config: CounterConfig | None = None,
    total_processed_frames: int | None = None,
    processed_sample_rate_hz: float | None = None,
) -> TrackCountResult:
    cfg = config or CounterConfig()
    kind = stroke_kind if isinstance(stroke_kind, StrokeKind) else StrokeKind(stroke_kind)
    rows = sorted(observations, key=lambda item: item.timestamp_sec)
    if not rows:
        raise ValueError("at least one track observation is required")
    timestamps = np.asarray([row.timestamp_sec for row in rows], dtype=np.float64)
    if not np.isfinite(timestamps).all() or np.any(np.diff(timestamps) <= 0):
        raise ValueError("track timestamps must be finite and strictly increasing")
    if len({(row.track_id, row.lane_id) for row in rows}) != 1:
        raise ValueError("count_track requires observations of a single swimmer")
    duration = max(float(timestamps[-1] - timestamps[0]), 0.0)
    observed_sample_rate = _sampling_rate_hz(timestamps, None)
    sample_rate_hz = _sampling_rate_hz(timestamps, processed_sample_rate_hz)
    if observed_sample_rate is not None and sample_rate_hz is not None:
        sample_rate_hz = min(sample_rate_hz, observed_sample_rate)
    denominator = total_processed_frames if total_processed_frames is not None else len(rows)
    track_coverage = float(np.clip(len(rows) / max(denominator, 1), 0.0, 1.0))
    warnings: list[str] = []

    left_wrist, left_confidence = _projected_signal(rows, KeypointIndex.LEFT_WRIST, "longitudinal", cfg)
    right_wrist, right_confidence = _projected_signal(rows, KeypointIndex.RIGHT_WRIST, "longitudinal", cfg)
    left_visibility = float(np.mean(left_confidence >= cfg.min_landmark_confidence))
    right_visibility = float(np.mean(right_confidence >= cfg.min_landmark_confidence))
    arm_visibility = (left_visibility + right_visibility) / 2.0
    arm_pattern = "insufficient_evidence"
    arm_pattern_synchrony: float | None = None
    arm_events: list[float] = []

    if track_coverage < cfg.min_track_coverage:
        arm_result = _unavailable(arm_visibility, "track_coverage_too_low")
        left_events = []
        right_events = []
        complete_cycles = 0
        warnings.append("counts_withheld_fragmented_track")
    elif len(rows) < cfg.min_track_frames or duration < cfg.min_track_duration_sec:
        arm_result = _unavailable(arm_visibility, "track_too_short")
        left_events: list[float] = []
        right_events: list[float] = []
        complete_cycles = 0
    elif min(left_visibility, right_visibility) < cfg.min_arm_visibility:
        arm_result = _unavailable(arm_visibility, "arms_not_visible")
        left_events = []
        right_events = []
        complete_cycles = 0
    else:
        left_events = _find_peak_events(timestamps, left_wrist, cfg.stroke_min_interval_sec, cfg)
        right_events = _find_peak_events(timestamps, right_wrist, cfg.stroke_min_interval_sec, cfg)
        arm_pattern_synchrony = _arm_synchrony_ratio(
            left_events,
            right_events,
            cfg.synchronous_pattern_tolerance_sec,
        )
        enough_pattern_events = (
            len(left_events) >= cfg.minimum_sync_pattern_events
            and len(right_events) >= cfg.minimum_sync_pattern_events
        )
        if enough_pattern_events and arm_pattern_synchrony is not None:
            if arm_pattern_synchrony >= cfg.maximum_alternating_synchrony_ratio:
                arm_pattern = "synchronous"
            elif arm_pattern_synchrony < cfg.minimum_sync_pattern_ratio:
                arm_pattern = "alternating"
            else:
                arm_pattern = "mixed"
        if kind in {StrokeKind.BREASTSTROKE, StrokeKind.BUTTERFLY}:
            arm_events = _merge_nearby_events((left_events, right_events), cfg.synchronous_merge_sec)
            arm_events = _reconcile_events(arm_events, cfg.synchronous_min_cycle_interval_sec)
            complete_cycles = len(arm_events)
        else:
            # Freestyle/backstroke arms should alternate. Generic pose models
            # can swap left/right identity around roll or water occlusion,
            # producing two events at effectively the same instant. Treat
            # those as one physical arm event instead of double-counting it.
            arm_events = _merge_nearby_events(
                (left_events, right_events),
                cfg.alternating_merge_sec,
            )
            unreconciled_count = len(arm_events)
            arm_events = _reconcile_events(arm_events, cfg.alternating_min_event_interval_sec)
            if len(arm_events) < unreconciled_count:
                warnings.append("near_duplicate_arm_events_reconciled")
            complete_cycles = len(arm_events) // 2
        pattern_conflict = (
            kind in {StrokeKind.BREASTSTROKE, StrokeKind.BUTTERFLY}
            and enough_pattern_events
            and arm_pattern_synchrony is not None
            and arm_pattern_synchrony < cfg.minimum_sync_pattern_ratio
        )
        ambiguous_alternating_identity = (
            kind in {StrokeKind.FREESTYLE, StrokeKind.BACKSTROKE}
            and enough_pattern_events
            and arm_pattern_synchrony is not None
            and arm_pattern_synchrony >= cfg.maximum_alternating_synchrony_ratio
        )
        if pattern_conflict:
            arm_result = _unavailable(arm_visibility, "stroke_pattern_conflict")
            complete_cycles = 0
            warnings.append("selected_stroke_conflicts_with_observed_arm_pattern")
        elif ambiguous_alternating_identity:
            arm_result = _unavailable(arm_visibility, "arm_identity_ambiguous")
            complete_cycles = 0
            warnings.append("alternating_arm_count_withheld_synchronous_pose_artifact")
        elif not arm_events:
            arm_result = _unavailable(arm_visibility, "no_reliable_stroke_events")
        else:
            regularity = _regularity_confidence(arm_events)
            confidence = float(np.clip(0.68 * arm_visibility + 0.32 * regularity, 0.0, 1.0))
            rate = len(arm_events) / duration * 60.0 if duration > 0 else None
            arm_result = EventCount(
                True,
                len(arm_events),
                tuple(arm_events),
                round(rate, 2) if rate is not None else None,
                round(confidence, 3),
                round(arm_visibility, 3),
            )

    if kind in {StrokeKind.FREESTYLE, StrokeKind.BACKSTROKE, StrokeKind.UNKNOWN}:
        kick_values, kick_confidence_values = _ankle_difference_signal(rows, cfg)
        include_troughs = True
    else:
        kick_values, kick_confidence_values = _synchronous_kick_signal(rows, kind, cfg)
        include_troughs = False
    leg_visibility = float(np.mean(kick_confidence_values >= cfg.min_landmark_confidence))
    required_kick_sample_hz = (
        cfg.minimum_flutter_kick_sample_hz
        if kind in {StrokeKind.FREESTYLE, StrokeKind.BACKSTROKE, StrokeKind.UNKNOWN}
        else cfg.minimum_synchronous_kick_sample_hz
    )
    kick_events: list[float] = []

    if track_coverage < cfg.min_track_coverage:
        kick_result = _unavailable(leg_visibility, "track_coverage_too_low")
    elif len(rows) < cfg.min_track_frames or duration < cfg.min_track_duration_sec:
        kick_result = _unavailable(leg_visibility, "track_too_short")
    elif leg_visibility < cfg.min_leg_visibility:
        kick_result = _unavailable(leg_visibility, "legs_not_visible")
        warnings.append("kick_count_withheld_low_leg_visibility")
    elif sample_rate_hz is not None and sample_rate_hz < required_kick_sample_hz:
        kick_result = _unavailable(leg_visibility, "sample_rate_too_low_for_kicks")
        warnings.append("kick_count_withheld_low_sample_rate")
    else:
        kick_events = _find_peak_events(
            timestamps,
            kick_values,
            cfg.kick_min_interval_sec,
            cfg,
            include_troughs=include_troughs,
            smoothing_window_sec=cfg.kick_smoothing_window_sec,
            max_gap_sec=cfg.kick_max_interpolation_gap_sec,
        )
        if not kick_events:
            kick_result = _unavailable(leg_visibility, "no_reliable_kick_events")
        else:
            regularity = _regularity_confidence(kick_events)
            confidence = float(np.clip(0.68 * leg_visibility + 0.32 * regularity, 0.0, 1.0))
            rate = len(kick_events) / duration * 60.0 if duration > 0 else None
            kick_result = EventCount(
                True,
                len(kick_events),
                tuple(kick_events),
                round(rate, 2) if rate is not None else None,
                round(confidence, 3),
                round(leg_visibility, 3),
            )

    arm_gap = max(_longest_signal_gap(timestamps, left_wrist), _longest_signal_gap(timestamps, right_wrist))
    kick_gap = _longest_signal_gap(timestamps, kick_values)
    frame_interval = float(np.median(np.diff(timestamps))) if len(rows) > 1 else 0.0
    # Check completeness before comparing rates: a partial arm count must not
    # invalidate an independently observable kick count through a bad ratio.
    if arm_result.available and arm_gap > max(cfg.max_interpolation_gap_sec, frame_interval * 1.5) + 1e-6:
        arm_result = _unavailable(arm_visibility, "arm_signal_gaps")
        complete_cycles = 0
        warnings.append("arm_candidates_cover_only_visible_segments")
    if kick_result.available and kick_gap > max(cfg.kick_max_interpolation_gap_sec, frame_interval * 1.5) + 1e-6:
        kick_result = _unavailable(leg_visibility, "kick_signal_gaps")
        warnings.append("kick_candidates_cover_only_visible_segments")

    kicks_per_cycle = None
    if kick_result.available and complete_cycles > 0:
        cycle_equivalents = (
            arm_result.count / 2.0
            if kind in {StrokeKind.FREESTYLE, StrokeKind.BACKSTROKE, StrokeKind.UNKNOWN}
            else float(arm_result.count)
        )
        kicks_per_cycle = round(kick_result.count / cycle_equivalents, 2)
        if kind in {StrokeKind.FREESTYLE, StrokeKind.BACKSTROKE, StrokeKind.UNKNOWN}:
            minimum_ratio = cfg.minimum_alternating_kicks_per_cycle
            maximum_ratio = cfg.maximum_alternating_kicks_per_cycle
        elif kind == StrokeKind.BREASTSTROKE:
            minimum_ratio = cfg.minimum_breaststroke_kicks_per_cycle
            maximum_ratio = cfg.maximum_breaststroke_kicks_per_cycle
        else:
            minimum_ratio = cfg.minimum_butterfly_kicks_per_cycle
            maximum_ratio = cfg.maximum_butterfly_kicks_per_cycle
        if kicks_per_cycle < minimum_ratio or kicks_per_cycle > maximum_ratio:
            kick_result = _unavailable(leg_visibility, "kick_stroke_ratio_implausible")
            warnings.append("kick_count_withheld_implausible_stroke_ratio")
            kicks_per_cycle = None
    if kind == StrokeKind.UNKNOWN:
        warnings.append("stroke_kind_unknown_counts_are_not_cycle_normalized")

    first = rows[0]
    return TrackCountResult(
        track_id=first.track_id,
        lane_id=first.lane_id,
        started_at_sec=round(float(timestamps[0]), 3),
        ended_at_sec=round(float(timestamps[-1]), 3),
        duration_sec=round(duration, 3),
        observed_frames=len(rows),
        track_coverage=round(track_coverage, 3),
        stroke_kind=kind.value,
        sample_rate_hz=round(sample_rate_hz, 3) if sample_rate_hz is not None else None,
        arm_pattern=arm_pattern,
        arm_pattern_synchrony=(
            round(arm_pattern_synchrony, 3) if arm_pattern_synchrony is not None else None
        ),
        arm_strokes=arm_result,
        complete_cycles=complete_cycles,
        left_arm_events=tuple(left_events),
        right_arm_events=tuple(right_events),
        kicks=kick_result,
        kicks_per_cycle=kicks_per_cycle,
        warnings=tuple(warnings),
        diagnostics={
            "left_arm_visibility": round(left_visibility, 3),
            "right_arm_visibility": round(right_visibility, 3),
            "longest_observation_gap_sec": round(float(np.max(np.diff(timestamps))), 3) if len(rows) > 1 else None,
            "longest_arm_signal_gap_sec": round(arm_gap, 3),
            "longest_kick_signal_gap_sec": round(kick_gap, 3),
            "arm_candidate_count": len(arm_events),
            "kick_candidate_count": len(kick_events),
            "merged_arm_candidate_times_sec": arm_events,
            "arm_candidate_times_sec": list(sorted(set(left_events + right_events))),
            "kick_candidate_times_sec": kick_events,
            "arm_smoothing_window_sec": cfg.smoothing_window_sec,
            "kick_smoothing_window_sec": cfg.kick_smoothing_window_sec,
            "accuracy_status": "unverified_model_prediction",
        },
    )

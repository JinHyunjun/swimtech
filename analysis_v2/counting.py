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
    max_interpolation_gap: int = 5
    stroke_min_interval_sec: float = 0.28
    kick_min_interval_sec: float = 0.11
    synchronous_merge_sec: float = 0.24
    minimum_peak_prominence_ratio: float = 0.18
    minimum_absolute_prominence: float = 0.035


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
    arm_strokes: EventCount
    complete_cycles: int
    left_arm_events: tuple[float, ...]
    right_arm_events: tuple[float, ...]
    kicks: EventCount
    kicks_per_cycle: float | None
    warnings: tuple[str, ...]

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
            "arm_strokes": self.arm_strokes.to_dict(),
            "complete_cycles": self.complete_cycles,
            "left_arm_events": list(self.left_arm_events),
            "right_arm_events": list(self.right_arm_events),
            "kicks": self.kicks.to_dict(),
            "kicks_per_cycle": self.kicks_per_cycle,
            "warnings": list(self.warnings),
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
        left = _visible_point(points, KeypointIndex.LEFT_ANKLE, config.min_landmark_confidence)
        right = _visible_point(points, KeypointIndex.RIGHT_ANKLE, config.min_landmark_confidence)
        if frame is None or left is None or right is None:
            continue
        _, _, scale, transverse = frame
        values[row_index] = float(np.dot(left - right, transverse) / scale)
        confidences[row_index] = float(
            min(points[int(KeypointIndex.LEFT_ANKLE), 3], points[int(KeypointIndex.RIGHT_ANKLE), 3])
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
        left = _visible_point(points, KeypointIndex.LEFT_ANKLE, config.min_landmark_confidence)
        right = _visible_point(points, KeypointIndex.RIGHT_ANKLE, config.min_landmark_confidence)
        if frame is None or left is None or right is None:
            continue
        hip_mid, longitudinal, scale, transverse = frame
        if stroke_kind == StrokeKind.BREASTSTROKE:
            values[row_index] = float(np.linalg.norm(left - right) / scale)
        else:
            mean_ankle = (left + right) / 2.0
            values[row_index] = float(np.dot(mean_ankle - hip_mid, transverse) / scale)
        confidences[row_index] = float(
            min(points[int(KeypointIndex.LEFT_ANKLE), 3], points[int(KeypointIndex.RIGHT_ANKLE), 3])
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
) -> list[float]:
    values = _smooth(_interpolate_short_gaps(raw_values, config.max_interpolation_gap), config.smoothing_window)
    finite = values[np.isfinite(values)]
    if finite.size < max(config.min_track_frames // 2, 8):
        return []
    amplitude = float(np.percentile(finite, 95) - np.percentile(finite, 5))
    if amplitude < config.minimum_absolute_prominence:
        return []
    prominence_threshold = max(
        config.minimum_absolute_prominence,
        amplitude * config.minimum_peak_prominence_ratio,
    )

    candidates: list[tuple[int, float]] = []
    signals = (values, -values) if include_troughs else (values,)
    prominence_radius = max(config.smoothing_window * 2, 3)
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
            prominence = float(signal[index] - max(np.min(left), np.min(right)))
            if prominence >= prominence_threshold:
                candidates.append((index, float(signal[index])))

    candidates.sort(key=lambda item: item[1], reverse=True)
    accepted: list[int] = []
    for index, _ in candidates:
        if all(abs(float(timestamps[index] - timestamps[other])) >= min_interval_sec for other in accepted):
            accepted.append(index)
    accepted.sort()
    return [round(float(timestamps[index]), 3) for index in accepted]


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


def _unavailable(visibility: float, reason: str) -> EventCount:
    return EventCount(False, 0, (), None, 0.0, round(visibility, 3), reason)


def count_track(
    observations: Iterable[TrackObservation],
    stroke_kind: StrokeKind | str,
    config: CounterConfig | None = None,
    total_processed_frames: int | None = None,
) -> TrackCountResult:
    cfg = config or CounterConfig()
    kind = stroke_kind if isinstance(stroke_kind, StrokeKind) else StrokeKind(stroke_kind)
    rows = sorted(observations, key=lambda item: item.timestamp_sec)
    if not rows:
        raise ValueError("at least one track observation is required")
    timestamps = np.asarray([row.timestamp_sec for row in rows], dtype=np.float64)
    duration = max(float(timestamps[-1] - timestamps[0]), 0.0)
    denominator = total_processed_frames if total_processed_frames is not None else len(rows)
    track_coverage = float(np.clip(len(rows) / max(denominator, 1), 0.0, 1.0))
    warnings: list[str] = []

    left_wrist, left_confidence = _projected_signal(rows, KeypointIndex.LEFT_WRIST, "longitudinal", cfg)
    right_wrist, right_confidence = _projected_signal(rows, KeypointIndex.RIGHT_WRIST, "longitudinal", cfg)
    left_visibility = float(np.mean(left_confidence >= cfg.min_landmark_confidence))
    right_visibility = float(np.mean(right_confidence >= cfg.min_landmark_confidence))
    arm_visibility = (left_visibility + right_visibility) / 2.0

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
    elif arm_visibility < cfg.min_arm_visibility:
        arm_result = _unavailable(arm_visibility, "arms_not_visible")
        left_events = []
        right_events = []
        complete_cycles = 0
    else:
        left_events = _find_peak_events(timestamps, left_wrist, cfg.stroke_min_interval_sec, cfg)
        right_events = _find_peak_events(timestamps, right_wrist, cfg.stroke_min_interval_sec, cfg)
        if kind in {StrokeKind.BREASTSTROKE, StrokeKind.BUTTERFLY}:
            arm_events = _merge_nearby_events((left_events, right_events), cfg.synchronous_merge_sec)
            complete_cycles = len(arm_events)
        else:
            arm_events = sorted(left_events + right_events)
            complete_cycles = min(len(left_events), len(right_events))
        if not arm_events:
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

    if track_coverage < cfg.min_track_coverage:
        kick_result = _unavailable(leg_visibility, "track_coverage_too_low")
    elif len(rows) < cfg.min_track_frames or duration < cfg.min_track_duration_sec:
        kick_result = _unavailable(leg_visibility, "track_too_short")
    elif leg_visibility < cfg.min_leg_visibility:
        kick_result = _unavailable(leg_visibility, "legs_not_visible")
        warnings.append("kick_count_withheld_low_leg_visibility")
    else:
        kick_events = _find_peak_events(
            timestamps,
            kick_values,
            cfg.kick_min_interval_sec,
            cfg,
            include_troughs=include_troughs,
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

    kicks_per_cycle = None
    if kick_result.available and complete_cycles > 0:
        kicks_per_cycle = round(kick_result.count / complete_cycles, 2)
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
        arm_strokes=arm_result,
        complete_cycles=complete_cycles,
        left_arm_events=tuple(left_events),
        right_arm_events=tuple(right_events),
        kicks=kick_result,
        kicks_per_cycle=kicks_per_cycle,
        warnings=tuple(warnings),
    )

"""Lane-aware persistent tracking for multi-swimmer race footage."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable

import numpy as np

from .types import KeypointIndex, PoseDetection, TrackObservation, mean_keypoint_distance


_ASSOCIATION_KEYPOINTS = (
    KeypointIndex.NOSE,
    KeypointIndex.LEFT_SHOULDER,
    KeypointIndex.RIGHT_SHOULDER,
    KeypointIndex.LEFT_HIP,
    KeypointIndex.RIGHT_HIP,
    KeypointIndex.LEFT_KNEE,
    KeypointIndex.RIGHT_KNEE,
)


@dataclass(frozen=True)
class TrackerConfig:
    """Association settings for competition footage.

    Coordinates are normalized to the frame. The lane axis defaults to ``y``
    for the common broadcast view where lanes are stacked vertically.
    """

    max_swimmers: int = 10
    max_missing_frames: int = 15
    max_centroid_distance: float = 0.22
    max_association_cost: float = 1.35
    lane_axis: str = "y"
    centroid_weight: float = 0.58
    lane_weight: float = 0.22
    pose_weight: float = 0.15
    iou_weight: float = 0.05
    velocity_smoothing: float = 0.65
    lane_smoothing: float = 0.90
    min_detection_confidence: float = 0.15

    def __post_init__(self) -> None:
        if self.lane_axis not in {"x", "y"}:
            raise ValueError("lane_axis must be 'x' or 'y'")
        if not 1 <= self.max_swimmers <= 16:
            raise ValueError("max_swimmers must be between 1 and 16")


@dataclass
class _TrackState:
    track_id: str
    lane_id: int
    last_detection: PoseDetection
    last_frame_index: int
    last_timestamp_sec: float
    lane_position: float
    velocity: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=np.float64))
    missing_frames: int = 0
    hits: int = 1
    observations: list[TrackObservation] = field(default_factory=list)
    closed: bool = False

    @property
    def predicted_centroid(self) -> np.ndarray:
        return self.last_detection.centroid + self.velocity * max(self.missing_frames + 1, 1)


def _bbox_iou(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    lx1, ly1, lx2, ly2 = left
    rx1, ry1, rx2, ry2 = right
    ix1, iy1 = max(lx1, rx1), max(ly1, ry1)
    ix2, iy2 = min(lx2, rx2), min(ly2, ry2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    intersection = iw * ih
    left_area = max(0.0, lx2 - lx1) * max(0.0, ly2 - ly1)
    right_area = max(0.0, rx2 - rx1) * max(0.0, ry2 - ry1)
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def _optimal_assignment(costs: np.ndarray, max_cost: float) -> list[tuple[int, int, float]]:
    """Maximize matched tracks, then minimize total association cost.

    Race footage normally has at most ten lanes, so a bitmask dynamic program
    gives a globally consistent assignment without adding SciPy to the public
    deployment dependencies.
    """

    if costs.size == 0:
        return []
    track_count, detection_count = costs.shape

    @lru_cache(maxsize=None)
    def solve(track_index: int, used_mask: int) -> tuple[int, float, tuple[tuple[int, int, float], ...]]:
        if track_index >= track_count:
            return 0, 0.0, ()

        best = solve(track_index + 1, used_mask)
        for detection_index in range(detection_count):
            if used_mask & (1 << detection_index):
                continue
            cost = float(costs[track_index, detection_index])
            if not np.isfinite(cost) or cost > max_cost:
                continue
            matched, total_cost, pairs = solve(track_index + 1, used_mask | (1 << detection_index))
            candidate = (matched + 1, total_cost + cost, ((track_index, detection_index, cost),) + pairs)
            if candidate[0] > best[0] or (candidate[0] == best[0] and candidate[1] < best[1]):
                best = candidate
        return best

    return list(solve(0, 0)[2])


class MultiSwimmerTracker:
    """Keep a stable swimmer ID while detector result order changes."""

    def __init__(self, config: TrackerConfig | None = None) -> None:
        self.config = config or TrackerConfig()
        self._active: dict[str, _TrackState] = {}
        self._closed: dict[str, _TrackState] = {}
        self._next_track_number = 1
        self._next_lane_number = 1

    @property
    def lane_axis_index(self) -> int:
        return 0 if self.config.lane_axis == "x" else 1

    def _new_track(
        self,
        detection: PoseDetection,
        frame_index: int,
        timestamp_sec: float,
    ) -> _TrackState:
        if detection.lane_hint is not None:
            lane_id = detection.lane_hint
            track_id = f"L{lane_id:02d}"
            previous = self._closed.pop(track_id, None)
            if previous is not None:
                previous.closed = False
                previous.missing_frames = 0
                previous.velocity = np.zeros(2, dtype=np.float64)
                previous.last_detection = detection
                previous.last_frame_index = frame_index
                previous.last_timestamp_sec = timestamp_sec
                observation = TrackObservation(track_id, lane_id, frame_index, timestamp_sec, detection)
                previous.observations.append(observation)
                previous.hits += 1
                self._active[track_id] = previous
                return previous
        else:
            track_id = f"S{self._next_track_number:03d}"
            self._next_track_number += 1
            lane_id = self._next_lane_number
            self._next_lane_number += 1
        state = _TrackState(
            track_id=track_id,
            lane_id=lane_id,
            last_detection=detection,
            last_frame_index=frame_index,
            last_timestamp_sec=timestamp_sec,
            lane_position=float(detection.centroid[self.lane_axis_index]),
        )
        observation = TrackObservation(track_id, lane_id, frame_index, timestamp_sec, detection)
        state.observations.append(observation)
        self._active[track_id] = state
        return state

    def _association_cost(self, track: _TrackState, detection: PoseDetection) -> float:
        cfg = self.config
        if detection.lane_hint is not None and detection.lane_hint != track.lane_id:
            return float("inf")
        predicted = track.predicted_centroid
        centroid_distance = float(np.linalg.norm(predicted - detection.centroid))
        allowed_distance = cfg.max_centroid_distance * (1.0 + min(track.missing_frames, 6) * 0.16)
        if detection.lane_hint == track.lane_id:
            allowed_distance = max(allowed_distance, 0.55)
        lane_distance = abs(float(detection.centroid[self.lane_axis_index]) - track.lane_position)
        if centroid_distance > allowed_distance or (
            detection.lane_hint is None and lane_distance > allowed_distance * 0.75
        ):
            return float("inf")
        pose_distance = mean_keypoint_distance(track.last_detection, detection, _ASSOCIATION_KEYPOINTS)
        iou_cost = 1.0 - _bbox_iou(track.last_detection.bbox, detection.bbox)
        return (
            cfg.centroid_weight * (centroid_distance / max(allowed_distance, 1e-6))
            + cfg.lane_weight * (lane_distance / max(allowed_distance * 0.75, 1e-6))
            + cfg.pose_weight * min(pose_distance, 2.0)
            + cfg.iou_weight * iou_cost
        )

    def update(
        self,
        detections: Iterable[PoseDetection],
        frame_index: int,
        timestamp_sec: float,
    ) -> list[TrackObservation]:
        cfg = self.config
        valid = [d for d in detections if d.confidence >= cfg.min_detection_confidence]
        valid.sort(key=lambda item: float(item.centroid[self.lane_axis_index]))
        valid = valid[: cfg.max_swimmers]

        tracks = [state for state in self._active.values() if not state.closed]
        costs = np.full((len(tracks), len(valid)), np.inf, dtype=np.float64)
        for track_index, track in enumerate(tracks):
            for detection_index, detection in enumerate(valid):
                costs[track_index, detection_index] = self._association_cost(track, detection)

        assignments = _optimal_assignment(costs, cfg.max_association_cost)
        matched_track_indexes = {track_index for track_index, _, _ in assignments}
        matched_detection_indexes = {detection_index for _, detection_index, _ in assignments}
        frame_observations: list[TrackObservation] = []

        for track_index, detection_index, cost in assignments:
            state = tracks[track_index]
            detection = valid[detection_index]
            frame_gap = max(frame_index - state.last_frame_index, 1)
            measured_velocity = (detection.centroid - state.last_detection.centroid) / frame_gap
            state.velocity = (
                cfg.velocity_smoothing * state.velocity
                + (1.0 - cfg.velocity_smoothing) * measured_velocity
            )
            state.lane_position = (
                cfg.lane_smoothing * state.lane_position
                + (1.0 - cfg.lane_smoothing) * float(detection.centroid[self.lane_axis_index])
            )
            state.last_detection = detection
            state.last_frame_index = frame_index
            state.last_timestamp_sec = timestamp_sec
            state.missing_frames = 0
            state.hits += 1
            observation = TrackObservation(
                state.track_id,
                state.lane_id,
                frame_index,
                timestamp_sec,
                detection,
                association_cost=cost,
            )
            state.observations.append(observation)
            frame_observations.append(observation)

        for track_index, state in enumerate(tracks):
            if track_index in matched_track_indexes:
                continue
            state.missing_frames += 1
            if state.missing_frames > cfg.max_missing_frames:
                state.closed = True
                self._closed[state.track_id] = state
                self._active.pop(state.track_id, None)

        for detection_index, detection in enumerate(valid):
            if detection_index in matched_detection_indexes:
                continue
            if detection.lane_hint is not None and f"L{detection.lane_hint:02d}" in self._active:
                continue
            state = self._new_track(detection, frame_index, timestamp_sec)
            frame_observations.append(state.observations[-1])

        return sorted(frame_observations, key=lambda item: item.lane_id)

    def all_tracks(self) -> list[list[TrackObservation]]:
        states = list(self._closed.values()) + list(self._active.values())
        states.sort(key=lambda item: item.lane_id)
        return [list(state.observations) for state in states]

    def track_states(self) -> list[dict[str, object]]:
        states = list(self._closed.values()) + list(self._active.values())
        return [
            {
                "track_id": state.track_id,
                "lane_id": state.lane_id,
                "lane_position": state.lane_position,
                "observed_frames": len(state.observations),
                "hits": state.hits,
                "closed": state.closed,
            }
            for state in sorted(states, key=lambda item: item.lane_id)
        ]

"""Shared types for the multi-swimmer analysis baseline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Iterable, Sequence

import numpy as np


class KeypointIndex(IntEnum):
    """MediaPipe-compatible pose landmark indexes used by the counter."""

    NOSE = 0
    LEFT_SHOULDER = 11
    RIGHT_SHOULDER = 12
    LEFT_ELBOW = 13
    RIGHT_ELBOW = 14
    LEFT_WRIST = 15
    RIGHT_WRIST = 16
    LEFT_HIP = 23
    RIGHT_HIP = 24
    LEFT_KNEE = 25
    RIGHT_KNEE = 26
    LEFT_ANKLE = 27
    RIGHT_ANKLE = 28


class StrokeKind(str, Enum):
    FREESTYLE = "freestyle"
    BACKSTROKE = "backstroke"
    BREASTSTROKE = "breaststroke"
    BUTTERFLY = "butterfly"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PoseDetection:
    """One swimmer pose detected in one video frame.

    ``keypoints`` is an ``(N, 4)`` float array containing normalized
    ``x, y, z, confidence`` values. It uses MediaPipe's 33-landmark indexing,
    but another pose estimator can be adapted to this format.
    """

    keypoints: np.ndarray
    bbox: tuple[float, float, float, float]
    confidence: float

    def __post_init__(self) -> None:
        points = np.asarray(self.keypoints, dtype=np.float64)
        if points.ndim != 2 or points.shape[0] < 29 or points.shape[1] != 4:
            raise ValueError("keypoints must have shape (N>=29, 4)")
        if not np.isfinite(points[:, :3]).all():
            raise ValueError("keypoint coordinates must be finite")
        if len(self.bbox) != 4:
            raise ValueError("bbox must contain x1, y1, x2, y2")
        x1, y1, x2, y2 = self.bbox
        if x2 < x1 or y2 < y1:
            raise ValueError("bbox coordinates are reversed")
        object.__setattr__(self, "keypoints", points)
        object.__setattr__(self, "confidence", float(np.clip(self.confidence, 0.0, 1.0)))

    @classmethod
    def from_keypoints(
        cls,
        keypoints: Sequence[Sequence[float]] | np.ndarray,
        confidence: float | None = None,
        visibility_threshold: float = 0.05,
        padding: float = 0.015,
    ) -> "PoseDetection":
        points = np.asarray(keypoints, dtype=np.float64)
        if points.ndim != 2 or points.shape[1] not in (3, 4):
            raise ValueError("keypoints must contain x, y, z[, confidence]")
        if points.shape[1] == 3:
            points = np.column_stack([points, np.ones(points.shape[0], dtype=np.float64)])
        visible = points[:, 3] >= visibility_threshold
        if not visible.any():
            visible = np.ones(points.shape[0], dtype=bool)
        xy = points[visible, :2]
        x1, y1 = np.min(xy, axis=0) - padding
        x2, y2 = np.max(xy, axis=0) + padding
        score = float(np.mean(points[visible, 3])) if confidence is None else confidence
        return cls(points, (float(x1), float(y1), float(x2), float(y2)), score)

    @property
    def centroid(self) -> np.ndarray:
        anchors = np.array(
            [
                KeypointIndex.LEFT_SHOULDER,
                KeypointIndex.RIGHT_SHOULDER,
                KeypointIndex.LEFT_HIP,
                KeypointIndex.RIGHT_HIP,
            ],
            dtype=int,
        )
        points = self.keypoints[anchors]
        visible = points[:, 3] >= 0.15
        if visible.any():
            return np.mean(points[visible, :2], axis=0)
        x1, y1, x2, y2 = self.bbox
        return np.array([(x1 + x2) / 2.0, (y1 + y2) / 2.0], dtype=np.float64)


@dataclass(frozen=True)
class TrackObservation:
    track_id: str
    lane_id: int
    frame_index: int
    timestamp_sec: float
    detection: PoseDetection
    association_cost: float = 0.0
    interpolated: bool = False


def mean_keypoint_distance(
    left: PoseDetection,
    right: PoseDetection,
    indexes: Iterable[int],
    min_confidence: float = 0.15,
) -> float:
    """Return torso-scale-normalized pose distance for association."""

    idx = np.asarray(list(indexes), dtype=int)
    lp = left.keypoints[idx]
    rp = right.keypoints[idx]
    visible = (lp[:, 3] >= min_confidence) & (rp[:, 3] >= min_confidence)
    if not visible.any():
        return 1.0
    distances = np.linalg.norm(lp[visible, :2] - rp[visible, :2], axis=1)
    x1, y1, x2, y2 = left.bbox
    scale = max(np.hypot(x2 - x1, y2 - y1), 0.03)
    return float(np.mean(distances) / scale)

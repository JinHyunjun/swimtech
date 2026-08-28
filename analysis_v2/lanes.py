"""Perspective-aware lane regions for competition footage."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Iterable, Protocol

import numpy as np

from .types import KeypointIndex, PoseDetection


_TORSO_ANCHORS = np.asarray(
    [
        KeypointIndex.LEFT_SHOULDER,
        KeypointIndex.RIGHT_SHOULDER,
        KeypointIndex.LEFT_HIP,
        KeypointIndex.RIGHT_HIP,
    ],
    dtype=int,
)


class PoseProvider(Protocol):
    def detect(self, rgb_frame: np.ndarray, timestamp_ms: int) -> list[PoseDetection]: ...


def _validate_polygon(points: np.ndarray) -> np.ndarray:
    polygon = np.asarray(points, dtype=np.float64)
    if polygon.ndim != 2 or polygon.shape[0] < 3 or polygon.shape[1] != 2:
        raise ValueError("lane polygon must contain at least three x,y points")
    if not np.isfinite(polygon).all() or np.any(polygon < 0.0) or np.any(polygon > 1.0):
        raise ValueError("lane polygon coordinates must be normalized to [0, 1]")
    return polygon


def point_in_polygon(point: np.ndarray, polygon: np.ndarray) -> bool:
    """Return whether a normalized point lies inside a normalized polygon."""

    x, y = (float(value) for value in point)
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            crossing_x = float((x2 - x1) * (y - y1) / (y2 - y1) + x1)
            if x < crossing_x:
                inside = not inside
        previous = current
    return inside


def pose_anchor_inside_ratio(
    detection: PoseDetection,
    lane: "LaneRegion",
    min_confidence: float = 0.12,
) -> float:
    """Return the share of visible torso anchors inside a physical lane.

    A centroid-only check can accept a pose whose shoulders are on the pool
    deck and hips are in the water. Requiring the torso anchors themselves to
    stay in the lane rejects that common false positive while still allowing
    arms and legs to cross a lane boundary during recovery or splash.
    """

    anchors = detection.keypoints[_TORSO_ANCHORS]
    visible = anchors[:, 3] >= min_confidence
    if np.count_nonzero(visible) < 2:
        return 0.0
    inside = sum(lane.contains(point[:2]) for point in anchors[visible])
    return float(inside / np.count_nonzero(visible))


def lane_direction(lane: "LaneRegion") -> np.ndarray:
    """Return the normalized long axis of a perspective lane polygon."""

    polygon = lane.polygon
    first_axis = (polygon[1] - polygon[0]) + (polygon[2] - polygon[3])
    second_axis = (polygon[3] - polygon[0]) + (polygon[2] - polygon[1])
    direction = (
        first_axis
        if np.linalg.norm(first_axis) >= np.linalg.norm(second_axis)
        else second_axis
    )
    length = float(np.linalg.norm(direction))
    return direction / length if length > 1e-9 else np.asarray([1.0, 0.0])


def pose_lane_alignment(
    detection: PoseDetection,
    lane: "LaneRegion",
    min_confidence: float = 0.12,
) -> float:
    """Measure how closely the detected torso follows the swimming lane.

    Pool-deck spectators are usually upright while swimmers are elongated
    along the lane.  This geometry check is independent of model confidence,
    which can be high even when a generic pose model locks onto the wrong
    person.
    """

    points = detection.keypoints
    shoulders = points[[KeypointIndex.LEFT_SHOULDER, KeypointIndex.RIGHT_SHOULDER]]
    hips = points[[KeypointIndex.LEFT_HIP, KeypointIndex.RIGHT_HIP]]
    visible_shoulders = shoulders[:, 3] >= min_confidence
    visible_hips = hips[:, 3] >= min_confidence
    if not visible_shoulders.any() or not visible_hips.any():
        return 0.0
    body_axis = np.mean(shoulders[visible_shoulders, :2], axis=0) - np.mean(
        hips[visible_hips, :2], axis=0
    )
    length = float(np.linalg.norm(body_axis))
    if length <= 1e-9:
        return 0.0
    return float(abs(np.dot(body_axis / length, lane_direction(lane))))


@dataclass(frozen=True)
class LaneRegion:
    lane_id: int
    polygon: np.ndarray

    def __post_init__(self) -> None:
        if self.lane_id < 1:
            raise ValueError("lane_id must be positive")
        object.__setattr__(self, "polygon", _validate_polygon(self.polygon))

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        minimum = np.min(self.polygon, axis=0)
        maximum = np.max(self.polygon, axis=0)
        return float(minimum[0]), float(minimum[1]), float(maximum[0]), float(maximum[1])

    def contains(self, point: np.ndarray) -> bool:
        return point_in_polygon(point, self.polygon)


@dataclass(frozen=True)
class LaneLayout:
    lanes: tuple[LaneRegion, ...]
    source: str | None = None
    active_start_sec: float | None = None
    active_end_sec: float | None = None

    def __post_init__(self) -> None:
        if not self.lanes:
            raise ValueError("lane layout must contain at least one lane")
        lane_ids = [lane.lane_id for lane in self.lanes]
        if len(lane_ids) != len(set(lane_ids)):
            raise ValueError("lane IDs must be unique")
        if self.active_start_sec is not None and self.active_start_sec < 0:
            raise ValueError("active_start_sec cannot be negative")
        if (
            self.active_start_sec is not None
            and self.active_end_sec is not None
            and self.active_end_sec <= self.active_start_sec
        ):
            raise ValueError("active_end_sec must be after active_start_sec")

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "LaneLayout":
        raw_lanes = data.get("lanes", [])
        if not isinstance(raw_lanes, list):
            raise ValueError("lanes must be a list")
        if raw_lanes:
            lanes = tuple(
                LaneRegion(int(item["lane_id"]), np.asarray(item["polygon"], dtype=np.float64))
                for item in raw_lanes
            )
        else:
            quad = data.get("lane_quad")
            if not isinstance(quad, dict):
                raise ValueError("provide lanes or lane_quad")
            lane_ids = quad.get("lane_ids")
            corners = quad.get("corners")
            if not isinstance(lane_ids, list) or not isinstance(corners, list):
                raise ValueError("lane_quad requires lane_ids and four corners")
            generated = cls.from_trapezoid(
                tuple(int(value) for value in lane_ids),
                np.asarray(corners, dtype=np.float64),
                str(quad.get("axis", "horizontal")),
            )
            lanes = generated.lanes
        active = data.get("active_interval_sec")
        start = end = None
        if active is not None:
            if not isinstance(active, list) or len(active) != 2:
                raise ValueError("active_interval_sec must be [start, end]")
            start = float(active[0]) if active[0] is not None else None
            end = float(active[1]) if active[1] is not None else None
        source = data.get("source")
        return cls(lanes, str(source) if source else None, start, end)

    @classmethod
    def from_trapezoid(
        cls,
        lane_ids: tuple[int, ...],
        corners: np.ndarray,
        axis: str = "horizontal",
    ) -> "LaneLayout":
        """Split a pool quadrilateral into equally spaced perspective lanes.

        Corners are top-left, top-right, bottom-right, bottom-left. ``axis``
        describes whether lane centre lines run horizontally or vertically.
        """

        quad = np.asarray(corners, dtype=np.float64)
        if quad.shape != (4, 2):
            raise ValueError("trapezoid corners must be top-left, top-right, bottom-right, bottom-left")
        _validate_polygon(quad)
        if axis not in {"horizontal", "vertical"}:
            raise ValueError("lane_quad axis must be horizontal or vertical")
        if not lane_ids:
            raise ValueError("lane_quad requires lane IDs")
        lanes: list[LaneRegion] = []
        count = len(lane_ids)
        top_left, top_right, bottom_right, bottom_left = quad
        for index, lane_id in enumerate(lane_ids):
            first, second = index / count, (index + 1) / count
            if axis == "horizontal":
                upper_left = top_left + (bottom_left - top_left) * first
                upper_right = top_right + (bottom_right - top_right) * first
                lower_right = top_right + (bottom_right - top_right) * second
                lower_left = top_left + (bottom_left - top_left) * second
            else:
                upper_left = top_left + (top_right - top_left) * first
                upper_right = top_left + (top_right - top_left) * second
                lower_right = bottom_left + (bottom_right - bottom_left) * second
                lower_left = bottom_left + (bottom_right - bottom_left) * first
            lanes.append(
                LaneRegion(
                    lane_id,
                    np.asarray([upper_left, upper_right, lower_right, lower_left]),
                )
            )
        return cls(tuple(lanes))

    @classmethod
    def load(cls, path: str | Path) -> "LaneLayout":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "source": self.source,
            "lanes": [
                {"lane_id": lane.lane_id, "polygon": lane.polygon.round(6).tolist()}
                for lane in self.lanes
            ],
        }
        if self.active_start_sec is not None or self.active_end_sec is not None:
            result["active_interval_sec"] = [self.active_start_sec, self.active_end_sec]
        return result

    def lane_for_point(self, point: np.ndarray) -> LaneRegion | None:
        matches = [lane for lane in self.lanes if lane.contains(point)]
        if not matches:
            return None
        return min(matches, key=lambda lane: float(np.linalg.norm(np.mean(lane.polygon, axis=0) - point)))


def assign_detections_to_lanes(
    detections: Iterable[PoseDetection],
    layout: LaneLayout,
    one_per_lane: bool = True,
) -> list[PoseDetection]:
    """Attach stable lane hints and reject spectators/out-of-pool poses."""

    assigned: list[PoseDetection] = []
    for detection in detections:
        lane = layout.lane_for_point(detection.centroid)
        if lane is not None:
            assigned.append(replace(detection, lane_hint=lane.lane_id))
    if not one_per_lane:
        return assigned
    best: dict[int, PoseDetection] = {}
    for detection in assigned:
        lane_id = int(detection.lane_hint or 0)
        if lane_id not in best or detection.confidence > best[lane_id].confidence:
            best[lane_id] = detection
    return [best[lane_id] for lane_id in sorted(best)]


def _crop_bounds(
    lane: LaneRegion,
    width: int,
    height: int,
    padding: float,
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = lane.bounds
    x_pad = (x2 - x1) * padding
    y_pad = (y2 - y1) * padding
    return (
        max(0, int(np.floor((x1 - x_pad) * width))),
        max(0, int(np.floor((y1 - y_pad) * height))),
        min(width, int(np.ceil((x2 + x_pad) * width))),
        min(height, int(np.ceil((y2 + y_pad) * height))),
    )


def _remap_crop_detection(
    detection: PoseDetection,
    crop: tuple[int, int, int, int],
    frame_width: int,
    frame_height: int,
    lane_id: int,
    rotation: str = "none",
) -> PoseDetection:
    x1, y1, x2, y2 = crop
    points = detection.keypoints.copy()
    if rotation == "clockwise":
        rotated_x = points[:, 0].copy()
        points[:, 0] = points[:, 1]
        points[:, 1] = 1.0 - rotated_x
    elif rotation == "counterclockwise":
        rotated_y = points[:, 1].copy()
        points[:, 1] = points[:, 0]
        points[:, 0] = 1.0 - rotated_y
    points[:, 0] = (x1 + points[:, 0] * (x2 - x1)) / frame_width
    points[:, 1] = (y1 + points[:, 1] * (y2 - y1)) / frame_height
    points[:, 2] *= max(x2 - x1, y2 - y1) / max(frame_width, frame_height)
    return PoseDetection.from_keypoints(points, confidence=detection.confidence, lane_hint=lane_id)


class LaneCropPoseProvider:
    """Run a pose provider on each perspective lane crop."""

    def __init__(
        self,
        provider: PoseProvider,
        layout: LaneLayout,
        crop_padding: float = 0.08,
        rotation: str = "none",
        min_anchor_inside_ratio: float = 0.0,
        min_anchor_confidence: float = 0.12,
        min_lane_alignment: float = 0.0,
    ) -> None:
        if not 0.0 <= crop_padding <= 0.5:
            raise ValueError("crop_padding must be between 0 and 0.5")
        if rotation not in {"none", "clockwise", "counterclockwise"}:
            raise ValueError("rotation must be none, clockwise, or counterclockwise")
        if not 0.0 <= min_anchor_inside_ratio <= 1.0:
            raise ValueError("min_anchor_inside_ratio must be between 0 and 1")
        if not 0.0 <= min_anchor_confidence <= 1.0:
            raise ValueError("min_anchor_confidence must be between 0 and 1")
        if not 0.0 <= min_lane_alignment <= 1.0:
            raise ValueError("min_lane_alignment must be between 0 and 1")
        self.provider = provider
        self.layout = layout
        self.crop_padding = crop_padding
        self.rotation = rotation
        self.min_anchor_inside_ratio = min_anchor_inside_ratio
        self.min_anchor_confidence = min_anchor_confidence
        self.min_lane_alignment = min_lane_alignment

    def detect(self, rgb_frame: np.ndarray, timestamp_ms: int) -> list[PoseDetection]:
        height, width = rgb_frame.shape[:2]
        assigned: list[PoseDetection] = []
        for lane in self.layout.lanes:
            crop_bounds = _crop_bounds(lane, width, height, self.crop_padding)
            x1, y1, x2, y2 = crop_bounds
            if x2 - x1 < 16 or y2 - y1 < 16:
                continue
            crop = np.ascontiguousarray(rgb_frame[y1:y2, x1:x2])
            if self.rotation == "clockwise":
                crop = np.ascontiguousarray(np.rot90(crop, k=3))
            elif self.rotation == "counterclockwise":
                crop = np.ascontiguousarray(np.rot90(crop, k=1))
            for detection in self.provider.detect(crop, timestamp_ms):
                mapped = _remap_crop_detection(
                    detection,
                    crop_bounds,
                    width,
                    height,
                    lane.lane_id,
                    self.rotation,
                )
                if (
                    lane.contains(mapped.centroid)
                    and (
                        self.min_anchor_inside_ratio <= 0.0
                        or pose_anchor_inside_ratio(mapped, lane, self.min_anchor_confidence)
                        >= self.min_anchor_inside_ratio
                    )
                    and (
                        self.min_lane_alignment <= 0.0
                        or pose_lane_alignment(mapped, lane, self.min_anchor_confidence)
                        >= self.min_lane_alignment
                    )
                ):
                    assigned.append(mapped)
        return assign_detections_to_lanes(assigned, self.layout, one_per_lane=True)

    def close(self) -> None:
        close = getattr(self.provider, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> "LaneCropPoseProvider":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


class LaneMosaicPoseProvider:
    """Detect all rotated lane crops in one batched mosaic inference.

    Running a person detector once per lane is accurate but too slow on CPU.
    The mosaic keeps swimmers upright while reducing eight lane detections to a
    single provider call per video frame.
    """

    def __init__(
        self,
        provider: PoseProvider,
        layout: LaneLayout,
        columns: int = 4,
        tile_size: tuple[int, int] = (192, 256),
        crop_padding: float = 0.20,
        rotation: str = "clockwise",
    ) -> None:
        if columns < 1:
            raise ValueError("columns must be positive")
        if tile_size[0] < 32 or tile_size[1] < 32:
            raise ValueError("mosaic tiles must be at least 32 pixels")
        if rotation not in {"clockwise", "counterclockwise"}:
            raise ValueError("mosaic rotation must be clockwise or counterclockwise")
        self.provider = provider
        self.layout = layout
        self.columns = columns
        self.tile_size = tile_size
        self.crop_padding = crop_padding
        self.rotation = rotation

    def detect(self, rgb_frame: np.ndarray, timestamp_ms: int) -> list[PoseDetection]:
        try:
            import cv2
        except ImportError as exc:  # pragma: no cover - offline dependency
            raise RuntimeError("OpenCV is required for lane mosaic inference") from exc
        height, width = rgb_frame.shape[:2]
        tile_width, tile_height = self.tile_size
        rows = int(np.ceil(len(self.layout.lanes) / self.columns))
        mosaic = np.zeros((rows * tile_height, self.columns * tile_width, 3), dtype=np.uint8)
        slots: list[tuple[LaneRegion, tuple[int, int, int, int]]] = []
        for index, lane in enumerate(self.layout.lanes):
            bounds = _crop_bounds(lane, width, height, self.crop_padding)
            x1, y1, x2, y2 = bounds
            crop = np.ascontiguousarray(rgb_frame[y1:y2, x1:x2])
            crop = np.rot90(crop, k=3 if self.rotation == "clockwise" else 1)
            crop = cv2.resize(np.ascontiguousarray(crop), (tile_width, tile_height))
            row, column = divmod(index, self.columns)
            mosaic[
                row * tile_height : (row + 1) * tile_height,
                column * tile_width : (column + 1) * tile_width,
            ] = crop
            slots.append((lane, bounds))

        assigned: list[PoseDetection] = []
        mosaic_height, mosaic_width = mosaic.shape[:2]
        for detection in self.provider.detect(mosaic, timestamp_ms):
            center_x = int(np.clip(detection.centroid[0] * mosaic_width, 0, mosaic_width - 1))
            center_y = int(np.clip(detection.centroid[1] * mosaic_height, 0, mosaic_height - 1))
            column, row = center_x // tile_width, center_y // tile_height
            slot_index = row * self.columns + column
            if slot_index >= len(slots):
                continue
            lane, bounds = slots[slot_index]
            points = detection.keypoints.copy()
            points[:, 0] = (points[:, 0] * mosaic_width - column * tile_width) / tile_width
            points[:, 1] = (points[:, 1] * mosaic_height - row * tile_height) / tile_height
            if np.any(points[:, :2] < -0.15) or np.any(points[:, :2] > 1.15):
                continue
            local = PoseDetection.from_keypoints(points, confidence=detection.confidence)
            mapped = _remap_crop_detection(
                local,
                bounds,
                width,
                height,
                lane.lane_id,
                self.rotation,
            )
            if lane.contains(mapped.centroid):
                assigned.append(mapped)
        return assign_detections_to_lanes(assigned, self.layout, one_per_lane=True)

    def close(self) -> None:
        close = getattr(self.provider, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> "LaneMosaicPoseProvider":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

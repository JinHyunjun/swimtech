"""Optional MediaPipe adapter for the offline multi-swimmer baseline."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .types import KeypointIndex, PoseDetection


def _remap_keypoints(
    points: np.ndarray,
    tile: tuple[int, int, int, int],
    frame_width: int,
    frame_height: int,
) -> np.ndarray:
    x1, y1, x2, y2 = tile
    mapped = points.copy()
    mapped[:, 0] = (x1 + mapped[:, 0] * (x2 - x1)) / frame_width
    mapped[:, 1] = (y1 + mapped[:, 1] * (y2 - y1)) / frame_height
    mapped[:, 2] = mapped[:, 2] * max(x2 - x1, y2 - y1) / max(frame_width, frame_height)
    return mapped


def _detection_overlap(left: PoseDetection, right: PoseDetection) -> float:
    lx1, ly1, lx2, ly2 = left.bbox
    rx1, ry1, rx2, ry2 = right.bbox
    ix1, iy1 = max(lx1, rx1), max(ly1, ry1)
    ix2, iy2 = min(lx2, rx2), min(ly2, ry2)
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    left_area = max(0.0, lx2 - lx1) * max(0.0, ly2 - ly1)
    right_area = max(0.0, rx2 - rx1) * max(0.0, ry2 - ry1)
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def deduplicate_detections(
    detections: list[PoseDetection],
    max_centroid_distance: float = 0.055,
    min_iou: float = 0.22,
) -> list[PoseDetection]:
    """Merge the same athlete detected in overlapping tiles."""

    kept: list[PoseDetection] = []
    for detection in sorted(detections, key=lambda item: item.confidence, reverse=True):
        duplicate = any(
            np.linalg.norm(detection.centroid - existing.centroid) <= max_centroid_distance
            or _detection_overlap(detection, existing) >= min_iou
            for existing in kept
        )
        if not duplicate:
            kept.append(detection)
    return kept


def _orientation_matches(points: np.ndarray, orientation: str, min_confidence: float = 0.15) -> bool:
    if orientation == "any":
        return True
    required = np.array(
        [
            KeypointIndex.LEFT_SHOULDER,
            KeypointIndex.RIGHT_SHOULDER,
            KeypointIndex.LEFT_HIP,
            KeypointIndex.RIGHT_HIP,
        ],
        dtype=int,
    )
    anchors = points[required]
    if np.any(anchors[:, 3] < min_confidence):
        return True  # Do not reject a partially visible swimmer at this stage.
    shoulder_mid = np.mean(anchors[:2, :2], axis=0)
    hip_mid = np.mean(anchors[2:, :2], axis=0)
    direction = np.abs(shoulder_mid - hip_mid)
    if orientation == "horizontal":
        return bool(direction[0] >= direction[1] * 0.65)
    return bool(direction[1] >= direction[0] * 0.65)


def build_overlapping_tiles(
    frame_width: int,
    frame_height: int,
    columns: int,
    rows: int,
    overlap: float,
    roi: tuple[float, float, float, float],
) -> list[tuple[int, int, int, int]]:
    """Build overlapping pixel tiles inside a normalized pool ROI."""

    if columns < 1 or rows < 1:
        raise ValueError("tile rows and columns must be positive")
    if not 0.0 <= overlap < 0.8:
        raise ValueError("tile overlap must be in [0, 0.8)")
    rx1, ry1, rx2, ry2 = roi
    if not (0.0 <= rx1 < rx2 <= 1.0 and 0.0 <= ry1 < ry2 <= 1.0):
        raise ValueError("pool ROI must be normalized x1,y1,x2,y2")
    px1, py1 = int(rx1 * frame_width), int(ry1 * frame_height)
    px2, py2 = int(np.ceil(rx2 * frame_width)), int(np.ceil(ry2 * frame_height))
    roi_width, roi_height = px2 - px1, py2 - py1
    tile_width = roi_width / columns
    tile_height = roi_height / rows
    pad_x, pad_y = tile_width * overlap / 2.0, tile_height * overlap / 2.0
    tiles: list[tuple[int, int, int, int]] = []
    for row in range(rows):
        for column in range(columns):
            x1 = max(px1, int(np.floor(px1 + column * tile_width - pad_x)))
            y1 = max(py1, int(np.floor(py1 + row * tile_height - pad_y)))
            x2 = min(px2, int(np.ceil(px1 + (column + 1) * tile_width + pad_x)))
            y2 = min(py2, int(np.ceil(py1 + (row + 1) * tile_height + pad_y)))
            if x2 - x1 >= 16 and y2 - y1 >= 16:
                tiles.append((x1, y1, x2, y2))
    return tiles


class MediaPipeMultiPoseProvider:
    """Return every pose found in a frame instead of only pose zero.

    Heavy computer-vision dependencies are imported lazily so the public
    FastAPI application does not start or install this pipeline accidentally.
    """

    def __init__(
        self,
        model_path: str | Path,
        max_swimmers: int = 10,
        min_detection_confidence: float = 0.25,
        min_presence_confidence: float = 0.25,
        min_tracking_confidence: float = 0.25,
    ) -> None:
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision as mp_vision
        except ImportError as exc:  # pragma: no cover - depends on optional local packages
            raise RuntimeError(
                "MediaPipe is an optional offline dependency. Install the legacy CV environment first."
            ) from exc

        path = Path(model_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        self._mp = mp
        options = mp_vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(path)),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_poses=max_swimmers,
            min_pose_detection_confidence=min_detection_confidence,
            min_pose_presence_confidence=min_presence_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._detector = mp_vision.PoseLandmarker.create_from_options(options)

    def detect(self, rgb_frame: np.ndarray, timestamp_ms: int) -> list[PoseDetection]:
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb_frame)
        result = self._detector.detect_for_video(image, timestamp_ms)
        detections: list[PoseDetection] = []
        for pose in result.pose_landmarks or []:
            points = np.asarray(
                [
                    [
                        float(item.x),
                        float(item.y),
                        float(item.z),
                        float(min(getattr(item, "visibility", 1.0), getattr(item, "presence", 1.0))),
                    ]
                    for item in pose
                ],
                dtype=np.float64,
            )
            detections.append(PoseDetection.from_keypoints(points))
        return detections

    def close(self) -> None:
        self._detector.close()

    def __enter__(self) -> "MediaPipeMultiPoseProvider":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


class MediaPipeTiledPoseProvider:
    """Enlarge overlapping pool tiles to recover small swimmers.

    Broadcast race footage often makes every athlete too small for a generic
    whole-frame pose detector. This provider runs image-mode inference on
    overlapping pool crops, maps landmarks back to the original frame, removes
    duplicates, and leaves temporal identity to ``MultiSwimmerTracker``.
    """

    def __init__(
        self,
        model_path: str | Path,
        max_swimmers: int = 10,
        tile_columns: int = 3,
        tile_rows: int = 3,
        tile_overlap: float = 0.28,
        pool_roi: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0),
        orientation: str = "horizontal",
        poses_per_tile: int = 2,
        min_detection_confidence: float = 0.20,
        min_presence_confidence: float = 0.20,
    ) -> None:
        if orientation not in {"any", "horizontal", "vertical"}:
            raise ValueError("orientation must be any, horizontal, or vertical")
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision as mp_vision
        except ImportError as exc:  # pragma: no cover - optional local packages
            raise RuntimeError(
                "MediaPipe is an optional offline dependency. Install the legacy CV environment first."
            ) from exc

        path = Path(model_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        # Validate geometry before loading the model.
        build_overlapping_tiles(100, 100, tile_columns, tile_rows, tile_overlap, pool_roi)
        self._mp = mp
        self.max_swimmers = max_swimmers
        self.tile_columns = tile_columns
        self.tile_rows = tile_rows
        self.tile_overlap = tile_overlap
        self.pool_roi = pool_roi
        self.orientation = orientation
        options = mp_vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(path)),
            running_mode=mp_vision.RunningMode.IMAGE,
            num_poses=poses_per_tile,
            min_pose_detection_confidence=min_detection_confidence,
            min_pose_presence_confidence=min_presence_confidence,
        )
        self._detector = mp_vision.PoseLandmarker.create_from_options(options)

    def detect(self, rgb_frame: np.ndarray, timestamp_ms: int = 0) -> list[PoseDetection]:
        del timestamp_ms  # Image mode intentionally delegates time identity to the external tracker.
        height, width = rgb_frame.shape[:2]
        tiles = build_overlapping_tiles(
            width,
            height,
            self.tile_columns,
            self.tile_rows,
            self.tile_overlap,
            self.pool_roi,
        )
        candidates: list[PoseDetection] = []
        for tile in tiles:
            x1, y1, x2, y2 = tile
            crop = np.ascontiguousarray(rgb_frame[y1:y2, x1:x2])
            image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=crop)
            result = self._detector.detect(image)
            for pose in result.pose_landmarks or []:
                local_points = np.asarray(
                    [
                        [
                            float(item.x),
                            float(item.y),
                            float(item.z),
                            float(min(getattr(item, "visibility", 1.0), getattr(item, "presence", 1.0))),
                        ]
                        for item in pose
                    ],
                    dtype=np.float64,
                )
                points = _remap_keypoints(local_points, tile, width, height)
                if not _orientation_matches(points, self.orientation):
                    continue
                candidates.append(PoseDetection.from_keypoints(points))
        return deduplicate_detections(candidates)[: self.max_swimmers]

    def close(self) -> None:
        self._detector.close()

    def __enter__(self) -> "MediaPipeTiledPoseProvider":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

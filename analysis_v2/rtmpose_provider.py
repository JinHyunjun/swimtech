"""Optional RTMPose adapter for offline detector comparison.

``rtmlib`` supplies a person detector followed by RTMPose.  It is imported
lazily and remains outside the deployed FastAPI dependency set.
"""

from __future__ import annotations

import numpy as np

from .types import KeypointIndex, PoseDetection


COCO_TO_MEDIAPIPE = {
    0: KeypointIndex.NOSE,
    5: KeypointIndex.LEFT_SHOULDER,
    6: KeypointIndex.RIGHT_SHOULDER,
    7: KeypointIndex.LEFT_ELBOW,
    8: KeypointIndex.RIGHT_ELBOW,
    9: KeypointIndex.LEFT_WRIST,
    10: KeypointIndex.RIGHT_WRIST,
    11: KeypointIndex.LEFT_HIP,
    12: KeypointIndex.RIGHT_HIP,
    13: KeypointIndex.LEFT_KNEE,
    14: KeypointIndex.RIGHT_KNEE,
    15: KeypointIndex.LEFT_ANKLE,
    16: KeypointIndex.RIGHT_ANKLE,
}

_REQUIRED_COCO = np.asarray([5, 6, 11, 12], dtype=int)


def coco_pose_to_detection(
    keypoints: np.ndarray,
    scores: np.ndarray,
    frame_width: int,
    frame_height: int,
    min_anchor_confidence: float = 0.12,
) -> PoseDetection | None:
    """Convert a COCO-17 pixel pose to the pipeline's MediaPipe-33 layout."""

    xy = np.asarray(keypoints, dtype=np.float64)
    confidence = np.asarray(scores, dtype=np.float64)
    if xy.shape != (17, 2) or confidence.shape != (17,):
        raise ValueError("RTMPose output must be COCO keypoints (17,2) and scores (17,)")
    if frame_width <= 0 or frame_height <= 0:
        raise ValueError("frame dimensions must be positive")
    if np.count_nonzero(confidence[_REQUIRED_COCO] >= min_anchor_confidence) < 2:
        return None

    points = np.zeros((33, 4), dtype=np.float64)
    for coco_index, media_index in COCO_TO_MEDIAPIPE.items():
        points[int(media_index)] = [
            float(xy[coco_index, 0] / frame_width),
            float(xy[coco_index, 1] / frame_height),
            0.0,
            float(np.clip(confidence[coco_index], 0.0, 1.0)),
        ]
    visible = confidence[confidence >= min_anchor_confidence]
    pose_confidence = float(np.mean(visible)) if visible.size else 0.0
    return PoseDetection.from_keypoints(points, confidence=pose_confidence)


class RTMPoseProvider:
    """Detect multiple people with YOLOX + RTMPose through ONNX Runtime."""

    def __init__(
        self,
        mode: str = "lightweight",
        backend: str = "onnxruntime",
        device: str = "cpu",
        max_swimmers: int = 10,
        min_pose_confidence: float = 0.12,
    ) -> None:
        if mode not in {"lightweight", "balanced", "performance"}:
            raise ValueError("mode must be lightweight, balanced, or performance")
        try:
            from rtmlib import Body
        except ImportError as exc:  # pragma: no cover - optional offline dependency
            raise RuntimeError("Install rtmlib and onnxruntime for offline RTMPose experiments") from exc
        self.model = Body(mode=mode, backend=backend, device=device, to_openpose=False)
        self.max_swimmers = max_swimmers
        self.min_pose_confidence = min_pose_confidence

    def detect(self, rgb_frame: np.ndarray, timestamp_ms: int = 0) -> list[PoseDetection]:
        del timestamp_ms
        if rgb_frame.ndim != 3 or rgb_frame.shape[2] != 3:
            raise ValueError("rgb_frame must have shape (height, width, 3)")
        height, width = rgb_frame.shape[:2]
        # rtmlib follows OpenCV's BGR convention.
        bgr_frame = np.ascontiguousarray(rgb_frame[:, :, ::-1])
        keypoints, scores = self.model(bgr_frame)
        detections: list[PoseDetection] = []
        for person_points, person_scores in zip(keypoints, scores):
            detection = coco_pose_to_detection(
                person_points,
                person_scores,
                width,
                height,
                self.min_pose_confidence,
            )
            if detection is not None and detection.confidence >= self.min_pose_confidence:
                detections.append(detection)
        detections.sort(key=lambda item: item.confidence, reverse=True)
        return detections[: self.max_swimmers]

    def close(self) -> None:
        # rtmlib/ONNX Runtime owns no explicit close method.
        return None

    def __enter__(self) -> "RTMPoseProvider":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


class RTMPoseTopDownProvider:
    """Estimate one pose from a known crop without running a person detector."""

    def __init__(
        self,
        mode: str = "lightweight",
        backend: str = "onnxruntime",
        device: str = "cpu",
        min_pose_confidence: float = 0.16,
    ) -> None:
        if mode not in {"lightweight", "balanced", "performance"}:
            raise ValueError("mode must be lightweight, balanced, or performance")
        try:
            from rtmlib import Body, RTMPose
        except ImportError as exc:  # pragma: no cover - optional offline dependency
            raise RuntimeError("Install rtmlib and onnxruntime for offline RTMPose experiments") from exc
        settings = Body.MODE[mode]
        self.model = RTMPose(
            settings["pose"],
            model_input_size=settings["pose_input_size"],
            to_openpose=False,
            backend=backend,
            device=device,
        )
        self.min_pose_confidence = min_pose_confidence

    def detect(self, rgb_frame: np.ndarray, timestamp_ms: int = 0) -> list[PoseDetection]:
        del timestamp_ms
        height, width = rgb_frame.shape[:2]
        bgr_frame = np.ascontiguousarray(rgb_frame[:, :, ::-1])
        keypoints, scores = self.model(bgr_frame, bboxes=[[0, 0, width, height]])
        if not len(keypoints):
            return []
        detection = coco_pose_to_detection(
            keypoints[0],
            scores[0],
            width,
            height,
            self.min_pose_confidence,
        )
        if detection is None or detection.confidence < self.min_pose_confidence:
            return []
        return [detection]

    def close(self) -> None:
        return None

    def __enter__(self) -> "RTMPoseTopDownProvider":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

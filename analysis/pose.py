"""
SwimTech — 포즈 분석 핵심 모듈
MediaPipe Tasks API (0.10.x 이상 / Python 3.12 호환) 기준
랜드마크 추출 → 팔 각도 / 머리 각도 / 발차기 횟수 계산
"""
import cv2
import numpy as np
import urllib.request
import os
from dataclasses import dataclass, field
from typing import Optional

from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode
import mediapipe as mp

class LM:
    NOSE           = 0
    LEFT_EAR       = 7
    RIGHT_EAR      = 8
    LEFT_SHOULDER  = 11
    RIGHT_SHOULDER = 12
    LEFT_ELBOW     = 13
    RIGHT_ELBOW    = 14
    LEFT_WRIST     = 15
    RIGHT_WRIST    = 16
    LEFT_HIP       = 23
    RIGHT_HIP      = 24
    LEFT_ANKLE     = 27
    RIGHT_ANKLE    = 28

MODEL_PATH = os.path.join(os.path.dirname(__file__), "pose_landmarker.task")
MODEL_URL  = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_lite/float16/latest/"
    "pose_landmarker_lite.task"
)

def _ensure_model():
    if not os.path.exists(MODEL_PATH):
        print("[SwimTech] MediaPipe 모델 다운로드 중... (최초 1회, 약 5MB)")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        print(f"[SwimTech] 모델 저장 완료: {MODEL_PATH}")


@dataclass
class FrameMetric:
    frame_number: int
    timestamp_sec: float
    left_elbow_angle: Optional[float] = None
    right_elbow_angle: Optional[float] = None
    left_shoulder_angle: Optional[float] = None
    right_shoulder_angle: Optional[float] = None
    head_angle: Optional[float] = None
    body_roll: Optional[float] = None
    kick_detected: bool = False
    landmarks_visible: bool = False


@dataclass
class AnalysisSummary:
    total_frames: int = 0
    analyzed_frames: int = 0
    duration_sec: float = 0.0
    left_arm_angle_avg: float = 0.0
    right_arm_angle_avg: float = 0.0
    left_arm_angle_min: float = 0.0
    right_arm_angle_min: float = 0.0
    arm_symmetry_score: float = 0.0
    kick_count: int = 0
    kick_frequency_hz: float = 0.0
    head_angle_avg: float = 0.0
    head_rotation_score: float = 0.0
    overall_score: float = 0.0
    frame_metrics: list = field(default_factory=list)


def calc_angle(a, b, c) -> float:
    a, b, c = np.array(a), np.array(b), np.array(c)
    ba, bc = a - b, c - b
    cos_v = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-6)
    return float(np.degrees(np.arccos(np.clip(cos_v, -1.0, 1.0))))

def lm_xy(landmarks, idx) -> list:
    return [landmarks[idx].x, landmarks[idx].y]


class KickDetector:
    def __init__(self, threshold: float = 0.015):
        self.threshold = threshold
        self._prev_y: Optional[float] = None
        self._direction: int = 0
        self.kick_count: int = 0

    def update(self, l_y: float, r_y: float) -> bool:
        avg_y = (l_y + r_y) / 2
        kicked = False
        if self._prev_y is not None:
            delta = avg_y - self._prev_y
            if delta > self.threshold and self._direction != 1:
                self._direction = 1
            elif delta < -self.threshold and self._direction == 1:
                self._direction = -1
                self.kick_count += 1
                kicked = True
        self._prev_y = avg_y
        return kicked


def _draw_overlay(frame, metric: FrameMetric, width: int, height: int):
    w = width
    def put(text, y, color=(255,255,255)):
        cv2.putText(frame, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,0,0), 3)
        cv2.putText(frame, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1)
    put(f"Time : {metric.timestamp_sec:.2f}s", 30)
    if metric.left_elbow_angle is not None:
        good, bad = (0,200,0), (0,80,255)
        put(f"L Elbow: {metric.left_elbow_angle:.1f}deg",  60,
            good if 80 <= metric.left_elbow_angle  <= 120 else bad)
        put(f"R Elbow: {metric.right_elbow_angle:.1f}deg", 85,
            good if 80 <= metric.right_elbow_angle <= 120 else bad)
        put(f"Head  : {metric.head_angle:.1f}deg", 110, (200,200,0))
    if metric.kick_detected:
        cv2.putText(frame, "KICK!", (w-120, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,255,255), 3)


SKELETON_CONNECTIONS = [
    (LM.LEFT_SHOULDER,  LM.LEFT_ELBOW),
    (LM.LEFT_ELBOW,     LM.LEFT_WRIST),
    (LM.RIGHT_SHOULDER, LM.RIGHT_ELBOW),
    (LM.RIGHT_ELBOW,    LM.RIGHT_WRIST),
    (LM.LEFT_SHOULDER,  LM.RIGHT_SHOULDER),
    (LM.LEFT_HIP,       LM.RIGHT_HIP),
    (LM.LEFT_SHOULDER,  LM.LEFT_HIP),
    (LM.RIGHT_SHOULDER, LM.RIGHT_HIP),
    (LM.LEFT_HIP,       LM.LEFT_ANKLE),
    (LM.RIGHT_HIP,      LM.RIGHT_ANKLE),
]
KEY_POINTS = [
    LM.LEFT_SHOULDER, LM.RIGHT_SHOULDER,
    LM.LEFT_ELBOW,    LM.RIGHT_ELBOW,
    LM.LEFT_WRIST,    LM.RIGHT_WRIST,
    LM.LEFT_HIP,      LM.RIGHT_HIP,
    LM.LEFT_ANKLE,    LM.RIGHT_ANKLE,
]


def analyze_video(video_path: str, output_path: Optional[str] = None) -> AnalysisSummary:
    _ensure_model()

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"영상을 열 수 없습니다: {video_path}")

    fps          = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width        = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height       = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    writer = None
    if output_path:
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        writer = cv2.VideoWriter(output_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))

    kick_detector = KickDetector()
    summary = AnalysisSummary(total_frames=total_frames, duration_sec=total_frames / fps)
    l_elbows, r_elbows, l_shoulders, r_shoulders, head_angles = [], [], [], [], []

    options = PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    with PoseLandmarker.create_from_options(options) as landmarker:
        frame_num = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            timestamp_ms = int(frame_num / fps * 1000)
            rgb      = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result   = landmarker.detect_for_video(mp_image, timestamp_ms)

            metric = FrameMetric(frame_number=frame_num, timestamp_sec=round(frame_num/fps, 3))

            if result.pose_landmarks and len(result.pose_landmarks) > 0:
                lms = result.pose_landmarks[0]
                metric.landmarks_visible = True
                summary.analyzed_frames += 1

                l_elbow    = calc_angle(lm_xy(lms,LM.LEFT_SHOULDER), lm_xy(lms,LM.LEFT_ELBOW),    lm_xy(lms,LM.LEFT_WRIST))
                r_elbow    = calc_angle(lm_xy(lms,LM.RIGHT_SHOULDER),lm_xy(lms,LM.RIGHT_ELBOW),   lm_xy(lms,LM.RIGHT_WRIST))
                l_shoulder = calc_angle(lm_xy(lms,LM.LEFT_HIP),      lm_xy(lms,LM.LEFT_SHOULDER), lm_xy(lms,LM.LEFT_ELBOW))
                r_shoulder = calc_angle(lm_xy(lms,LM.RIGHT_HIP),     lm_xy(lms,LM.RIGHT_SHOULDER),lm_xy(lms,LM.RIGHT_ELBOW))
                head_angle = calc_angle(lm_xy(lms,LM.LEFT_EAR),      lm_xy(lms,LM.NOSE),          lm_xy(lms,LM.RIGHT_EAR))

                metric.left_elbow_angle     = round(l_elbow,    2)
                metric.right_elbow_angle    = round(r_elbow,    2)
                metric.left_shoulder_angle  = round(l_shoulder, 2)
                metric.right_shoulder_angle = round(r_shoulder, 2)
                metric.head_angle           = round(head_angle, 2)

                dy = lms[LM.LEFT_SHOULDER].y - lms[LM.RIGHT_SHOULDER].y
                dx = lms[LM.LEFT_SHOULDER].x - lms[LM.RIGHT_SHOULDER].x
                metric.body_roll = round(float(np.degrees(np.arctan2(dy, dx))), 2)

                l_elbows.append(l_elbow);   r_elbows.append(r_elbow)
                l_shoulders.append(l_shoulder); r_shoulders.append(r_shoulder)
                head_angles.append(head_angle)

                metric.kick_detected = kick_detector.update(lms[LM.LEFT_ANKLE].y, lms[LM.RIGHT_ANKLE].y)

                if writer:
                    for c in SKELETON_CONNECTIONS:
                        p1, p2 = lms[c[0]], lms[c[1]]
                        cv2.line(frame,
                                 (int(p1.x*width), int(p1.y*height)),
                                 (int(p2.x*width), int(p2.y*height)),
                                 (0,255,0), 2)
                    for idx in KEY_POINTS:
                        p = lms[idx]
                        cv2.circle(frame, (int(p.x*width), int(p.y*height)), 5, (255,0,0), -1)
                    _draw_overlay(frame, metric, width, height)

            summary.frame_metrics.append(metric)
            if writer:
                writer.write(frame)
            frame_num += 1

    cap.release()
    if writer:
        writer.release()

    if l_elbows:
        summary.left_arm_angle_avg  = round(float(np.mean(l_elbows)), 2)
        summary.right_arm_angle_avg = round(float(np.mean(r_elbows)), 2)
        summary.left_arm_angle_min  = round(float(np.min(l_elbows)),  2)
        summary.right_arm_angle_min = round(float(np.min(r_elbows)),  2)
        diff = abs(summary.left_arm_angle_avg - summary.right_arm_angle_avg)
        summary.arm_symmetry_score  = round(max(0, 100 - diff * 2), 2)

    summary.kick_count = kick_detector.kick_count
    if summary.duration_sec > 0:
        summary.kick_frequency_hz = round(summary.kick_count / summary.duration_sec, 3)

    if head_angles:
        summary.head_angle_avg      = round(float(np.mean(head_angles)), 2)
        ideal_range                 = abs(summary.head_angle_avg - 170)
        summary.head_rotation_score = round(max(0, 100 - ideal_range * 3), 2)

    summary.overall_score = round(
        summary.arm_symmetry_score  * 0.4 +
        summary.head_rotation_score * 0.3 +
        min(100, summary.kick_frequency_hz * 20) * 0.3, 2
    )
    return summary

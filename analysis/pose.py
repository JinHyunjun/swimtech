"""
SwimTech 포즈 분석 핵심 모듈 (v2 - 전처리 강화 + 랜드마크 보간)
MediaPipe Tasks API (0.10.x 이상 / Python 3.12 호환) 기준
감지율 개선:
  1. CLAHE 대비 강화 — 수중/흐린 환경 개선
  2. 칼만 필터 기반 랜드마크 보간 — 감지 실패 프레임 보완
  3. 촬영 환경별 전처리 파라미터 분기 (수중/수면/실내)
"""
import cv2
import numpy as np
import urllib.request
import os
from dataclasses import dataclass, field
from typing import Optional, List

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
        print("[SwimTech] MediaPipe 모델 다운로드 중... (최대 1분, 약 5MB)")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        print(f"[SwimTech] 모델 저장 완료: {MODEL_PATH}")


# ── 전처리 ────────────────────────────────────────────────────────────────────

# 촬영 환경별 CLAHE 파라미터
_PREPROCESS_PARAMS = {
    "underwater": {"clip_limit": 4.0, "tile_grid": (4, 4), "denoise": True,  "upscale": 1.5},
    "surface":    {"clip_limit": 2.5, "tile_grid": (8, 8), "denoise": True,  "upscale": 1.0},
    "indoor":     {"clip_limit": 1.5, "tile_grid": (8, 8), "denoise": False, "upscale": 1.0},
    "outdoor":    {"clip_limit": 2.0, "tile_grid": (8, 8), "denoise": False, "upscale": 1.0},
    "default":    {"clip_limit": 2.0, "tile_grid": (8, 8), "denoise": True,  "upscale": 1.0},
}

# SwimTech 촬영환경 선택값 → 전처리 파라미터 매핑
_ENV_MAP = {
    "수중":   "underwater",
    "수면위": "surface",
    "실내":   "indoor",
    "실외":   "outdoor",
}


def preprocess_frame(frame: np.ndarray, env: str = "default") -> np.ndarray:
    """
    촬영 환경에 맞는 전처리 적용
    - CLAHE: 대비 강화 (수중 흐림, 역광 개선)
    - 노이즈 제거: 수중 영상 노이즈 감소
    - 업스케일: 원거리 촬영 해상도 보정

    Args:
        frame: BGR 프레임
        env: 촬영 환경 ('수중', '수면위', '실내', '실외', 'default')
    Returns:
        전처리된 BGR 프레임
    """
    key = _ENV_MAP.get(env, env if env in _PREPROCESS_PARAMS else "default")
    p = _PREPROCESS_PARAMS[key]

    # 1. 업스케일 (수중 영상 원거리 보정)
    if p["upscale"] != 1.0:
        h, w = frame.shape[:2]
        frame = cv2.resize(
            frame,
            (int(w * p["upscale"]), int(h * p["upscale"])),
            interpolation=cv2.INTER_CUBIC
        )

    # 2. 노이즈 제거 (수중 영상)
    if p["denoise"]:
        frame = cv2.fastNlMeansDenoisingColored(frame, None, 6, 6, 7, 21)

    # 3. CLAHE 대비 강화 (LAB 색공간 L채널에만 적용)
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(
        clipLimit=p["clip_limit"],
        tileGridSize=p["tile_grid"]
    )
    l = clahe.apply(l)
    lab = cv2.merge([l, a, b])
    frame = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    return frame


# ── 랜드마크 보간 (칼만 필터) ──────────────────────────────────────────────────

class LandmarkInterpolator:
    """
    칼만 필터 기반 랜드마크 보간기.
    MediaPipe 감지 실패 프레임에서 이전/예측값으로 좌표를 보완.

    - 연속 max_missing_frames 이상 감지 실패 시 보간 포기 (None 반환)
    - 감지 성공 시 칼만 필터 업데이트
    - 감지 실패 시 칼만 예측값 반환
    """

    MAX_MISSING = 10  # 연속 감지 실패 허용 최대 프레임 수

    def __init__(self, n_landmarks: int = 33):
        self.n = n_landmarks
        # 각 랜드마크별 (x, y) 칼만 필터
        self._filters: List[Optional[cv2.KalmanFilter]] = [None] * n_landmarks
        self._missing_count = 0
        self._last_landmarks = None

    def _make_kalman(self) -> cv2.KalmanFilter:
        """2D 등속도 모델 칼만 필터 생성 (state: x, y, vx, vy)"""
        kf = cv2.KalmanFilter(4, 2)
        kf.measurementMatrix = np.array(
            [[1, 0, 0, 0],
             [0, 1, 0, 0]], np.float32
        )
        kf.transitionMatrix = np.array(
            [[1, 0, 1, 0],
             [0, 1, 0, 1],
             [0, 0, 1, 0],
             [0, 0, 0, 1]], np.float32
        )
        kf.processNoiseCov    = np.eye(4, dtype=np.float32) * 1e-3
        kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 1e-2
        kf.errorCovPost       = np.eye(4, dtype=np.float32)
        return kf

    def update(self, landmarks):
        """
        landmarks: MediaPipe pose_landmarks[0] 또는 None (감지 실패)
        returns: 보간된 landmarks 유사 구조 (list of SimpleNamespace) 또는 None
        """
        if landmarks is not None:
            self._missing_count = 0
            self._last_landmarks = landmarks

            # 칼만 필터 업데이트
            for i, lm in enumerate(landmarks):
                if self._filters[i] is None:
                    self._filters[i] = self._make_kalman()
                    # 초기 상태 설정
                    self._filters[i].statePre = np.array(
                        [[lm.x], [lm.y], [0.0], [0.0]], np.float32
                    )
                    self._filters[i].statePost = self._filters[i].statePre.copy()

                meas = np.array([[lm.x], [lm.y]], np.float32)
                self._filters[i].predict()
                self._filters[i].correct(meas)

            return landmarks

        else:
            # 감지 실패
            self._missing_count += 1

            if self._missing_count > self.MAX_MISSING or self._last_landmarks is None:
                return None  # 보간 포기

            # 칼만 예측값으로 보간
            interpolated = []
            for i, kf in enumerate(self._filters):
                if kf is None:
                    interpolated.append(self._last_landmarks[i])
                    continue
                pred = kf.predict()
                # SimpleNamespace로 x, y 속성 모방
                from types import SimpleNamespace
                lm_interp = SimpleNamespace(
                    x=float(pred[0]),
                    y=float(pred[1]),
                    z=self._last_landmarks[i].z,
                    visibility=self._last_landmarks[i].visibility * 0.8  # 보간 신뢰도 감소
                )
                interpolated.append(lm_interp)

            return interpolated


# ── 기존 코드 (변경 없음) ────────────────────────────────────────────────────

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
    interpolated: bool = False  # 보간 프레임 여부 추가


@dataclass
class AnalysisSummary:
    total_frames: int = 0
    analyzed_frames: int = 0
    interpolated_frames: int = 0  # 보간으로 복구된 프레임 수 추가
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
    """
    영법별 발차기 감지기 — 캘리브레이션 없이 rolling std 기반 동적 threshold.
    최근 60프레임 발목 Y 표준편차 * 0.5 를 threshold로 사용함.
    수영 환경에 자동 적응. 각 발 독립 쿨다운 5프레임.

    - freestyle / backstroke / unknown : 각 발 독립 감지 (쿨다운 5프레임)
    - butterfly                        : 양발 평균 Y, 아래→위 전환 (쿨다운 8프레임)
    - breaststroke                     : 양발 평균 Y, 모임→벌어진 패턴 (쿨다운 12프레임)
    """

    _WINDOW = 60

    _COOLDOWN = {
        "freestyle":    5,
        "backstroke":   5,
        "butterfly":    8,
        "breaststroke": 12,
        "unknown":      5,
    }

    def __init__(self, stroke_type: str = "unknown"):
        self.stroke_type = stroke_type
        self.kick_count  = 0
        self._y_buf: list = []

        self._prev_l: Optional[float] = None
        self._prev_r: Optional[float] = None
        self._dir_l:  int = 0
        self._dir_r:  int = 0
        self._cool_l: int = 0
        self._cool_r: int = 0

        self._prev_avg: Optional[float] = None
        self._dir_avg:  int = 0
        self._cool_avg: int = 0

        self._base_cd = self._COOLDOWN.get(stroke_type, 5)

    def _threshold(self) -> float:
        if len(self._y_buf) < 10:
            return 0.015
        std = float(np.std(self._y_buf[-self._WINDOW:]))
        return float(np.clip(std * 0.5, 0.008, 0.04))

    def update(self, l_y: float, r_y: float) -> bool:
        self._y_buf.append(l_y)
        self._y_buf.append(r_y)
        if len(self._y_buf) > self._WINDOW * 4:
            del self._y_buf[:self._WINDOW * 2]

        thr    = self._threshold()
        kicked = False

        if self.stroke_type == "butterfly":
            if self._cool_avg > 0:
                self._cool_avg -= 1
            avg = (l_y + r_y) / 2
            if self._prev_avg is not None:
                delta = avg - self._prev_avg
                if delta > thr:
                    self._dir_avg = 1
                elif delta < -thr:
                    if self._dir_avg == 1 and self._cool_avg == 0:
                        self.kick_count += 1
                        self._cool_avg = self._base_cd
                        kicked = True
                    self._dir_avg = -1
            self._prev_avg = avg

        elif self.stroke_type == "breaststroke":
            if self._cool_avg > 0:
                self._cool_avg -= 1
            avg = (l_y + r_y) / 2
            if self._prev_avg is not None:
                delta = avg - self._prev_avg
                if delta < -thr:
                    self._dir_avg = -1
                elif delta > thr:
                    if self._dir_avg == -1 and self._cool_avg == 0:
                        self.kick_count += 1
                        self._cool_avg = self._base_cd
                        kicked = True
                    self._dir_avg = 1
            self._prev_avg = avg

        else:
            if self._cool_l > 0:
                self._cool_l -= 1
            if self._prev_l is not None:
                delta_l = l_y - self._prev_l
                if delta_l > thr:
                    self._dir_l = 1
                elif delta_l < -thr:
                    if self._dir_l == 1 and self._cool_l == 0:
                        self.kick_count += 1
                        self._cool_l = self._base_cd
                        kicked = True
                    self._dir_l = -1
            self._prev_l = l_y

            if self._cool_r > 0:
                self._cool_r -= 1
            if self._prev_r is not None:
                delta_r = r_y - self._prev_r
                if delta_r > thr:
                    self._dir_r = 1
                elif delta_r < -thr:
                    if self._dir_r == 1 and self._cool_r == 0:
                        self.kick_count += 1
                        self._cool_r = self._base_cd
                        kicked = True
                    self._dir_r = -1
            self._prev_r = r_y

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
    if metric.interpolated:
        cv2.putText(frame, "INTERP", (w-160, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100,200,255), 2)
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


def analyze_video(
    video_path: str,
    output_path: Optional[str] = None,
    env: str = "default",
    stroke_type: str = "freestyle"
) -> AnalysisSummary:
    """
    수영 영상 분석 메인 함수

    Args:
        video_path:  입력 영상 경로
        output_path: 오버레이 영상 저장 경로 (None이면 저장 안 함)
        env:         촬영 환경 ('수중', '수면위', '실내', '실외', 'default')
        stroke_type: 영법 ('freestyle', 'backstroke', 'breaststroke', 'butterfly')
    """
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

    kick_detector = KickDetector(stroke_type=stroke_type)
    interpolator  = LandmarkInterpolator(n_landmarks=33)
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

            # ── 전처리 적용 ──
            processed = preprocess_frame(frame, env=env)

            rgb      = cv2.cvtColor(processed, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result   = landmarker.detect_for_video(mp_image, timestamp_ms)

            # ── 랜드마크 보간 ──
            raw_lms = result.pose_landmarks[0] if (
                result.pose_landmarks and len(result.pose_landmarks) > 0
            ) else None
            lms = interpolator.update(raw_lms)
            is_interpolated = (raw_lms is None and lms is not None)

            metric = FrameMetric(
                frame_number=frame_num,
                timestamp_sec=round(frame_num / fps, 3),
                interpolated=is_interpolated
            )

            if lms is not None:
                metric.landmarks_visible = True
                summary.analyzed_frames += 1
                if is_interpolated:
                    summary.interpolated_frames += 1

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

                l_elbows.append(l_elbow);    r_elbows.append(r_elbow)
                l_shoulders.append(l_shoulder); r_shoulders.append(r_shoulder)
                head_angles.append(head_angle)

                metric.kick_detected = kick_detector.update(
                    lms[LM.LEFT_ANKLE].y, lms[LM.RIGHT_ANKLE].y
                )

                if writer:
                    draw_frame = frame.copy()
                    for c in SKELETON_CONNECTIONS:
                        p1, p2 = lms[c[0]], lms[c[1]]
                        color = (100, 200, 255) if is_interpolated else (0, 255, 0)
                        cv2.line(draw_frame,
                                 (int(p1.x*width), int(p1.y*height)),
                                 (int(p2.x*width), int(p2.y*height)),
                                 color, 2)
                    for idx in KEY_POINTS:
                        p = lms[idx]
                        cv2.circle(draw_frame, (int(p.x*width), int(p.y*height)), 5, (255,0,0), -1)
                    _draw_overlay(draw_frame, metric, width, height)
                    writer.write(draw_frame)
            else:
                if writer:
                    writer.write(frame)

            summary.frame_metrics.append(metric)
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

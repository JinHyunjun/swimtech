"""
SwimTech — 영법 분류 + 피드백 모듈 (3-Track 버전)

Track 1. Competition  → 올림픽/세계선수권 기반 대회 모델
Track 2. Tutorial     → 강의 영상 기반 교습 모델
Track 3. Start & Turn → 스타트/턴 전문 모델

사용자가 선택한 목적(purpose)과 촬영환경(context)에 따라
적절한 트랙의 모델을 자동 선택합니다.
"""
import os
import numpy as np
from dataclasses import dataclass
from typing import Optional

MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")


@dataclass
class FrameMetric:
    frame_number: int
    timestamp_sec: float
    left_elbow_angle: Optional[float] = None
    right_elbow_angle: Optional[float] = None
    left_shoulder_angle: Optional[float] = None
    right_shoulder_angle: Optional[float] = None
    head_angle: Optional[float] = None
    kick_detected: bool = False
    landmarks_visible: bool = False


@dataclass
class StrokeClassification:
    stroke_type: str
    confidence: float
    reason: str


# ── 트랙 선택 로직 ─────────────────────────────────────

def select_track(purpose: str = "", context: str = "") -> str:
    """
    사용자 선택에 따라 적절한 트랙 반환
    - competition / record → Track 1 (Competition)
    - start/turn 관련     → Track 3 (Start & Turn)
    - 그 외               → Track 2 (Tutorial)
    """
    if purpose in ("competition", "record") or context == "competition":
        return "competition"
    if purpose in ("start", "turn") or context in ("start", "turn"):
        return "start_turn"
    return "tutorial"


# ── ML 모델 로드 ───────────────────────────────────────

def _load_model(track: str):
    try:
        import joblib, json
        model_path   = os.path.join(MODEL_DIR, f"model_{track}.joblib")
        encoder_path = os.path.join(MODEL_DIR, f"encoder_{track}.joblib")
        info_path    = os.path.join(MODEL_DIR, f"info_{track}.json")

        if not os.path.exists(model_path):
            return None, None, None

        model   = joblib.load(model_path)
        encoder = joblib.load(encoder_path)
        with open(info_path) as f:
            info = json.load(f)
        return model, encoder, info
    except Exception:
        return None, None, None


# 트랙별 모델 캐시
_models = {}

def _get_model(track: str):
    if track not in _models:
        _models[track] = _load_model(track)
    return _models[track]


FEATURE_COLS = [
    "l_elbow_mean",   "l_elbow_std",   "l_elbow_min",
    "r_elbow_mean",   "r_elbow_std",   "r_elbow_min",
    "l_shoulder_mean","r_shoulder_mean",
    "head_angle_mean","hip_angle_mean",
    "body_roll_mean", "hip_roll_mean",
    "elbow_symmetry_mean","shoulder_symmetry_mean",
    "kick_frequency", "kick_ratio",
    "entry_angle_mean","streamline_width_mean",
]


# ── ML 모델 기반 분류 ──────────────────────────────────

def classify_stroke_ml(frame_metrics: list, purpose: str = "", context: str = "") -> StrokeClassification:
    """
    목적/환경에 따라 적절한 트랙 모델로 분류
    모델 없으면 규칙 기반 fallback
    """
    track = select_track(purpose, context)
    model, encoder, info = _get_model(track)

    if model is None:
        return classify_stroke(frame_metrics)   # 규칙 기반 fallback

    valid = [m for m in frame_metrics if m.landmarks_visible]
    if len(valid) < 10:
        return StrokeClassification("unknown", 30.0, "랜드마크 부족")

    l_elbows   = [m.left_elbow_angle  for m in valid if m.left_elbow_angle]
    r_elbows   = [m.right_elbow_angle for m in valid if m.right_elbow_angle]
    heads      = [m.head_angle        for m in valid if m.head_angle]
    kicks      = sum(1 for m in valid if m.kick_detected)
    dur        = valid[-1].timestamp_sec if valid else 1

    feat = {
        "l_elbow_mean":           np.mean(l_elbows) if l_elbows else 0,
        "l_elbow_std":            np.std(l_elbows)  if l_elbows else 0,
        "l_elbow_min":            np.min(l_elbows)  if l_elbows else 0,
        "r_elbow_mean":           np.mean(r_elbows) if r_elbows else 0,
        "r_elbow_std":            np.std(r_elbows)  if r_elbows else 0,
        "r_elbow_min":            np.min(r_elbows)  if r_elbows else 0,
        "l_shoulder_mean":        0,
        "r_shoulder_mean":        0,
        "head_angle_mean":        np.mean(heads) if heads else 0,
        "hip_angle_mean":         0,
        "body_roll_mean":         0,
        "hip_roll_mean":          0,
        "elbow_symmetry_mean":    abs(np.mean(l_elbows)-np.mean(r_elbows)) if l_elbows and r_elbows else 0,
        "shoulder_symmetry_mean": 0,
        "kick_frequency":         kicks / dur if dur > 0 else 0,
        "kick_ratio":             kicks / len(valid) if valid else 0,
        "entry_angle_mean":       0,
        "streamline_width_mean":  0,
    }

    X      = np.array([[feat.get(c, 0) for c in FEATURE_COLS]])
    pred   = model.predict(X)[0]
    proba  = model.predict_proba(X)[0]
    stroke = encoder.inverse_transform([pred])[0]
    conf   = round(float(proba.max()) * 100, 1)

    track_desc = {"competition": "대회 모델", "tutorial": "교습 모델", "start_turn": "스타트/턴 모델"}
    return StrokeClassification(stroke, conf, f"{track_desc.get(track, '')} 예측")


# ── 규칙 기반 분류 (fallback) ──────────────────────────

def classify_stroke(frame_metrics: list) -> StrokeClassification:
    valid = [m for m in frame_metrics if m.landmarks_visible]
    if len(valid) < 10:
        return StrokeClassification("unknown", 30.0, "감지된 랜드마크 부족")

    l_elbows  = [m.left_elbow_angle  for m in valid if m.left_elbow_angle]
    r_elbows  = [m.right_elbow_angle for m in valid if m.right_elbow_angle]
    l_shoulders = [m.left_shoulder_angle  for m in valid if m.left_shoulder_angle]
    r_shoulders = [m.right_shoulder_angle for m in valid if m.right_shoulder_angle]

    if not l_elbows:
        return StrokeClassification("unknown", 20.0, "팔꿈치 각도 감지 불가")

    l_elbow_avg  = np.mean(l_elbows)
    r_elbow_avg  = np.mean(r_elbows)
    l_shoulder_avg = np.mean(l_shoulders) if l_shoulders else 90
    r_shoulder_avg = np.mean(r_shoulders) if r_shoulders else 90
    elbow_diff    = abs(l_elbow_avg - r_elbow_avg)
    shoulder_diff = abs(l_shoulder_avg - r_shoulder_avg)
    kick_ratio = sum(1 for m in valid if m.kick_detected) / len(valid)

    if l_shoulder_avg > 150 and r_shoulder_avg > 150 and shoulder_diff < 30:
        return StrokeClassification("backstroke",   72.0, f"어깨 각도 {l_shoulder_avg:.0f}°/{r_shoulder_avg:.0f}°")
    if elbow_diff < 10 and shoulder_diff < 15 and kick_ratio < 0.05:
        return StrokeClassification("breaststroke", 68.0, f"좌우 대칭 {elbow_diff:.1f}° + 낮은 발차기")
    if elbow_diff < 20 and kick_ratio > 0.15:
        return StrokeClassification("butterfly",    65.0, f"대칭 팔 + 높은 발차기 {kick_ratio:.2f}")
    return StrokeClassification("freestyle",        60.0, f"교차 팔 동작 차이 {elbow_diff:.1f}°")


# ── 영법별 피드백 기준값 ───────────────────────────────

STROKE_STANDARDS = {
    "freestyle": {
        "elbow_angle_ideal": (80, 110), "head_angle_ideal": (160, 180),
        "kick_freq_ideal": (1.5, 3.0),
        "drills": [
            "catch-up 드릴: 한 팔이 앞에서 기다리는 동안 반대 팔 스트로크",
            "핑거-드래그 드릴: 손가락을 수면에 끌며 팔 회전 연습",
            "6-1-6 킥 드릴: 6번 킥 후 1번 스트로크 반복",
        ],
        "youtube_queries": ["freestyle swimming technique drill", "자유형 팔 동작 교정 드릴"],
    },
    "backstroke": {
        "elbow_angle_ideal": (90, 130), "head_angle_ideal": (155, 175),
        "kick_freq_ideal": (1.5, 3.0),
        "drills": ["단팔 배영 드릴", "플래그 드릴"],
        "youtube_queries": ["backstroke technique drill", "배영 교정 드릴"],
    },
    "breaststroke": {
        "elbow_angle_ideal": (70, 100), "head_angle_ideal": (150, 170),
        "kick_freq_ideal": (0.5, 1.5),
        "drills": ["2킥 1풀 드릴", "손-머리 드릴"],
        "youtube_queries": ["breaststroke technique drill", "평영 발차기 타이밍 드릴"],
    },
    "butterfly": {
        "elbow_angle_ideal": (80, 115), "head_angle_ideal": (155, 175),
        "kick_freq_ideal": (1.0, 2.5),
        "drills": ["돌핀킥 드릴", "단팔 접영 드릴"],
        "youtube_queries": ["butterfly stroke drill", "접영 돌핀킥 드릴"],
    },
    # 스타트/턴 피드백
    "start": {
        "elbow_angle_ideal": (160, 180), "head_angle_ideal": (155, 175),
        "kick_freq_ideal": (0, 1),
        "drills": ["블록 스타트 반응 훈련", "입수 각도 교정 드릴", "스트림라인 자세 훈련"],
        "youtube_queries": ["swimming start technique tutorial", "수영 스타트 교정"],
    },
    "flip_turn": {
        "elbow_angle_ideal": (80, 110), "head_angle_ideal": (150, 170),
        "kick_freq_ideal": (0.5, 2.0),
        "drills": ["플립턴 연속 드릴", "벽 킥 거리 훈련", "돌핀킥 스트림라인 연습"],
        "youtube_queries": ["flip turn tutorial", "자유형 플립턴 교정"],
    },
    "touch_turn": {
        "elbow_angle_ideal": (70, 100), "head_angle_ideal": (150, 170),
        "kick_freq_ideal": (0.3, 1.0),
        "drills": ["터치 타이밍 드릴", "두손 터치 교정 훈련"],
        "youtube_queries": ["breaststroke butterfly turn tutorial", "평영 접영 턴 교정"],
    },
}


def generate_rule_based_feedback(summary, stroke_type: str) -> dict:
    std = STROKE_STANDARDS.get(stroke_type, STROKE_STANDARDS["freestyle"])
    lines = []

    ideal_min, ideal_max = std["elbow_angle_ideal"]
    l_avg = getattr(summary, "left_arm_angle_avg",  0) or 0
    r_avg = getattr(summary, "right_arm_angle_avg", 0) or 0

    if l_avg and l_avg < ideal_min:
        lines.append(f"왼팔 팔꿈치 각도({l_avg:.0f}°)가 너무 작습니다. 팔을 더 펴주세요. (이상: {ideal_min}~{ideal_max}°)")
    elif l_avg and l_avg > ideal_max:
        lines.append(f"왼팔 팔꿈치 각도({l_avg:.0f}°)가 너무 큽니다. 팔꿈치를 더 구부려 당겨주세요.")
    if r_avg and r_avg < ideal_min:
        lines.append(f"오른팔 팔꿈치 각도({r_avg:.0f}°)가 너무 작습니다.")
    elif r_avg and r_avg > ideal_max:
        lines.append(f"오른팔 팔꿈치 각도({r_avg:.0f}°)가 너무 큽니다.")

    sym = getattr(summary, "arm_symmetry_score", 100) or 100
    if sym < 70:
        lines.append(f"좌우 팔 각도 차이({abs(l_avg-r_avg):.0f}°)가 큽니다. 대칭 동작을 연습하세요.")

    freq_min, freq_max = std["kick_freq_ideal"]
    freq = getattr(summary, "kick_frequency_hz", 0) or 0
    if freq and freq < freq_min:
        lines.append(f"발차기 빈도({freq:.1f}회/초)가 낮습니다.")
    elif freq and freq > freq_max:
        lines.append(f"발차기 빈도({freq:.1f}회/초)가 높습니다. 체력 낭비를 줄이세요.")

    head_min, head_max = std["head_angle_ideal"]
    head = getattr(summary, "head_angle_avg", 170) or 170
    if head < head_min:
        lines.append("머리가 너무 들려 있습니다. 시선을 아래로 향해 수평 자세를 유지하세요.")

    if not lines:
        lines.append("전반적으로 좋은 자세입니다! 현재 패턴을 유지하세요.")

    return {
        "feedback": "\n".join(f"• {l}" for l in lines),
        "drills":   std["drills"],
        "youtube_queries": std["youtube_queries"],
    }

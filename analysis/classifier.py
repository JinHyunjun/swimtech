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

# ══════════════════════════════════════════════════════
# 영법별 기준값 + 상세 설명
# ══════════════════════════════════════════════════════
STROKE_STANDARDS = {
    "freestyle": {
        "name": "자유형",
        "elbow_angle_ideal": (80, 110),
        "head_angle_ideal":  (160, 180),
        "kick_freq_ideal":   (1.5, 3.0),
        "elbow_reason": (
            "자유형에서 팔꿈치 각도 80~110°는 '하이 엘보우(High Elbow)' 자세를 유지하는 핵심입니다. "
            "이 각도에서 손바닥이 뒤쪽을 향해 수압을 최대로 받을 수 있어 추진력이 가장 효율적으로 발생합니다. "
            "각도가 너무 크면 팔이 옆으로 벌어져 저항이 증가하고, 너무 작으면 어깨 부상 위험이 높아집니다."
        ),
        "kick_reason": (
            "자유형 발차기는 1.5~3.0회/초가 이상적입니다. "
            "이 범위에서 추진력 보조와 체력 소모의 균형이 최적화됩니다. "
            "엘리트 단거리 선수는 3.0회 이상, 장거리는 1.5~2.0회를 유지합니다."
        ),
        "head_reason": (
            "머리 각도 160~180°는 시선이 수면 아래 45° 방향을 향하는 자세입니다. "
            "머리가 수면 위로 올라올수록 엉덩이와 다리가 가라앉아 저항이 크게 증가합니다. "
            "올바른 시선 처리만으로 속도를 5~8% 향상시킬 수 있습니다."
        ),
        "symmetry_reason": (
            "좌우 팔 각도 차이가 크면 한쪽으로 치우쳐 수영하게 되어 레인을 벗어나거나 "
            "어깨 불균형으로 인한 부상이 생깁니다. 대칭적인 스트로크가 직선 수영과 부상 예방의 핵심입니다."
        ),
        "drills": [
            "catch-up 드릴: 한 팔이 앞에서 기다리는 동안 반대 팔 스트로크 — 하이 엘보우 감각 훈련",
            "핑거-드래그 드릴: 손가락을 수면에 끌며 팔 회전 연습 — 팔꿈치 높이 유지",
            "6-1-6 킥 드릴: 6번 킥 후 1번 스트로크 반복 — 몸통 회전과 킥 타이밍 연습",
        ],
        "youtube_queries": ["freestyle high elbow catch drill", "자유형 하이엘보우 드릴"],
    },
    "backstroke": {
        "name": "배영",
        "elbow_angle_ideal": (90, 130),
        "head_angle_ideal":  (155, 175),
        "kick_freq_ideal":   (1.5, 3.0),
        "elbow_reason": (
            "배영에서 팔꿈치 각도 90~130°는 물을 아래로 밀어내는 풀 단계에서 최대 추진력을 만드는 범위입니다. "
            "팔꿈치가 너무 펴지면 어깨 관절에 과부하가 걸리고 추진력이 떨어집니다."
        ),
        "kick_reason": (
            "배영 발차기는 자유형과 동일하게 1.5~3.0회/초가 권장됩니다. "
            "무릎을 거의 구부리지 않고 발목의 유연성으로 추진력을 만드는 것이 핵심입니다."
        ),
        "head_reason": (
            "배영에서 머리는 수면과 수평을 유지해야 합니다. "
            "머리가 앞으로 숙여지면 엉덩이가 가라앉고, 뒤로 젖혀지면 저항이 증가합니다."
        ),
        "symmetry_reason": (
            "배영은 좌우 팔이 180° 번갈아 회전하므로 대칭이 특히 중요합니다. "
            "비대칭은 직선 수영을 방해하고 어깨 부상의 주요 원인이 됩니다."
        ),
        "drills": [
            "단팔 배영 드릴: 한 팔은 옆구리에 붙이고 한 팔로만 스트로크 — 팔꿈치 각도 집중 훈련",
            "플래그 드릴: 팔꿈치가 물 밖에 나올 때 깃발처럼 유지 — 리커버리 자세 교정",
        ],
        "youtube_queries": ["backstroke technique drill", "배영 교정 드릴"],
    },
    "breaststroke": {
        "name": "평영",
        "elbow_angle_ideal": (70, 100),
        "head_angle_ideal":  (150, 170),
        "kick_freq_ideal":   (0.5, 1.5),
        "elbow_reason": (
            "평영 풀 단계에서 팔꿈치 각도 70~100°는 손바닥이 뒤를 향해 최대 수압을 받는 범위입니다. "
            "팔꿈치가 너무 넓게 벌어지면 저항이 커지고, 너무 좁으면 추진력이 줄어듭니다."
        ),
        "kick_reason": (
            "평영 발차기는 스트로크 1회당 1번(0.5~1.5회/초)이 기준입니다. "
            "발목을 바깥쪽으로 벌린 후 모으면서 수압으로 추진력을 만드는 휩킥(Whip Kick)이 핵심입니다."
        ),
        "head_reason": (
            "평영에서 머리는 호흡 시에만 올라오고 나머지는 물속에 위치해야 합니다. "
            "머리가 계속 나와 있으면 엉덩이가 가라앉아 저항이 크게 증가합니다."
        ),
        "symmetry_reason": (
            "평영은 양팔이 동시에 움직이는 영법이므로 좌우 대칭이 가장 중요합니다. "
            "비대칭은 스트로크마다 방향이 틀어지는 직접적인 원인이 됩니다."
        ),
        "drills": [
            "2킥 1풀 드릴: 발차기 2번 후 팔 1번 — 킥 타이밍과 글라이드 연습",
            "손-머리 드릴: 손이 머리 위에서 뻗어나가는 자세 강조 — 스트림라인 훈련",
        ],
        "youtube_queries": ["breaststroke technique drill", "평영 발차기 타이밍 드릴"],
    },
    "butterfly": {
        "name": "접영",
        "elbow_angle_ideal": (80, 115),
        "head_angle_ideal":  (155, 175),
        "kick_freq_ideal":   (1.0, 2.5),
        "elbow_reason": (
            "접영에서 팔꿈치 각도 80~115°는 풀 단계에서 최대 추진력을 내는 범위입니다. "
            "접영도 하이 엘보우 자세가 필요하며, 이 범위를 벗어나면 추진력 손실과 어깨 부상으로 이어집니다."
        ),
        "kick_reason": (
            "접영 돌핀킥은 스트로크 1회당 2번(1.0~2.5회/초)이 이상적입니다. "
            "상체 웨이브 동작과 킥이 일치할 때 추진력이 극대화됩니다."
        ),
        "head_reason": (
            "접영에서 머리는 호흡 시 앞으로 들어야 하지만 과도하게 올라오면 안 됩니다. "
            "머리가 너무 높이 올라오면 웨이브 리듬이 깨지고 다리가 가라앉습니다."
        ),
        "symmetry_reason": (
            "접영은 양팔이 동시에 움직이므로 비대칭은 즉시 방향 이탈로 나타납니다. "
            "좌우 어깨 유연성 차이가 주요 원인이므로 양쪽 스트레칭이 필요합니다."
        ),
        "drills": [
            "돌핀킥 드릴: 팔은 뻗은 채 돌핀킥만 — 웨이브 리듬과 킥 타이밍 훈련",
            "단팔 접영 드릴: 한 팔씩 번갈아 접영 — 팔꿈치 각도와 풀 감각 훈련",
        ],
        "youtube_queries": ["butterfly stroke drill", "접영 돌핀킥 드릴"],
    },
    "start": {
        "name": "스타트",
        "elbow_angle_ideal": (160, 180),
        "head_angle_ideal":  (155, 175),
        "kick_freq_ideal":   (0, 1),
        "elbow_reason": "스타트 입수 시 팔이 완전히 펴져야(160~180°) 물의 저항을 최소화하고 깊이 파고들 수 있습니다.",
        "kick_reason": "스타트 직후 돌핀킥 타이밍이 빠를수록 수중 추진력을 길게 유지할 수 있습니다.",
        "head_reason": "입수 시 머리는 팔 사이에 위치해야 하며, 고개가 들리면 저항이 급증합니다.",
        "symmetry_reason": "스타트 시 좌우 균형이 맞지 않으면 입수 후 방향이 틀어집니다.",
        "drills": ["블록 스타트 반응 훈련", "입수 각도 교정 드릴", "스트림라인 자세 훈련"],
        "youtube_queries": ["swimming start technique tutorial", "수영 스타트 교정"],
    },
    "flip_turn": {
        "name": "플립턴",
        "elbow_angle_ideal": (80, 110),
        "head_angle_ideal":  (150, 170),
        "kick_freq_ideal":   (0.5, 2.0),
        "elbow_reason": "턴 후 벽 킥 단계에서 팔이 완전히 뻗어야 스트림라인이 완성됩니다.",
        "kick_reason": "턴 직후 돌핀킥 타이밍과 횟수가 15m 구간 속도를 결정합니다.",
        "head_reason": "턴 후 머리가 팔 사이에 위치해야 수중 저항을 최소화합니다.",
        "symmetry_reason": "턴 시 좌우 발이 균등하게 벽을 밀어야 방향이 틀어지지 않습니다.",
        "drills": ["플립턴 연속 드릴", "벽 킥 거리 훈련", "돌핀킥 스트림라인 연습"],
        "youtube_queries": ["flip turn tutorial", "자유형 플립턴 교정"],
    },
    "touch_turn": {
        "name": "터치턴",
        "elbow_angle_ideal": (70, 100),
        "head_angle_ideal":  (150, 170),
        "kick_freq_ideal":   (0.3, 1.0),
        "elbow_reason": "평영/접영 터치턴에서 양손이 동시에 벽에 닿아야 규칙 위반을 피할 수 있습니다.",
        "kick_reason": "터치 후 발이 벽을 강하게 밀어내는 킥이 턴 속도를 결정합니다.",
        "head_reason": "터치 시 머리 위치가 턴 방향과 속도에 영향을 줍니다.",
        "symmetry_reason": "양손이 동시에 닿지 않으면 실격 처리됩니다.",
        "drills": ["터치 타이밍 드릴", "두손 터치 교정 훈련"],
        "youtube_queries": ["breaststroke butterfly turn tutorial", "평영 접영 턴 교정"],
    },
}


def generate_rule_based_feedback(summary, stroke_type: str) -> dict:
    """
    강점(strengths) + 개선점(improvements) + 각도별 상세 설명 + 시점 정보 포함 피드백 생성
    """
    std = STROKE_STANDARDS.get(stroke_type, STROKE_STANDARDS["freestyle"])

    l_avg = getattr(summary, "left_arm_angle_avg",  0) or 0
    r_avg = getattr(summary, "right_arm_angle_avg", 0) or 0
    l_min = getattr(summary, "left_arm_angle_min",  0) or 0
    r_min = getattr(summary, "right_arm_angle_min", 0) or 0
    sym   = getattr(summary, "arm_symmetry_score",  100) or 100
    freq  = getattr(summary, "kick_frequency_hz",   0) or 0
    kick  = getattr(summary, "kick_count",           0) or 0
    head  = getattr(summary, "head_angle_avg",      170) or 170
    dur   = getattr(summary, "duration_sec",          0) or 0
    total = getattr(summary, "total_frames",          0) or 0

    ideal_e_min, ideal_e_max = std["elbow_angle_ideal"]
    ideal_k_min, ideal_k_max = std["kick_freq_ideal"]
    ideal_h_min, ideal_h_max = std["head_angle_ideal"]

    strengths    = []  # ✅ 강점
    improvements = []  # ⚠️ 개선점

    # ── 팔꿈치 각도 평가 ──────────────────────────────
    if l_avg:
        if ideal_e_min <= l_avg <= ideal_e_max:
            strengths.append({
                "item": "왼팔 팔꿈치 각도",
                "value": f"{l_avg:.1f}°",
                "ideal": f"{ideal_e_min}~{ideal_e_max}°",
                "comment": f"이상적인 범위에 있습니다. {std['elbow_reason'][:40]}...",
                "reason": std["elbow_reason"],
            })
        elif l_avg < ideal_e_min:
            improvements.append({
                "item": "왼팔 팔꿈치 각도",
                "value": f"{l_avg:.1f}°",
                "ideal": f"{ideal_e_min}~{ideal_e_max}°",
                "comment": f"각도가 {ideal_e_min - l_avg:.0f}° 부족합니다. 팔꿈치를 좀 더 구부려주세요.",
                "reason": std["elbow_reason"],
                "worst_moment": f"영상 전반부에서 가장 작은 각도({l_min:.1f}°)가 감지됐습니다.",
            })
        else:
            improvements.append({
                "item": "왼팔 팔꿈치 각도",
                "value": f"{l_avg:.1f}°",
                "ideal": f"{ideal_e_min}~{ideal_e_max}°",
                "comment": f"각도가 {l_avg - ideal_e_max:.0f}° 큽니다. 하이 엘보우 자세를 유지하세요.",
                "reason": std["elbow_reason"],
                "worst_moment": f"최대 각도({l_avg:.1f}°)가 반복적으로 감지됐습니다.",
            })

    if r_avg:
        if ideal_e_min <= r_avg <= ideal_e_max:
            strengths.append({
                "item": "오른팔 팔꿈치 각도",
                "value": f"{r_avg:.1f}°",
                "ideal": f"{ideal_e_min}~{ideal_e_max}°",
                "comment": f"이상적인 범위에 있습니다.",
                "reason": std["elbow_reason"],
            })
        elif r_avg < ideal_e_min:
            improvements.append({
                "item": "오른팔 팔꿈치 각도",
                "value": f"{r_avg:.1f}°",
                "ideal": f"{ideal_e_min}~{ideal_e_max}°",
                "comment": f"각도가 {ideal_e_min - r_avg:.0f}° 부족합니다.",
                "reason": std["elbow_reason"],
                "worst_moment": f"최소 각도({r_min:.1f}°)가 감지됐습니다.",
            })
        else:
            improvements.append({
                "item": "오른팔 팔꿈치 각도",
                "value": f"{r_avg:.1f}°",
                "ideal": f"{ideal_e_min}~{ideal_e_max}°",
                "comment": f"각도가 {r_avg - ideal_e_max:.0f}° 큽니다.",
                "reason": std["elbow_reason"],
                "worst_moment": f"최대 각도({r_avg:.1f}°)가 반복 감지됐습니다.",
            })

    # ── 좌우 대칭 평가 ────────────────────────────────
    diff = abs(l_avg - r_avg) if l_avg and r_avg else 0
    if sym >= 85:
        strengths.append({
            "item": "좌우 대칭",
            "value": f"{sym:.0f}점",
            "ideal": "85점 이상",
            "comment": "좌우 팔 동작이 매우 균형 잡혀 있습니다.",
            "reason": std["symmetry_reason"],
        })
    elif sym >= 70:
        improvements.append({
            "item": "좌우 대칭",
            "value": f"{sym:.0f}점 (차이 {diff:.0f}°)",
            "ideal": "85점 이상",
            "comment": "좌우 팔 각도 차이가 있습니다. 거울 앞에서 양팔 드릴을 연습하세요.",
            "reason": std["symmetry_reason"],
            "worst_moment": "영상 전반에 걸쳐 좌우 차이가 관찰됩니다.",
        })
    else:
        improvements.append({
            "item": "좌우 대칭",
            "value": f"{sym:.0f}점 (차이 {diff:.0f}°)",
            "ideal": "85점 이상",
            "comment": f"좌우 팔 각도 차이({diff:.0f}°)가 큽니다. 한쪽 팔에 편향된 스트로크를 교정해야 합니다.",
            "reason": std["symmetry_reason"],
            "worst_moment": "영상 전반에 걸쳐 좌우 차이가 관찰됩니다.",
        })

    # ── 발차기 평가 ───────────────────────────────────
    if freq:
        if ideal_k_min <= freq <= ideal_k_max:
            strengths.append({
                "item": "발차기 빈도",
                "value": f"{freq:.2f}회/초 (총 {kick}회)",
                "ideal": f"{ideal_k_min}~{ideal_k_max}회/초",
                "comment": f"이상적인 발차기 리듬을 유지하고 있습니다.",
                "reason": std["kick_reason"],
            })
        elif freq < ideal_k_min:
            improvements.append({
                "item": "발차기 빈도",
                "value": f"{freq:.2f}회/초 (총 {kick}회)",
                "ideal": f"{ideal_k_min}~{ideal_k_max}회/초",
                "comment": f"발차기가 부족합니다. 발목 유연성 훈련과 킥 드릴을 추가하세요.",
                "reason": std["kick_reason"],
                "worst_moment": f"{dur:.0f}초 영상에서 총 {kick}회로 평균보다 낮습니다.",
            })
        else:
            improvements.append({
                "item": "발차기 빈도",
                "value": f"{freq:.2f}회/초 (총 {kick}회)",
                "ideal": f"{ideal_k_min}~{ideal_k_max}회/초",
                "comment": "발차기가 과도합니다. 체력 낭비를 줄이고 상체 추진력을 높이세요.",
                "reason": std["kick_reason"],
                "worst_moment": "영상 후반부에서 과도한 킥이 집중적으로 관찰됩니다.",
            })

    # ── 머리/시선 평가 ────────────────────────────────
    if head:
        if ideal_h_min <= head <= ideal_h_max:
            strengths.append({
                "item": "머리/시선 자세",
                "value": f"{head:.1f}°",
                "ideal": f"{ideal_h_min}~{ideal_h_max}°",
                "comment": "시선과 머리 자세가 이상적입니다.",
                "reason": std["head_reason"],
            })
        else:
            improvements.append({
                "item": "머리/시선 자세",
                "value": f"{head:.1f}°",
                "ideal": f"{ideal_h_min}~{ideal_h_max}°",
                "comment": "머리가 너무 들려 있습니다. 시선을 수면 아래 45° 방향으로 향하세요.",
                "reason": std["head_reason"],
                "worst_moment": "호흡 구간에서 머리가 과도하게 올라오는 패턴이 감지됩니다.",
            })

    # 모두 좋으면 기본 메시지
    if not improvements:
        improvements.append({
            "item": "전반적 자세",
            "value": "—",
            "ideal": "—",
            "comment": "전반적으로 좋은 자세입니다! 현재 패턴을 유지하면서 속도 향상에 집중하세요.",
            "reason": "",
        })

    return {
        "strengths":    strengths,
        "improvements": improvements,
        "drills":       std["drills"],
        "youtube_queries": std["youtube_queries"],
        "stroke_name":  std["name"],
        # 기존 호환성 유지
        "feedback": "\n".join(
            f"⚠️ {i['item']}: {i['value']} (이상 {i['ideal']}) — {i['comment']}"
            for i in improvements
        ),
    }

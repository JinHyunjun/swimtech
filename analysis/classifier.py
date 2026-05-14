"""
SwimTech — 영법 분류 모듈
랜드마크 패턴 기반으로 자유형/배영/평영/접영 분류
(ML 모델 없이 규칙 기반으로 먼저 구현, 추후 모델로 교체 가능)
"""
from dataclasses import dataclass
from typing import Optional
import numpy as np


@dataclass
class StrokeClassification:
    stroke_type: str        # freestyle / backstroke / breaststroke / butterfly / unknown
    confidence: float       # 0~100
    reason: str             # 분류 근거 설명


def classify_stroke(frame_metrics: list) -> StrokeClassification:
    """
    frame_metrics 리스트를 받아 영법 분류
    현재는 규칙 기반 (어깨 각도 + 팔 대칭성 + 발차기 패턴)
    """
    if not frame_metrics:
        return StrokeClassification("unknown", 0.0, "분석 데이터 없음")

    valid = [m for m in frame_metrics if m.landmarks_visible]
    if len(valid) < 10:
        return StrokeClassification("unknown", 30.0, "감지된 랜드마크 부족")

    # 평균값 계산
    l_elbows = [m.left_elbow_angle  for m in valid if m.left_elbow_angle]
    r_elbows = [m.right_elbow_angle for m in valid if m.right_elbow_angle]
    l_shoulders = [m.left_shoulder_angle  for m in valid if m.left_shoulder_angle]
    r_shoulders = [m.right_shoulder_angle for m in valid if m.right_shoulder_angle]

    if not l_elbows:
        return StrokeClassification("unknown", 20.0, "팔꿈치 각도 감지 불가")

    l_elbow_avg  = np.mean(l_elbows)
    r_elbow_avg  = np.mean(r_elbows)
    l_shoulder_avg = np.mean(l_shoulders) if l_shoulders else 90
    r_shoulder_avg = np.mean(r_shoulders) if r_shoulders else 90

    # 좌우 대칭성 (0 = 완전 대칭)
    elbow_diff    = abs(l_elbow_avg - r_elbow_avg)
    shoulder_diff = abs(l_shoulder_avg - r_shoulder_avg)

    # 발차기 빈도
    total_kicks = sum(1 for m in valid if m.kick_detected)
    kick_ratio = total_kicks / len(valid)  # 프레임당 발차기 비율

    # ── 분류 규칙 ─────────────────────────────────────

    # 배영: 어깨 각도가 크고 (180도 근처), 팔 대칭
    if l_shoulder_avg > 150 and r_shoulder_avg > 150 and shoulder_diff < 30:
        return StrokeClassification(
            "backstroke", 72.0,
            f"어깨 각도 평균 {l_shoulder_avg:.0f}°/{r_shoulder_avg:.0f}° (배영 특징)"
        )

    # 평영: 팔 대칭성 매우 높음 + 낮은 발차기 빈도
    if elbow_diff < 10 and shoulder_diff < 15 and kick_ratio < 0.05:
        return StrokeClassification(
            "breaststroke", 68.0,
            f"좌우 대칭 오차 {elbow_diff:.1f}° + 낮은 발차기 빈도 (평영 특징)"
        )

    # 접영: 팔 대칭 + 높은 발차기 빈도 (돌핀킥)
    if elbow_diff < 20 and kick_ratio > 0.15:
        return StrokeClassification(
            "butterfly", 65.0,
            f"대칭 팔 동작 + 높은 발차기 빈도 {kick_ratio:.2f} (접영 특징)"
        )

    # 자유형: 기본값 (비대칭 교차 팔 동작)
    return StrokeClassification(
        "freestyle", 60.0,
        f"교차 팔 동작 (좌우 차이 {elbow_diff:.1f}°) (자유형 추정)"
    )


# 영법별 피드백 기준값 (AI 없이 규칙 기반 피드백용)
STROKE_STANDARDS = {
    "freestyle": {
        "elbow_angle_ideal": (80, 110),
        "head_angle_ideal": (160, 180),
        "kick_freq_ideal": (1.5, 3.0),
        "drills": [
            "catch-up 드릴: 한 팔이 앞에서 기다리는 동안 반대 팔 스트로크",
            "핑거-드래그 드릴: 손가락을 수면에 끌며 팔 회전 연습",
            "6-1-6 킥 드릴: 6번 킥 후 1번 스트로크 반복",
        ],
        "youtube_queries": [
            "freestyle swimming technique drill",
            "자유형 팔 동작 교정 드릴",
        ]
    },
    "backstroke": {
        "elbow_angle_ideal": (90, 130),
        "head_angle_ideal": (155, 175),
        "kick_freq_ideal": (1.5, 3.0),
        "drills": [
            "단팔 배영 드릴: 한 팔만 사용해 스트로크 집중 연습",
            "플래그 드릴: 손이 귀 옆을 지나는 위치 인식 연습",
        ],
        "youtube_queries": [
            "backstroke technique drill",
            "배영 교정 드릴",
        ]
    },
    "breaststroke": {
        "elbow_angle_ideal": (70, 100),
        "head_angle_ideal": (150, 170),
        "kick_freq_ideal": (0.5, 1.5),
        "drills": [
            "2킥 1풀 드릴: 발차기 2번 후 팔 당기기 타이밍 연습",
            "손-머리 드릴: 팔을 앞으로 뻗을 때 머리가 물에 들어가는 타이밍",
        ],
        "youtube_queries": [
            "breaststroke technique drill",
            "평영 발차기 타이밍 드릴",
        ]
    },
    "butterfly": {
        "elbow_angle_ideal": (80, 115),
        "head_angle_ideal": (155, 175),
        "kick_freq_ideal": (1.0, 2.5),
        "drills": [
            "돌핀킥 드릴: 킥보드 잡고 돌핀킥만 연습",
            "단팔 접영 드릴: 한 팔 앞에 두고 반대 팔 스트로크",
        ],
        "youtube_queries": [
            "butterfly stroke technique drill",
            "접영 돌핀킥 드릴",
        ]
    },
}


def generate_rule_based_feedback(summary, stroke_type: str) -> dict:
    """
    AI 없이 규칙 기반으로 피드백 생성
    수치를 기준값과 비교해 텍스트 피드백 반환
    """
    std = STROKE_STANDARDS.get(stroke_type, STROKE_STANDARDS["freestyle"])
    feedback_lines = []

    # 팔꿈치 각도 피드백
    ideal_min, ideal_max = std["elbow_angle_ideal"]
    l_avg = summary.left_arm_angle_avg
    r_avg = summary.right_arm_angle_avg

    if l_avg < ideal_min:
        feedback_lines.append(f"왼팔 팔꿈치 각도({l_avg:.0f}°)가 너무 작습니다. 팔을 더 펴주세요. (이상: {ideal_min}~{ideal_max}°)")
    elif l_avg > ideal_max:
        feedback_lines.append(f"왼팔 팔꿈치 각도({l_avg:.0f}°)가 너무 큽니다. 팔꿈치를 더 구부려 당겨주세요.")

    if r_avg < ideal_min:
        feedback_lines.append(f"오른팔 팔꿈치 각도({r_avg:.0f}°)가 너무 작습니다.")
    elif r_avg > ideal_max:
        feedback_lines.append(f"오른팔 팔꿈치 각도({r_avg:.0f}°)가 너무 큽니다.")

    # 좌우 대칭 피드백
    if summary.arm_symmetry_score < 70:
        diff = abs(l_avg - r_avg)
        feedback_lines.append(f"좌우 팔 각도 차이({diff:.0f}°)가 큽니다. 대칭 동작을 연습하세요.")

    # 발차기 피드백
    freq_min, freq_max = std["kick_freq_ideal"]
    freq = summary.kick_frequency_hz
    if freq < freq_min:
        feedback_lines.append(f"발차기 빈도({freq:.1f}회/초)가 낮습니다. 더 빠르게 발차기를 해주세요.")
    elif freq > freq_max:
        feedback_lines.append(f"발차기 빈도({freq:.1f}회/초)가 높습니다. 체력 낭비를 줄이세요.")

    # 머리 피드백
    head_min, head_max = std["head_angle_ideal"]
    if summary.head_angle_avg < head_min:
        feedback_lines.append("머리가 너무 들려 있습니다. 시선을 아래로 향해 수평 자세를 유지하세요.")

    if not feedback_lines:
        feedback_lines.append("전반적으로 좋은 자세입니다! 현재 패턴을 유지하세요.")

    return {
        "feedback": "\n".join(f"• {line}" for line in feedback_lines),
        "drills": std["drills"],
        "youtube_queries": std["youtube_queries"],
    }

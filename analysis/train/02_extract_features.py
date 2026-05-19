"""
SwimTech — Step 2. 특징 추출 (v2.0)

추가 특징:
- 어깨 너비 정규화 손목 좌표 (체형 무관)
- 발목 Y rolling std 5프레임 (발차기 강도)
- 머리 수직 각도: nose-어깨중점 수직 기준
- 바디롤 각도: 어깨 좌우 기울기 (degrees)
- 스트로크 주기: 손목 Y peak 간격 (Hz)

저장 형식:
  features_frames.csv   — frame-level  (video_id, frame, category, purpose_tag, ...)
  features_summary.csv  — video-level  (학습용 집계 통계)

실행:
    python analysis/train/02_extract_features.py
    python analysis/train/02_extract_features.py --category competition
    python analysis/train/02_extract_features.py --skip 3
"""
import os, sys, argparse, math
from collections import deque
import numpy as np
import pandas as pd
import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pose import _ensure_model, MODEL_PATH, LM, calc_angle, lm_xy, KickDetector

BASE_DIR    = os.path.join(os.path.dirname(__file__), "data")
FRAMES_CSV  = os.path.join(BASE_DIR, "features_frames.csv")
SUMMARY_CSV = os.path.join(BASE_DIR, "features_summary.csv")

# 목적 태그 매핑 (top-level 폴더 → purpose)
CATEGORY_TO_PURPOSE = {
    "competition": "competition",
    "tutorial":    "tutorial",
    "health":      "health",
    "masters":     "masters",
    "start_turn":  "competition",
}

# 카테고리별 특징 가중치 (score model 학습 시 참고용)
CATEGORY_FEATURE_WEIGHTS = {
    "competition": {"l_elbow_angle": 1.5, "r_elbow_angle": 1.5, "kick_ratio": 1.4, "stroke_cycle_hz": 1.3},
    "health":      {"elbow_symmetry": 1.5, "shoulder_symmetry": 1.5, "l_ankle_roll_std5": 1.3, "r_ankle_roll_std5": 1.3},
    "tutorial":    {},  # 균등 가중치
    "masters":     {"body_roll_deg": 1.3, "elbow_symmetry": 1.2, "stroke_cycle_hz": 1.2},
}


# ── 신규 헬퍼 함수 ──────────────────────────────────────────────────────

def _shoulder_width(lms) -> float:
    """어깨 너비 (MediaPipe 정규화 좌표 기준 Euclidean)"""
    dx = lms[LM.LEFT_SHOULDER].x - lms[LM.RIGHT_SHOULDER].x
    dy = lms[LM.LEFT_SHOULDER].y - lms[LM.RIGHT_SHOULDER].y
    return max(math.sqrt(dx ** 2 + dy ** 2), 1e-4)


def _head_v_angle(lms) -> float:
    """nose → 어깨 중점 벡터와 수직(위 방향)의 각도 (degrees)
    0° = nose가 어깨 바로 위 (완벽한 수평 자세)
    클수록 머리가 옆으로 기울거나 들려 있음"""
    mid_x = (lms[LM.LEFT_SHOULDER].x + lms[LM.RIGHT_SHOULDER].x) / 2
    mid_y = (lms[LM.LEFT_SHOULDER].y + lms[LM.RIGHT_SHOULDER].y) / 2
    dx = lms[LM.NOSE].x - mid_x
    dy = mid_y - lms[LM.NOSE].y   # 양수 = nose가 어깨보다 위
    return round(math.degrees(math.atan2(abs(dx), abs(dy) + 1e-6)), 2)


def _body_roll_deg(lms) -> float:
    """어깨 좌우 기울기 각도 (수평 기준, degrees)"""
    dx = lms[LM.RIGHT_SHOULDER].x - lms[LM.LEFT_SHOULDER].x
    dy = lms[LM.RIGHT_SHOULDER].y - lms[LM.LEFT_SHOULDER].y
    return round(abs(math.degrees(math.atan2(dy, max(abs(dx), 1e-6)))), 2)


def _find_local_minima(seq: list, min_dist: int = 8) -> list:
    """Y 시퀀스에서 local minimum 인덱스 탐지 (손목 최상단 = 입수 직전)"""
    n = len(seq)
    if n < min_dist * 2 + 1:
        return []
    peaks = []
    for i in range(min_dist, n - min_dist):
        window = seq[i - min_dist: i + min_dist + 1]
        if seq[i] <= min(window) + 1e-6:
            if not peaks or (i - peaks[-1]) >= min_dist:
                peaks.append(i)
    return peaks


def _stroke_cycle_hz(l_seq: list, r_seq: list, fps: float, skip: int) -> float:
    """손목 Y local minimum 간격 → 스트로크 Hz"""
    combined = sorted(_find_local_minima(l_seq) + _find_local_minima(r_seq))
    if len(combined) < 2:
        return 0.0
    intervals = [combined[i + 1] - combined[i] for i in range(len(combined) - 1)]
    intervals  = [iv for iv in intervals if iv >= 4]
    if not intervals:
        return 0.0
    mean_sec = (sum(intervals) / len(intervals)) * skip / fps
    return round(1.0 / mean_sec, 3) if mean_sec > 0 else 0.0


# ── 프레임 특징 추출 ────────────────────────────────────────────────────

def extract_frames(video_path: str, category: str, purpose_tag: str,
                   stroke_label: str, skip: int = 5) -> list:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []
    fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total < 30:
        cap.release()
        return []

    video_id      = os.path.basename(video_path)
    kick_detector = KickDetector()
    l_ankle_buf   = deque(maxlen=5)
    r_ankle_buf   = deque(maxlen=5)
    l_wrist_seq   = []
    r_wrist_seq   = []
    frame_rows    = []
    total_proc    = 0
    detected      = 0

    options = PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    with PoseLandmarker.create_from_options(options) as detector:
        frame_num = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            if frame_num % skip != 0:
                frame_num += 1
                continue

            total_proc += 1
            ts_ms   = int(frame_num / fps * 1000)
            rgb     = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_img  = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result  = detector.detect_for_video(mp_img, ts_ms)

            if result.pose_landmarks and len(result.pose_landmarks) > 0:
                detected += 1
                lms = result.pose_landmarks[0]

                # ── 기존 특징 ───────────────────────────────────────
                l_elbow    = calc_angle(lm_xy(lms, LM.LEFT_SHOULDER),  lm_xy(lms, LM.LEFT_ELBOW),    lm_xy(lms, LM.LEFT_WRIST))
                r_elbow    = calc_angle(lm_xy(lms, LM.RIGHT_SHOULDER), lm_xy(lms, LM.RIGHT_ELBOW),   lm_xy(lms, LM.RIGHT_WRIST))
                l_shoulder = calc_angle(lm_xy(lms, LM.LEFT_HIP),       lm_xy(lms, LM.LEFT_SHOULDER), lm_xy(lms, LM.LEFT_ELBOW))
                r_shoulder = calc_angle(lm_xy(lms, LM.RIGHT_HIP),      lm_xy(lms, LM.RIGHT_SHOULDER),lm_xy(lms, LM.RIGHT_ELBOW))
                head_angle = calc_angle(lm_xy(lms, LM.LEFT_EAR),       lm_xy(lms, LM.NOSE),          lm_xy(lms, LM.RIGHT_EAR))
                hip_angle  = calc_angle(lm_xy(lms, LM.LEFT_SHOULDER),  lm_xy(lms, LM.LEFT_HIP),      lm_xy(lms, LM.LEFT_ANKLE))
                body_roll  = round(abs(lms[LM.LEFT_SHOULDER].y - lms[LM.RIGHT_SHOULDER].y), 4)
                hip_roll   = round(abs(lms[LM.LEFT_HIP].y      - lms[LM.RIGHT_HIP].y),      4)
                kicked     = kick_detector.update(lms[LM.LEFT_ANKLE].y, lms[LM.RIGHT_ANKLE].y)
                entry_ang  = round(abs(lms[LM.LEFT_WRIST].y - lms[LM.LEFT_HIP].y),    4)
                streamline = round(abs(lms[LM.LEFT_WRIST].x - lms[LM.RIGHT_WRIST].x), 4)

                # ── 신규 특징 ───────────────────────────────────────
                sw            = _shoulder_width(lms)
                head_v        = _head_v_angle(lms)
                body_roll_d   = _body_roll_deg(lms)

                # 어깨 너비 정규화 손목 좌표
                norm_l_wx = round(lms[LM.LEFT_WRIST].x  / sw, 4)
                norm_r_wx = round(lms[LM.RIGHT_WRIST].x / sw, 4)
                norm_l_wy = round(lms[LM.LEFT_WRIST].y  / sw, 4)
                norm_r_wy = round(lms[LM.RIGHT_WRIST].y / sw, 4)

                # 발목 Y rolling std (5프레임)
                l_ankle_buf.append(lms[LM.LEFT_ANKLE].y)
                r_ankle_buf.append(lms[LM.RIGHT_ANKLE].y)
                l_ank_std = round(float(np.std(list(l_ankle_buf))), 6) if len(l_ankle_buf) >= 2 else 0.0
                r_ank_std = round(float(np.std(list(r_ankle_buf))), 6) if len(r_ankle_buf) >= 2 else 0.0

                # 손목 Y 시퀀스 (스트로크 주기용)
                l_wrist_seq.append(lms[LM.LEFT_WRIST].y)
                r_wrist_seq.append(lms[LM.RIGHT_WRIST].y)

                frame_rows.append({
                    "video_id":          video_id,
                    "frame":             frame_num,
                    "timestamp":         round(frame_num / fps, 3),
                    "category":          category,
                    "purpose_tag":       purpose_tag,
                    "stroke_label":      stroke_label,
                    # 기존
                    "l_elbow_angle":     round(l_elbow,    2),
                    "r_elbow_angle":     round(r_elbow,    2),
                    "l_shoulder_angle":  round(l_shoulder, 2),
                    "r_shoulder_angle":  round(r_shoulder, 2),
                    "head_angle":        round(head_angle, 2),
                    "hip_angle":         round(hip_angle,  2),
                    "body_roll":         body_roll,
                    "hip_roll":          hip_roll,
                    "elbow_symmetry":    round(abs(l_elbow - r_elbow),     2),
                    "shoulder_symmetry": round(abs(l_shoulder - r_shoulder), 2),
                    "kick_detected":     int(kicked),
                    "total_kicks":       kick_detector.kick_count,
                    "entry_angle":       entry_ang,
                    "streamline_width":  streamline,
                    # 신규
                    "head_v_angle":      head_v,
                    "body_roll_deg":     body_roll_d,
                    "shoulder_width":    round(sw, 4),
                    "norm_l_wrist_x":    norm_l_wx,
                    "norm_r_wrist_x":    norm_r_wx,
                    "norm_l_wrist_y":    norm_l_wy,
                    "norm_r_wrist_y":    norm_r_wy,
                    "l_ankle_roll_std5": l_ank_std,
                    "r_ankle_roll_std5": r_ank_std,
                })

            frame_num += 1

    cap.release()
    if not frame_rows:
        return []

    # 비디오 레벨 통계 추가 (모든 프레임에 동일 값)
    cycle_hz    = _stroke_cycle_hz(l_wrist_seq, r_wrist_seq, fps, skip)
    detect_rate = round(detected / total_proc, 3) if total_proc > 0 else 0.0
    for r in frame_rows:
        r["stroke_cycle_hz"] = cycle_hz
        r["detection_rate"]  = detect_rate

    return frame_rows


def summarize_video(frame_rows: list) -> dict:
    """Frame-level rows → video-level 집계 (03_train_model.py 학습용)"""
    if not frame_rows:
        return {}
    df  = pd.DataFrame(frame_rows)
    dur = frame_rows[-1]["timestamp"] if frame_rows else 1.0

    STAT_COLS = [
        "l_elbow_angle", "r_elbow_angle",
        "l_shoulder_angle", "r_shoulder_angle",
        "head_angle", "head_v_angle",
        "hip_angle", "body_roll", "body_roll_deg", "hip_roll",
        "elbow_symmetry", "shoulder_symmetry",
        "entry_angle", "streamline_width",
        "shoulder_width",
        "norm_l_wrist_x", "norm_r_wrist_x",
        "norm_l_wrist_y", "norm_r_wrist_y",
        "l_ankle_roll_std5", "r_ankle_roll_std5",
    ]

    row = {
        "video_id":        frame_rows[0]["video_id"],
        "category":        frame_rows[0]["category"],
        "purpose_tag":     frame_rows[0]["purpose_tag"],
        "stroke_label":    frame_rows[0]["stroke_label"],
        "duration_sec":    round(dur, 2),
        "kick_frequency":  round(df["total_kicks"].max() / dur, 3) if dur > 0 else 0.0,
        "kick_ratio":      round(df["kick_detected"].mean(), 4),
        "stroke_cycle_hz": frame_rows[0].get("stroke_cycle_hz", 0.0),
        "detection_rate":  frame_rows[0].get("detection_rate", 0.0),
    }
    for col in STAT_COLS:
        if col not in df.columns:
            continue
        row[f"{col}_mean"] = round(float(df[col].mean()), 4)
        row[f"{col}_std"]  = round(float(df[col].std()),  4)
        row[f"{col}_min"]  = round(float(df[col].min()),  4)

    return row


# ── 비디오 스캔 ─────────────────────────────────────────────────────────

def scan_videos(base_dir: str, category_filter: str = "all"):
    """(video_path, category, purpose_tag, stroke_label) 튜플 yield"""
    for top in sorted(os.listdir(base_dir)):
        top_path = os.path.join(base_dir, top)
        if not os.path.isdir(top_path) or top.startswith("_"):
            continue
        if category_filter != "all" and top != category_filter:
            continue

        purpose = CATEGORY_TO_PURPOSE.get(top, top)
        subdirs = [d for d in os.listdir(top_path)
                   if os.path.isdir(os.path.join(top_path, d))]

        if subdirs:
            for sub in sorted(subdirs):
                sub_path = os.path.join(top_path, sub)
                parts    = sub.split("_")
                stroke   = "_".join(parts[1:]) if len(parts) > 1 else sub
                for f in os.listdir(sub_path):
                    if f.lower().endswith(".mp4"):
                        yield os.path.join(sub_path, f), sub, purpose, stroke
        else:
            for f in os.listdir(top_path):
                if f.lower().endswith(".mp4"):
                    yield os.path.join(top_path, f), top, purpose, "unknown"


# ── 메인 ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", default="all",
                        help="처리할 카테고리 (competition|tutorial|health|masters|all)")
    parser.add_argument("--skip", type=int, default=5,
                        help="프레임 샘플링 간격 (기본: 5)")
    parser.add_argument("--min-detect", type=float, default=0.0,
                        help="최소 랜드마크 감지율 필터 (0~1, 기본: 0 = 필터 없음)")
    args = parser.parse_args()

    _ensure_model()

    # 기존 CSV 로드
    existing_frames  = pd.read_csv(FRAMES_CSV)  if os.path.exists(FRAMES_CSV)  else pd.DataFrame()
    existing_summary = pd.read_csv(SUMMARY_CSV) if os.path.exists(SUMMARY_CSV) else pd.DataFrame()
    done_videos = set(existing_frames["video_id"].tolist()) if not existing_frames.empty else set()

    all_frame_rows = existing_frames.to_dict("records") if not existing_frames.empty else []
    all_summary    = existing_summary.to_dict("records") if not existing_summary.empty else []

    videos = list(scan_videos(BASE_DIR, args.category))
    print(f"\n총 {len(videos)}개 비디오 발견 (이미 처리됨: {len(done_videos)}개)\n")

    for i, (vpath, category, purpose, stroke) in enumerate(videos, 1):
        vname = os.path.basename(vpath)
        if vname in done_videos:
            print(f"  [{i}/{len(videos)}] {vname} — skip")
            continue

        print(f"  [{i}/{len(videos)}] {vname}")
        print(f"           category={category}  purpose={purpose}  stroke={stroke}")

        rows = extract_frames(vpath, category, purpose, stroke, skip=args.skip)
        if not rows:
            print(f"           ⚠️ 감지 실패")
            continue

        rate = rows[0].get("detection_rate", 0)
        print(f"           감지율={rate:.0%}  프레임={len(rows)}  cycle={rows[0].get('stroke_cycle_hz', 0):.2f}Hz")

        if args.min_detect > 0 and rate < args.min_detect:
            print(f"           ⚠️ 감지율 부족 ({rate:.0%} < {args.min_detect:.0%}) → 제외")
            continue

        all_frame_rows.extend(rows)

        summary = summarize_video(rows)
        if summary:
            all_summary.append(summary)

    # 저장
    if all_frame_rows:
        df_f = pd.DataFrame(all_frame_rows)
        df_f.to_csv(FRAMES_CSV, index=False, encoding="utf-8-sig")
        print(f"\n💾 {FRAMES_CSV}  ({len(df_f)}행)")

    if all_summary:
        df_s = pd.DataFrame(all_summary)
        df_s.to_csv(SUMMARY_CSV, index=False, encoding="utf-8-sig")
        print(f"💾 {SUMMARY_CSV}  ({len(df_s)}행)")
        print(f"\n목적별 분포:\n{df_s['purpose_tag'].value_counts().to_string()}")
        print(f"\n영법별 분포:\n{df_s['stroke_label'].value_counts().to_string()}")

    print("\n✅ 특징 추출 완료!")
    print("다음 단계: python analysis/train/03_train_model.py")


if __name__ == "__main__":
    main()

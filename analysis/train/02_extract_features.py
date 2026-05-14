"""
SwimTech — Step 2. 특징 추출 (3-Track 버전)

Track 1. Competition  → 대회 영상: 효율·속도 중심 특징
Track 2. Tutorial     → 강의 영상: 자세 교정 중심 특징
Track 3. Start & Turn → 스타트/턴 구간 특징

실행:
    python analysis/train/02_extract_features.py
    python analysis/train/02_extract_features.py --track competition
    python analysis/train/02_extract_features.py --track start_turn
"""
import os, sys, argparse
import numpy as np
import pandas as pd
import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pose import _ensure_model, MODEL_PATH, LM, calc_angle, lm_xy, KickDetector

BASE_DIR  = os.path.join(os.path.dirname(__file__), "data")
TRACK_DIRS = {
    "competition": os.path.join(BASE_DIR, "competition"),
    "tutorial":    os.path.join(BASE_DIR, "tutorial"),
    "start_turn":  os.path.join(BASE_DIR, "start_turn"),
}
CSV_PATHS = {
    "competition": os.path.join(BASE_DIR, "features_competition.csv"),
    "tutorial":    os.path.join(BASE_DIR, "features_tutorial.csv"),
    "start_turn":  os.path.join(BASE_DIR, "features_start_turn.csv"),
}


def extract_frames(video_path: str, skip: int = 5) -> list:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []
    fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total < 30:
        cap.release()
        return []

    kick_detector = KickDetector()
    features = []

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

            ts_ms  = int(frame_num / fps * 1000)
            rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = detector.detect_for_video(mp_img, ts_ms)

            if result.pose_landmarks and len(result.pose_landmarks) > 0:
                lms = result.pose_landmarks[0]

                l_elbow    = calc_angle(lm_xy(lms,LM.LEFT_SHOULDER),  lm_xy(lms,LM.LEFT_ELBOW),    lm_xy(lms,LM.LEFT_WRIST))
                r_elbow    = calc_angle(lm_xy(lms,LM.RIGHT_SHOULDER), lm_xy(lms,LM.RIGHT_ELBOW),   lm_xy(lms,LM.RIGHT_WRIST))
                l_shoulder = calc_angle(lm_xy(lms,LM.LEFT_HIP),       lm_xy(lms,LM.LEFT_SHOULDER), lm_xy(lms,LM.LEFT_ELBOW))
                r_shoulder = calc_angle(lm_xy(lms,LM.RIGHT_HIP),      lm_xy(lms,LM.RIGHT_SHOULDER),lm_xy(lms,LM.RIGHT_ELBOW))
                head_angle = calc_angle(lm_xy(lms,LM.LEFT_EAR),       lm_xy(lms,LM.NOSE),          lm_xy(lms,LM.RIGHT_EAR))
                hip_angle  = calc_angle(lm_xy(lms,LM.LEFT_SHOULDER),  lm_xy(lms,LM.LEFT_HIP),      lm_xy(lms,LM.LEFT_ANKLE))
                body_roll  = abs(lms[LM.LEFT_SHOULDER].y - lms[LM.RIGHT_SHOULDER].y)
                hip_roll   = abs(lms[LM.LEFT_HIP].y      - lms[LM.RIGHT_HIP].y)
                kicked     = kick_detector.update(lms[LM.LEFT_ANKLE].y, lms[LM.RIGHT_ANKLE].y)
                entry_ang  = abs(lms[LM.LEFT_WRIST].y  - lms[LM.LEFT_HIP].y)
                streamline = abs(lms[LM.LEFT_WRIST].x  - lms[LM.RIGHT_WRIST].x)

                features.append({
                    "frame":            frame_num,
                    "timestamp":        round(frame_num / fps, 3),
                    "l_elbow_angle":    round(l_elbow,    2),
                    "r_elbow_angle":    round(r_elbow,    2),
                    "l_shoulder_angle": round(l_shoulder, 2),
                    "r_shoulder_angle": round(r_shoulder, 2),
                    "head_angle":       round(head_angle, 2),
                    "hip_angle":        round(hip_angle,  2),
                    "body_roll":        round(body_roll,  4),
                    "hip_roll":         round(hip_roll,   4),
                    "elbow_symmetry":   round(abs(l_elbow - r_elbow), 2),
                    "shoulder_symmetry":round(abs(l_shoulder - r_shoulder), 2),
                    "kick_detected":    int(kicked),
                    "total_kicks":      kick_detector.kick_count,
                    "entry_angle":      round(entry_ang,  4),
                    "streamline_width": round(streamline, 4),
                })
            frame_num += 1

    cap.release()
    return features


def summarize(features: list, label: str, category: str, video_path: str) -> dict:
    if not features:
        return None
    df  = pd.DataFrame(features)
    dur = features[-1]["timestamp"] if features else 1

    return {
        "video":    os.path.basename(video_path),
        "label":    label,
        "category": category,
        "duration_sec": dur,
        "l_elbow_mean":          round(df["l_elbow_angle"].mean(),       2),
        "l_elbow_std":           round(df["l_elbow_angle"].std(),        2),
        "l_elbow_min":           round(df["l_elbow_angle"].min(),        2),
        "r_elbow_mean":          round(df["r_elbow_angle"].mean(),       2),
        "r_elbow_std":           round(df["r_elbow_angle"].std(),        2),
        "r_elbow_min":           round(df["r_elbow_angle"].min(),        2),
        "l_shoulder_mean":       round(df["l_shoulder_angle"].mean(),    2),
        "r_shoulder_mean":       round(df["r_shoulder_angle"].mean(),    2),
        "head_angle_mean":       round(df["head_angle"].mean(),          2),
        "hip_angle_mean":        round(df["hip_angle"].mean(),           2),
        "body_roll_mean":        round(df["body_roll"].mean(),           4),
        "hip_roll_mean":         round(df["hip_roll"].mean(),            4),
        "elbow_symmetry_mean":   round(df["elbow_symmetry"].mean(),      2),
        "shoulder_symmetry_mean":round(df["shoulder_symmetry"].mean(),   2),
        "kick_frequency":        round(df["total_kicks"].max() / dur,    3) if dur > 0 else 0,
        "kick_ratio":            round(df["kick_detected"].mean(),       4),
        "entry_angle_mean":      round(df["entry_angle"].mean(),         4),
        "streamline_width_mean": round(df["streamline_width"].mean(),    4),
    }


def label_from_category(cat: str) -> str:
    parts = cat.split("_")
    if parts[0] in ("competition", "tutorial"):
        return "_".join(parts[1:])
    return cat


def process_track(track: str):
    track_dir = TRACK_DIRS[track]
    csv_path  = CSV_PATHS[track]
    if not os.path.exists(track_dir):
        print(f"  ⚠️  {track_dir} 없음 → 건너뜀")
        return

    all_rows, existing_videos = [], set()
    if os.path.exists(csv_path):
        ex = pd.read_csv(csv_path)
        all_rows = ex.to_dict("records")
        existing_videos = set(ex["video"].tolist())
        print(f"  기존 {len(all_rows)}개 로드")

    categories = [d for d in os.listdir(track_dir) if os.path.isdir(os.path.join(track_dir, d))]

    for cat in categories:
        cat_dir = os.path.join(track_dir, cat)
        videos  = [f for f in os.listdir(cat_dir) if f.endswith(".mp4")]
        label   = label_from_category(cat)
        print(f"\n  [{cat}] {len(videos)}개, 레이블={label}")

        for i, vf in enumerate(videos, 1):
            if vf in existing_videos:
                print(f"    [{i}] {vf} — skip")
                continue
            print(f"    [{i}/{len(videos)}] {vf}...")
            frames = extract_frames(os.path.join(cat_dir, vf))
            if not frames:
                print(f"      ⚠️ 감지 실패")
                continue
            row = summarize(frames, label, cat, vf)
            if row:
                all_rows.append(row)
                print(f"      ✅ kick={row['kick_frequency']:.2f}/s")

    if all_rows:
        df = pd.DataFrame(all_rows)
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"\n  💾 {csv_path} ({len(df)}개)")
        print(df["label"].value_counts().to_string())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--track", choices=["competition","tutorial","start_turn","all"], default="all")
    args = parser.parse_args()

    _ensure_model()
    tracks = ["competition","tutorial","start_turn"] if args.track == "all" else [args.track]
    for t in tracks:
        print(f"\n{'='*50}\n  Track: {t}\n{'='*50}")
        process_track(t)
    print("\n✅ 특징 추출 완료!")
    print("다음 단계: python analysis/train/03_train_model.py")


if __name__ == "__main__":
    main()

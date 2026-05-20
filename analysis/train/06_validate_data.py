"""
SwimTech — Step 6. 데이터 품질 검증

- data/ 하위 모든 카테고리 폴더 순회
- 각 영상에서 30프레임 샘플링
- MediaPipe로 랜드마크 감지율 계산
- 감지율 80% 이상: ✅ 정상
- 감지율 50~80%:   ⚠️ 주의
- 감지율 50% 미만: ❌ 불량
- 결과를 validation_report.json으로 저장

실행:
    python analysis/train/06_validate_data.py
    python analysis/train/06_validate_data.py --category competition
    python analysis/train/06_validate_data.py --frames 50
"""
import os, sys, json, argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pose import _ensure_model, MODEL_PATH

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode

BASE_DIR    = os.path.join(os.path.dirname(__file__), "data")
REPORT_PATH = os.path.join(BASE_DIR, "validation_report.json")

CATEGORY_TAGS = {
    "competition": ("competition", "elite"),
    "tutorial":    ("technique",   "beginner"),
    "health":      ("health",      "beginner"),
    "masters":     ("hobby",       "intermediate"),
    "start_turn":  ("competition", "elite"),
}


def detect_rate_for_video(video_path: str, n_frames: int = 30) -> float:
    """영상에서 n_frames개 균등 샘플링 후 MediaPipe 감지율 반환 (0~1)"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0.0

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0

    if total < n_frames:
        cap.release()
        return 0.0

    # 균등 간격 프레임 인덱스
    step    = max(1, total // n_frames)
    indices = list(range(0, total, step))[:n_frames]

    options = PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    detected = 0
    sampled  = 0

    with PoseLandmarker.create_from_options(options) as detector:
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue
            sampled += 1
            ts_ms  = int(idx / fps * 1000)
            rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = detector.detect_for_video(mp_img, ts_ms)
            if result.pose_landmarks and len(result.pose_landmarks) > 0:
                detected += 1

    cap.release()
    return detected / sampled if sampled > 0 else 0.0


def status_label(rate: float) -> str:
    if rate >= 0.80:
        return "✅ 정상"
    elif rate >= 0.50:
        return "⚠️ 주의"
    return "❌ 불량"


def scan_videos(base_dir: str, category_filter: str = "all"):
    """(video_path, category, purpose_tag, skill_level) 튜플 yield"""
    for top in sorted(os.listdir(base_dir)):
        top_path = os.path.join(base_dir, top)
        if not os.path.isdir(top_path) or top.startswith("_") or top.endswith(".csv"):
            continue
        if category_filter != "all" and top != category_filter:
            continue

        purpose_tag, skill_level = CATEGORY_TAGS.get(top, (top, "unknown"))
        subdirs = [d for d in os.listdir(top_path)
                   if os.path.isdir(os.path.join(top_path, d))]

        if subdirs:
            for sub in sorted(subdirs):
                sub_path = os.path.join(top_path, sub)
                for f in sorted(os.listdir(sub_path)):
                    if f.lower().endswith(".mp4"):
                        yield os.path.join(sub_path, f), top, purpose_tag, skill_level
        else:
            for f in sorted(os.listdir(top_path)):
                if f.lower().endswith(".mp4"):
                    yield os.path.join(top_path, f), top, purpose_tag, skill_level


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", default="all",
                        help="검증할 카테고리 (competition|tutorial|health|masters|all)")
    parser.add_argument("--frames", type=int, default=30,
                        help="영상당 샘플링 프레임 수 (기본: 30)")
    args = parser.parse_args()

    _ensure_model()

    videos = list(scan_videos(BASE_DIR, args.category))
    print(f"\n🔍 SwimTech 데이터 품질 검증 시작")
    print(f"   총 {len(videos)}개 영상, 영상당 {args.frames}프레임 샘플링\n")

    summary = {"total": len(videos), "ok": 0, "warn": 0, "bad": 0, "videos": []}
    cat_stats: dict = {}

    for i, (vpath, category, purpose_tag, skill_level) in enumerate(videos, 1):
        vname = os.path.basename(vpath)
        print(f"  [{i}/{len(videos)}] {category}/{vname}", end=" ", flush=True)

        rate   = detect_rate_for_video(vpath, n_frames=args.frames)
        status = status_label(rate)
        print(f"→ {rate:.1%}  {status}")

        entry = {
            "video":       vname,
            "path":        vpath,
            "category":    category,
            "purpose_tag": purpose_tag,
            "skill_level": skill_level,
            "detect_rate": round(rate, 4),
            "status":      status,
        }
        summary["videos"].append(entry)

        if rate >= 0.80:
            summary["ok"] += 1
        elif rate >= 0.50:
            summary["warn"] += 1
        else:
            summary["bad"] += 1

        if category not in cat_stats:
            cat_stats[category] = {"ok": 0, "warn": 0, "bad": 0, "rates": []}
        cat_stats[category]["rates"].append(rate)
        key = "ok" if rate >= 0.80 else ("warn" if rate >= 0.50 else "bad")
        cat_stats[category][key] += 1

    # 카테고리별 요약
    import statistics
    for cat, st in cat_stats.items():
        rates = st.pop("rates")
        st["mean_rate"] = round(statistics.mean(rates), 4) if rates else 0
        cat_stats[cat] = st
    summary["by_category"] = cat_stats

    # 전체 요약 출력
    print(f"\n{'='*50}")
    print(f"  총 {summary['total']}개  "
          f"✅ 정상={summary['ok']}  ⚠️ 주의={summary['warn']}  ❌ 불량={summary['bad']}")
    print(f"\n  카테고리별 요약:")
    for cat, st in cat_stats.items():
        print(f"    {cat:12s}: ✅{st['ok']} ⚠️{st['warn']} ❌{st['bad']}  "
              f"평균감지율={st['mean_rate']:.1%}")

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n💾 검증 리포트 저장: {REPORT_PATH}")
    print("\n✅ 데이터 검증 완료!")


if __name__ == "__main__":
    main()

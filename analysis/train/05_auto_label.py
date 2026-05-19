"""
SwimTech — Step 5. 자동 라벨링 (v2.0)

기존: 폴더 구조 기반 라벨링만
개선:
  - MediaPipe로 영상 분석 → 영법 자동 감지
  - 랜드마크 감지율 < 70% 영상 자동 제외 (excluded=true)
  - 감지된 영법 + 폴더 카테고리로 labels.json 자동 업데이트
  - 신뢰도 정보 함께 저장

실행:
    python analysis/train/05_auto_label.py
    python analysis/train/05_auto_label.py --min-detect 0.7
    python analysis/train/05_auto_label.py --overwrite       # 기존 항목도 재분석
    python analysis/train/05_auto_label.py --dry-run         # 분석만, 저장 X
"""
import os, sys, json, argparse, math
from collections import deque
import numpy as np
import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pose import _ensure_model, MODEL_PATH, LM, calc_angle, lm_xy, KickDetector

BASE_DIR   = os.path.join(os.path.dirname(__file__), "data")
LABELS_PATH = os.path.join(BASE_DIR, "labels.json")

CATEGORY_TO_PURPOSE = {
    "competition": "competition",
    "tutorial":    "tutorial",
    "health":      "health",
    "masters":     "masters",
    "start_turn":  "competition",
}

SKILL_MAP = {
    "competition": "elite",
    "tutorial":    "intermediate",
    "health":      "beginner",
    "masters":     "advanced",
    "start_turn":  "elite",
}


# ── 영법 추론 (규칙 기반) ────────────────────────────────────────────────

def _stroke_from_metrics(metrics: dict) -> tuple:
    """
    집계된 프레임 특징 → (stroke_type, confidence 0~1)
    returns ("unknown", 0.0) 감지 불가 시
    """
    l_elbow  = metrics.get("l_elbow_mean", 0)
    r_elbow  = metrics.get("r_elbow_mean", 0)
    l_sh     = metrics.get("l_shoulder_mean", 0)
    r_sh     = metrics.get("r_shoulder_mean", 0)
    kick_r   = metrics.get("kick_ratio", 0)
    sym      = metrics.get("elbow_sym_mean", 0)

    if l_elbow <= 0:
        return "unknown", 0.0

    elbow_diff  = abs(l_elbow - r_elbow)
    shoulder_diff = abs(l_sh - r_sh)

    # 배영: 어깨 각도 높음 + 대칭적
    if l_sh > 145 and r_sh > 145 and shoulder_diff < 30:
        return "backstroke", 0.75

    # 평영: 좌우 대칭 + 낮은 킥
    if elbow_diff < 12 and shoulder_diff < 18 and kick_r < 0.05:
        return "breaststroke", 0.68

    # 접영: 좌우 대칭 팔 + 높은 킥
    if elbow_diff < 22 and kick_r > 0.15:
        return "butterfly", 0.65

    # 자유형: 기본
    conf = max(0.50, 0.70 - elbow_diff * 0.005)
    return "freestyle", round(conf, 2)


def _stroke_from_subfolder(subfolder: str) -> str:
    """subfolder 이름에서 영법 추출 (예: competition_freestyle → freestyle)"""
    parts = subfolder.split("_")
    for stroke in ("freestyle", "backstroke", "breaststroke", "butterfly", "medley"):
        if stroke in subfolder:
            return stroke
    return "unknown"


# ── 비디오 분석 ─────────────────────────────────────────────────────────

def analyze_video(video_path: str, sample_skip: int = 15) -> dict:
    """
    video_path: 영상 경로
    sample_skip: 매 n번째 프레임만 분석 (기본 15 → fps30 영상에서 0.5초 간격)
    returns: {
        detection_rate, stroke_type, stroke_confidence,
        l_elbow_mean, r_elbow_mean, kick_ratio, ...
    }
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {"error": "cannot_open"}

    fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total < 30:
        cap.release()
        return {"error": "too_short"}

    kick_detector = KickDetector()
    l_elbows, r_elbows = [], []
    l_shoulders, r_shoulders = [], []
    kick_detected_frames = 0
    total_proc = 0
    detected   = 0

    options = PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.45,
        min_pose_presence_confidence=0.45,
        min_tracking_confidence=0.45,
    )

    with PoseLandmarker.create_from_options(options) as detector:
        frame_num = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            if frame_num % sample_skip != 0:
                frame_num += 1
                continue

            total_proc += 1
            ts_ms = int(frame_num / fps * 1000)
            rgb   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img   = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = detector.detect_for_video(img, ts_ms)

            if result.pose_landmarks and len(result.pose_landmarks) > 0:
                detected += 1
                lms = result.pose_landmarks[0]

                try:
                    le = calc_angle(lm_xy(lms, LM.LEFT_SHOULDER), lm_xy(lms, LM.LEFT_ELBOW),
                                    lm_xy(lms, LM.LEFT_WRIST))
                    re = calc_angle(lm_xy(lms, LM.RIGHT_SHOULDER), lm_xy(lms, LM.RIGHT_ELBOW),
                                    lm_xy(lms, LM.RIGHT_WRIST))
                    ls = calc_angle(lm_xy(lms, LM.LEFT_HIP), lm_xy(lms, LM.LEFT_SHOULDER),
                                    lm_xy(lms, LM.LEFT_ELBOW))
                    rs = calc_angle(lm_xy(lms, LM.RIGHT_HIP), lm_xy(lms, LM.RIGHT_SHOULDER),
                                    lm_xy(lms, LM.RIGHT_ELBOW))
                    l_elbows.append(le)
                    r_elbows.append(re)
                    l_shoulders.append(ls)
                    r_shoulders.append(rs)
                    kicked = kick_detector.update(lms[LM.LEFT_ANKLE].y, lms[LM.RIGHT_ANKLE].y)
                    if kicked:
                        kick_detected_frames += 1
                except Exception:
                    pass

            frame_num += 1

    cap.release()

    if total_proc == 0:
        return {"error": "no_frames"}

    detection_rate = round(detected / total_proc, 3)

    if detected < 3:
        return {"detection_rate": detection_rate, "error": "insufficient_landmarks"}

    metrics = {
        "detection_rate":  detection_rate,
        "l_elbow_mean":    float(np.mean(l_elbows))    if l_elbows    else 0.0,
        "r_elbow_mean":    float(np.mean(r_elbows))    if r_elbows    else 0.0,
        "l_shoulder_mean": float(np.mean(l_shoulders)) if l_shoulders else 0.0,
        "r_shoulder_mean": float(np.mean(r_shoulders)) if r_shoulders else 0.0,
        "elbow_sym_mean":  float(abs(np.mean(l_elbows) - np.mean(r_elbows))) if (l_elbows and r_elbows) else 0.0,
        "kick_ratio":      round(kick_detected_frames / detected, 4) if detected > 0 else 0.0,
        "analyzed_frames": detected,
        "total_frames":    total_proc,
    }

    stroke, conf = _stroke_from_metrics(metrics)
    metrics["stroke_type"]        = stroke
    metrics["stroke_confidence"]  = conf
    return metrics


# ── labels.json 관리 ────────────────────────────────────────────────────

def load_labels() -> dict:
    if not os.path.exists(LABELS_PATH):
        return {}
    with open(LABELS_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    # _schema, _example 등 메타 키 제외
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def save_labels(labels: dict):
    meta = {
        "_schema": {
            "stroke_type":        "freestyle | backstroke | breaststroke | butterfly | unknown",
            "skill_level":        "beginner | intermediate | advanced | elite",
            "purpose_tag":        "competition | tutorial | health | masters",
            "source":             "출처 설명 (채널명, 대회명 등)",
            "stroke_confidence":  "자동 감지 신뢰도 (0~1)",
            "detection_rate":     "랜드마크 감지율 (0~1)",
            "excluded":           "true = 감지율 부족으로 제외된 영상",
            "auto_labeled":       "true = 자동 라벨링",
        }
    }
    meta.update(labels)
    with open(LABELS_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


# ── 비디오 스캔 ─────────────────────────────────────────────────────────

def scan_videos(base_dir: str):
    """(video_path, top_folder, subfolder) 튜플 yield"""
    for top in sorted(os.listdir(base_dir)):
        top_path = os.path.join(base_dir, top)
        if not os.path.isdir(top_path) or top.startswith("_"):
            continue
        subdirs = [d for d in os.listdir(top_path) if os.path.isdir(os.path.join(top_path, d))]
        if subdirs:
            for sub in sorted(subdirs):
                sub_path = os.path.join(top_path, sub)
                for f in os.listdir(sub_path):
                    if f.lower().endswith(".mp4"):
                        yield os.path.join(sub_path, f), top, sub
        else:
            for f in os.listdir(top_path):
                if f.lower().endswith(".mp4"):
                    yield os.path.join(top_path, f), top, top


# ── 메인 ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-detect", type=float, default=0.70,
                        help="최소 랜드마크 감지율 (기본: 0.70 = 70%%)")
    parser.add_argument("--overwrite", action="store_true",
                        help="기존 라벨 항목도 재분석해서 덮어쓰기")
    parser.add_argument("--dry-run", action="store_true",
                        help="분석만 수행하고 labels.json 저장 안 함")
    parser.add_argument("--skip", type=int, default=15,
                        help="프레임 샘플링 간격 (기본: 15)")
    args = parser.parse_args()

    _ensure_model()

    labels = load_labels()
    videos = list(scan_videos(BASE_DIR))
    print(f"\n🏊 SwimTech 자동 라벨링 시작")
    print(f"   총 비디오: {len(videos)}개  |  최소 감지율: {args.min_detect:.0%}")
    print(f"   기존 라벨: {len(labels)}개\n")

    added = updated = excluded = skipped = 0

    for i, (vpath, top, sub) in enumerate(videos, 1):
        vname = os.path.basename(vpath)
        purpose = CATEGORY_TO_PURPOSE.get(top, top)
        skill   = SKILL_MAP.get(top, "intermediate")

        # 이미 라벨이 있고 overwrite 모드가 아니면 skip
        if vname in labels and not args.overwrite:
            print(f"  [{i}/{len(videos)}] {vname[:50]} — skip (기존 라벨)")
            skipped += 1
            continue

        print(f"  [{i}/{len(videos)}] {vname[:50]}")
        result = analyze_video(vpath, sample_skip=args.skip)

        if "error" in result and result["error"] not in ("insufficient_landmarks",):
            print(f"           ⚠️ 오류: {result['error']}")
            skipped += 1
            continue

        det_rate = result.get("detection_rate", 0.0)
        stroke   = result.get("stroke_type", "unknown")
        conf     = result.get("stroke_confidence", 0.0)

        # 폴더에서 영법 힌트 얻기 (감지 결과보다 우선순위는 낮음)
        folder_stroke = _stroke_from_subfolder(sub)

        # 감지율 부족 → 제외
        if det_rate < args.min_detect:
            label_entry = {
                "stroke_type":       folder_stroke,
                "skill_level":       skill,
                "purpose_tag":       purpose,
                "source":            sub,
                "stroke_confidence": 0.0,
                "detection_rate":    det_rate,
                "excluded":          True,
                "auto_labeled":      True,
            }
            status = "❌ 제외 (감지율 부족)"
            excluded += 1
        else:
            # 영법: MediaPipe 감지 신뢰도가 낮으면 폴더 힌트 사용
            final_stroke = stroke if conf >= 0.60 else folder_stroke
            label_entry = {
                "stroke_type":       final_stroke,
                "skill_level":       skill,
                "purpose_tag":       purpose,
                "source":            sub,
                "stroke_confidence": conf if conf >= 0.60 else 0.5,
                "detection_rate":    det_rate,
                "excluded":          False,
                "auto_labeled":      True,
            }
            if vname in labels:
                status = "♻️ 업데이트"
                updated += 1
            else:
                status = "✅ 추가"
                added += 1

        print(f"           {status}  감지율={det_rate:.0%}  영법={label_entry['stroke_type']}(conf={conf:.2f})  목적={purpose}")
        labels[vname] = label_entry

    print(f"\n{'='*55}")
    print(f"  결과: 추가={added}  업데이트={updated}  제외={excluded}  건너뜀={skipped}")

    excluded_list = [v for v, l in labels.items() if l.get("excluded")]
    if excluded_list:
        print(f"\n  ⚠️ 제외된 영상 ({len(excluded_list)}개):")
        for v in excluded_list[:10]:
            print(f"     - {v}")
        if len(excluded_list) > 10:
            print(f"     ... 외 {len(excluded_list)-10}개")

    if not args.dry_run:
        save_labels(labels)
        print(f"\n  💾 {LABELS_PATH}  (총 {len(labels)}개)")
    else:
        print(f"\n  [dry-run] 저장하지 않음")

    print("\n✅ 자동 라벨링 완료!")
    print("다음 단계: python analysis/train/02_extract_features.py")


if __name__ == "__main__":
    main()

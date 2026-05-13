"""
SwimTech — Step 3. 모델 학습 (3-Track 버전)

각 트랙별로 독립적인 모델을 학습합니다.

Track 1. Competition  → stroke 분류 (자유형/배영/평영/접영/혼영)
Track 2. Tutorial     → stroke 분류 + 자세 점수
Track 3. Start & Turn → 동작 분류 (start/flip_turn/touch_turn/streamline)

실행:
    python analysis/train/03_train_model.py
    python analysis/train/03_train_model.py --track competition
    python analysis/train/03_train_model.py --track start_turn
"""
import os, sys, argparse, json, warnings
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.svm import SVC
from sklearn.model_selection import train_test_split, cross_val_score, StratifiedKFold
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import classification_report, confusion_matrix
warnings.filterwarnings("ignore")

BASE_DIR  = os.path.join(os.path.dirname(__file__), "data")
MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "models")

CSV_PATHS = {
    "competition": os.path.join(BASE_DIR, "features_competition.csv"),
    "tutorial":    os.path.join(BASE_DIR, "features_tutorial.csv"),
    "start_turn":  os.path.join(BASE_DIR, "features_start_turn.csv"),
}
MODEL_NAMES = {
    "competition": "model_competition.joblib",
    "tutorial":    "model_tutorial.joblib",
    "start_turn":  "model_start_turn.joblib",
}
ENCODER_NAMES = {
    "competition": "encoder_competition.joblib",
    "tutorial":    "encoder_tutorial.joblib",
    "start_turn":  "encoder_start_turn.joblib",
}

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


def train_track(track: str):
    csv_path  = CSV_PATHS[track]
    if not os.path.exists(csv_path):
        print(f"  ❌ {csv_path} 없음 → 02_extract_features.py 먼저 실행")
        return

    df = pd.read_csv(csv_path)
    print(f"  데이터: {len(df)}개")
    print(f"  레이블 분포:\n{df['label'].value_counts().to_string()}")

    if df["label"].value_counts().min() < 3:
        print(f"  ⚠️  일부 레이블 데이터 부족 (최소 5개 이상 권장)")

    X   = df[FEATURE_COLS].fillna(0).values
    le  = LabelEncoder()
    y   = le.fit_transform(df["label"].values)

    print(f"\n  클래스: {list(le.classes_)}")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    candidates = {
        "RandomForest": Pipeline([
            ("sc", StandardScaler()),
            ("clf", RandomForestClassifier(n_estimators=200, max_depth=10, random_state=42))
        ]),
        "GradientBoosting": Pipeline([
            ("sc", StandardScaler()),
            ("clf", GradientBoostingClassifier(n_estimators=100, random_state=42))
        ]),
        "SVM": Pipeline([
            ("sc", StandardScaler()),
            ("clf", SVC(kernel="rbf", probability=True, random_state=42))
        ]),
    }

    cv = StratifiedKFold(n_splits=min(5, df["label"].value_counts().min()), shuffle=True, random_state=42)
    print(f"\n  ── 모델 비교 ──────────────────────────────")
    best_name, best_score, best_model = None, 0, None

    for name, model in candidates.items():
        try:
            scores = cross_val_score(model, X_train, y_train, cv=cv, scoring="accuracy")
            mean, std = scores.mean(), scores.std()
            print(f"    {name:20s}: {mean:.3f} ± {std:.3f}")
            if mean > best_score:
                best_score, best_name, best_model = mean, name, model
        except Exception as e:
            print(f"    {name:20s}: 실패 ({e})")

    if best_model is None:
        print("  ❌ 학습 실패")
        return

    print(f"\n  🏆 최고: {best_name} ({best_score:.3f})")
    best_model.fit(X_train, y_train)

    y_pred = best_model.predict(X_test)
    print(f"\n  ── 테스트 결과 ────────────────────────────")
    print(classification_report(y_test, y_pred, target_names=le.classes_))

    # 저장
    os.makedirs(MODEL_DIR, exist_ok=True)
    model_path   = os.path.join(MODEL_DIR, MODEL_NAMES[track])
    encoder_path = os.path.join(MODEL_DIR, ENCODER_NAMES[track])
    info_path    = os.path.join(MODEL_DIR, f"info_{track}.json")

    joblib.dump(best_model, model_path)
    joblib.dump(le,         encoder_path)

    info = {
        "track":       track,
        "model_name":  best_name,
        "cv_accuracy": round(best_score, 4),
        "classes":     list(le.classes_),
        "feature_cols": FEATURE_COLS,
        "train_size":  len(X_train),
        "test_size":   len(X_test),
    }
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    print(f"\n  💾 모델 저장: {model_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--track",
        choices=["competition","tutorial","start_turn","all"],
        default="all")
    args = parser.parse_args()

    tracks = ["competition","tutorial","start_turn"] if args.track == "all" else [args.track]

    for track in tracks:
        print(f"\n{'='*50}\n  Track: {track}\n{'='*50}")
        train_track(track)

    print("\n✅ 학습 완료!")
    print("다음 단계: python analysis/train/04_evaluate_model.py")


if __name__ == "__main__":
    main()

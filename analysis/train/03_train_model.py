"""
SwimTech — Step 3. 모델 학습 (v2.0)

학습 모델:
  stroke_classifier.pkl  — 영법 분류 (RandomForest, 5-fold CV)
  score_competition.pkl  — 대회 적합도 점수 (GradientBoosting)
  score_health.pkl       — 건강 적합도 점수
  score_tutorial.pkl     — 교습 적합도 점수
  score_masters.pkl      — 마스터즈 적합도 점수

실행:
    python analysis/train/03_train_model.py
    python analysis/train/03_train_model.py --mode stroke
    python analysis/train/03_train_model.py --mode score
"""
import os, sys, argparse, json, warnings
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, GradientBoostingRegressor
from sklearn.svm import SVC
from sklearn.model_selection import StratifiedKFold, KFold, cross_val_score, train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import classification_report, confusion_matrix, f1_score, mean_absolute_error
warnings.filterwarnings("ignore")

BASE_DIR  = os.path.join(os.path.dirname(__file__), "data")
MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "models")
SUMMARY_CSV = os.path.join(BASE_DIR, "features_summary.csv")

# 학습에 사용할 기본 특징 컬럼 (summarize_video 출력 기준)
_STAT_BASES = [
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
BASE_FEATURE_COLS = (
    [f"{b}_{s}" for b in _STAT_BASES for s in ("mean", "std", "min")]
    + ["kick_frequency", "kick_ratio", "stroke_cycle_hz"]
)

PURPOSE_TAGS   = ["competition", "health", "technique", "hobby"]
VALID_STROKES  = {"freestyle", "backstroke", "breaststroke", "butterfly"}


def _available_cols(df: pd.DataFrame, cols: list) -> list:
    """df에 실제로 있는 컬럼만 반환"""
    return [c for c in cols if c in df.columns]


def _load_summary(min_samples: int = 2) -> pd.DataFrame:
    if not os.path.exists(SUMMARY_CSV):
        raise FileNotFoundError(
            f"{SUMMARY_CSV} 없음\n먼저 실행: python analysis/train/02_extract_features.py"
        )
    df = pd.read_csv(SUMMARY_CSV)
    print(f"  로드: {len(df)}개 비디오")

    before = len(df)
    if "stroke_label" in df.columns:
        df = df[df["stroke_label"] != "medley"]
    if "category" in df.columns:
        df = df[df["category"] != "medley"]
    excluded = before - len(df)
    if excluded > 0:
        print(f"  medley 제외: {excluded}개 → {len(df)}개 남음")

    return df


def _build_X(df: pd.DataFrame, feature_cols: list) -> np.ndarray:
    cols = _available_cols(df, feature_cols)
    return df[cols].fillna(0).values


# ── 영법 분류 모델 ──────────────────────────────────────────────────────

def train_stroke_classifier(df: pd.DataFrame):
    print(f"\n{'='*55}")
    print("  [1] 영법 분류 모델 (stroke_classifier)")
    print(f"{'='*55}")

    # 4개 유효 영법 클래스만 사용 (medley/unknown 제외)
    df_s = df[
        df["stroke_label"].notna() &
        (df["stroke_label"] != "unknown") &
        (df["stroke_label"] != "medley") &
        (df["stroke_label"].isin(VALID_STROKES))
    ].copy()
    if len(df_s) < 6:
        print(f"  ❌ 유효 데이터 부족 ({len(df_s)}개, 최소 6개 필요)")
        return

    feat_cols = _available_cols(df_s, BASE_FEATURE_COLS)
    X = df_s[feat_cols].fillna(0).values
    le = LabelEncoder()
    y  = le.fit_transform(df_s["stroke_label"].values)

    print(f"  클래스: {list(le.classes_)}  |  샘플: {len(df_s)}개")

    min_class = df_s["stroke_label"].value_counts().min()
    n_splits  = min(5, min_class)
    if n_splits < 2:
        print("  ⚠️  일부 클래스 샘플 너무 적음 (최소 2개 필요)")
        n_splits = 2

    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42,
                                               stratify=y if min_class >= 2 else None)
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)

    candidates = {
        "RandomForest": Pipeline([
            ("sc",  StandardScaler()),
            ("clf", RandomForestClassifier(n_estimators=200, max_depth=10, random_state=42)),
        ]),
        "GradientBoosting": Pipeline([
            ("sc",  StandardScaler()),
            ("clf", GradientBoostingClassifier(n_estimators=100, random_state=42)),
        ]),
        "SVM": Pipeline([
            ("sc",  StandardScaler()),
            ("clf", SVC(kernel="rbf", probability=True, random_state=42)),
        ]),
    }

    print(f"\n  ── 5-fold 교차검증 ──────────────────────────")
    best_name, best_score, best_model = None, 0.0, None
    for name, model in candidates.items():
        try:
            scores = cross_val_score(model, X_tr, y_tr, cv=cv, scoring="accuracy")
            mean, std = scores.mean(), scores.std()
            print(f"    {name:22s}: {mean:.3f} ± {std:.3f}")
            if mean > best_score:
                best_score, best_name, best_model = mean, name, model
        except Exception as e:
            print(f"    {name:22s}: 실패 ({e})")

    if best_model is None:
        print("  ❌ 학습 실패")
        return

    print(f"\n  🏆 최고: {best_name}  CV={best_score:.3f}")
    best_model.fit(X_tr, y_tr)

    y_pred = best_model.predict(X_te)
    print(f"\n  ── 테스트 결과 ──────────────────────────────")
    print(classification_report(y_te, y_pred, target_names=le.classes_, zero_division=0))

    os.makedirs(MODEL_DIR, exist_ok=True)
    model_path   = os.path.join(MODEL_DIR, "stroke_classifier.pkl")
    encoder_path = os.path.join(MODEL_DIR, "stroke_classifier_encoder.pkl")
    info_path    = os.path.join(MODEL_DIR, "stroke_classifier_info.json")

    joblib.dump(best_model, model_path)
    joblib.dump(le, encoder_path)
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump({
            "model_name":   best_name,
            "cv_accuracy":  round(best_score, 4),
            "classes":      list(le.classes_),
            "feature_cols": feat_cols,
            "train_size":   len(X_tr),
            "test_size":    len(X_te),
        }, f, ensure_ascii=False, indent=2)

    # 하위 호환: 기존 track별 파일명으로도 저장
    joblib.dump(best_model, os.path.join(MODEL_DIR, "model_competition.joblib"))
    joblib.dump(le,         os.path.join(MODEL_DIR, "encoder_competition.joblib"))

    print(f"\n  💾 {model_path}")
    print(f"  💾 {encoder_path}")


# ── 목적별 점수 모델 ────────────────────────────────────────────────────

def train_score_model(df: pd.DataFrame, purpose: str):
    """
    Soft label 회귀 방식:
      해당 목적 카테고리 = 1.0, 나머지 = 0.3
    GradientBoostingRegressor → predict()로 0~1 점수 출력
    """
    print(f"\n  ── score_{purpose} ─────────────────────────")

    if "purpose_tag" not in df.columns:
        print("    ❌ purpose_tag 컬럼 없음")
        return

    # Soft labels: 해당 목적=1.0, 나머지=0.3
    y_soft = np.where(df["purpose_tag"] == purpose, 1.0, 0.3)
    pos_n  = int((y_soft == 1.0).sum())
    neg_n  = int((y_soft == 0.3).sum())

    if pos_n < 3 or neg_n < 3:
        print(f"    ⚠️  샘플 부족 (positive={pos_n}, negative={neg_n}, 각 3개 이상 필요) → skip")
        return

    feat_cols = _available_cols(df, BASE_FEATURE_COLS)
    X = df[feat_cols].fillna(0).values

    n_splits = min(5, min(pos_n, neg_n, len(df)))
    cv = KFold(n_splits=n_splits, shuffle=True, random_state=42)

    model = Pipeline([
        ("sc",  StandardScaler()),
        ("reg", GradientBoostingRegressor(n_estimators=150, max_depth=4,
                                          learning_rate=0.1, random_state=42)),
    ])

    mae_scores = -cross_val_score(model, X, y_soft, cv=cv,
                                  scoring="neg_mean_absolute_error")
    print(f"    MAE (5-fold): {mae_scores.mean():.4f} ± {mae_scores.std():.4f}  "
          f"[pos={pos_n}, neg={neg_n}]")

    model.fit(X, y_soft)

    # 학습 데이터 전체 MAE
    y_pred  = model.predict(X)
    mae_all = mean_absolute_error(y_soft, y_pred)
    rmse_all = float(np.sqrt(np.mean((y_soft - y_pred) ** 2)))
    print(f"    학습 MAE={mae_all:.4f}  RMSE={rmse_all:.4f}")

    os.makedirs(MODEL_DIR, exist_ok=True)
    model_path = os.path.join(MODEL_DIR, f"score_{purpose}.pkl")
    info_path  = os.path.join(MODEL_DIR, f"score_{purpose}_info.json")

    joblib.dump(model, model_path)
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump({
            "purpose":       purpose,
            "model_type":    "regressor",
            "cv_mae_mean":   round(float(mae_scores.mean()), 4),
            "cv_mae_std":    round(float(mae_scores.std()),  4),
            "train_mae":     round(mae_all,  4),
            "train_rmse":    round(rmse_all, 4),
            "pos_samples":   int(pos_n),
            "neg_samples":   int(neg_n),
            "feature_cols":  feat_cols,
        }, f, ensure_ascii=False, indent=2)

    print(f"    💾 {model_path}")


# ── 메인 ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["stroke", "score", "all"], default="all",
                        help="학습 모드: stroke=영법분류, score=목적별점수, all=전체")
    args = parser.parse_args()

    print("\n🏊 SwimTech 모델 학습 시작")
    df = _load_summary()

    if df.empty:
        print("❌ 데이터 없음 — 먼저 02_extract_features.py 실행")
        return

    print(f"\n  purpose_tag 분포:\n{df['purpose_tag'].value_counts().to_string()}")
    if "stroke_label" in df.columns:
        print(f"\n  stroke_label 분포:\n{df['stroke_label'].value_counts().to_string()}")

    if args.mode in ("stroke", "all"):
        train_stroke_classifier(df)

    if args.mode in ("score", "all"):
        print(f"\n{'='*55}")
        print("  [2] 목적별 점수 모델 (score_competition/health/technique/hobby)")
        print(f"{'='*55}")
        for purpose in PURPOSE_TAGS:
            train_score_model(df, purpose)

    # feature_columns.pkl 저장
    os.makedirs(MODEL_DIR, exist_ok=True)
    feat_cols = _available_cols(df, BASE_FEATURE_COLS)
    feat_path = os.path.join(MODEL_DIR, "feature_columns.pkl")
    joblib.dump(feat_cols, feat_path)
    print(f"\n  💾 {feat_path}  ({len(feat_cols)}개 컬럼)")

    print("\n✅ 학습 완료!")
    print("다음 단계: python analysis/train/04_evaluate_model.py")


if __name__ == "__main__":
    main()

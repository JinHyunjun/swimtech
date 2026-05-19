"""
SwimTech — Step 4. 모델 평가 (신규)

- 테스트 영상 최대 10개로 모델 평가
- 예측값 vs 실제값 비교 리포트
- 혼동 행렬 출력
- 목적별(purpose_tag) 정확도 분석

실행:
    python analysis/train/04_evaluate_model.py
    python analysis/train/04_evaluate_model.py --n 20
    python analysis/train/04_evaluate_model.py --source summary   # CSV에서 평가
"""
import os, sys, json, random, argparse
import numpy as np
import pandas as pd
import joblib

BASE_DIR  = os.path.join(os.path.dirname(__file__), "data")
MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "models")
SUMMARY_CSV = os.path.join(BASE_DIR, "features_summary.csv")


def _load_model(name: str):
    path = os.path.join(MODEL_DIR, name)
    if not os.path.exists(path):
        return None
    return joblib.load(path)


def _load_info(name: str) -> dict:
    path = os.path.join(MODEL_DIR, name)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _get_feature_cols(info: dict, df: pd.DataFrame) -> list:
    cols = info.get("feature_cols", [])
    return [c for c in cols if c in df.columns]


def _confusion_matrix_str(cm: np.ndarray, classes: list) -> str:
    """혼동 행렬을 텍스트 테이블로 반환"""
    col_w = max(max(len(c) for c in classes), 6)
    header = " " * (col_w + 2) + "  ".join(f"{c:>{col_w}}" for c in classes)
    lines  = [header, "-" * len(header)]
    for i, row_class in enumerate(classes):
        row = f"{row_class:>{col_w}}  " + "  ".join(f"{cm[i][j]:>{col_w}}" for j in range(len(classes)))
        lines.append(row)
    return "\n".join(lines)


def evaluate_stroke_classifier(df: pd.DataFrame):
    print(f"\n{'='*60}")
    print("  [1] 영법 분류 모델 평가 (stroke_classifier)")
    print(f"{'='*60}")

    model   = _load_model("stroke_classifier.pkl")
    encoder = _load_model("stroke_classifier_encoder.pkl")
    info    = _load_info("stroke_classifier_info.json")

    if model is None or encoder is None:
        print("  ❌ stroke_classifier.pkl 없음 — 먼저 03_train_model.py 실행")
        return

    df_s = df[df["stroke_label"].notna() & (df["stroke_label"] != "unknown")].copy()
    if df_s.empty:
        print("  ❌ 영법 레이블 데이터 없음")
        return

    feat_cols = _get_feature_cols(info, df_s)
    if not feat_cols:
        feat_cols = [c for c in df_s.columns if c not in
                     ("video_id", "category", "purpose_tag", "stroke_label", "detection_rate")]

    X_all = df_s[feat_cols].fillna(0).values
    y_true_str = df_s["stroke_label"].values

    # 알려진 클래스만 평가
    known = set(encoder.classes_)
    mask  = [l in known for l in y_true_str]
    if not any(mask):
        print("  ⚠️  알려진 클래스 없음 (학습 클래스와 테스트 클래스 불일치)")
        return

    X_eval      = X_all[mask]
    y_true_eval = y_true_str[mask]
    y_pred_enc  = model.predict(X_eval)
    y_pred_str  = encoder.inverse_transform(y_pred_enc)

    # 전체 정확도
    accuracy = (y_pred_str == y_true_eval).mean()
    print(f"\n  전체 정확도: {accuracy:.3f}  ({sum(y_pred_str == y_true_eval)}/{len(y_true_eval)}개)")

    # 클래스별 리포트
    classes = sorted(set(y_true_eval) | set(y_pred_str))
    print(f"\n  ── 클래스별 예측 결과 ───────────────────────")
    for cls in classes:
        mask_c  = y_true_eval == cls
        correct = (y_pred_str[mask_c] == cls).sum() if mask_c.any() else 0
        total_c = mask_c.sum()
        print(f"    {cls:15s}: {correct}/{total_c}  ({correct/total_c:.0%})" if total_c > 0 else f"    {cls}: 0샘플")

    # 혼동 행렬
    label_set = encoder.classes_
    try:
        from sklearn.metrics import confusion_matrix
        cm = confusion_matrix(y_true_eval, y_pred_str, labels=label_set)
        print(f"\n  ── 혼동 행렬 ───────────────────────────────")
        print(_confusion_matrix_str(cm, list(label_set)))
    except Exception as e:
        print(f"  ⚠️ 혼동 행렬 생성 실패: {e}")

    # 예측 vs 실제 샘플 10개
    print(f"\n  ── 예측 vs 실제 (샘플 10개) ─────────────────")
    idxs = list(range(len(y_true_eval)))
    random.shuffle(idxs)
    for i in idxs[:10]:
        correct_mark = "✅" if y_pred_str[i] == y_true_eval[i] else "❌"
        vid = df_s.iloc[np.where(mask)[0][i]].get("video_id", "?") if hasattr(df_s, "iloc") else "?"
        print(f"    {correct_mark} 실제={y_true_eval[i]:15s}  예측={y_pred_str[i]:15s}  video={str(vid)[:35]}")


def evaluate_score_models(df: pd.DataFrame, purposes: list):
    print(f"\n{'='*60}")
    print("  [2] 목적별 점수 모델 평가")
    print(f"{'='*60}")

    for purpose in purposes:
        model = _load_model(f"score_{purpose}.pkl")
        info  = _load_info(f"score_{purpose}_info.json")
        if model is None:
            print(f"\n  score_{purpose}.pkl — 없음 (skip)")
            continue

        print(f"\n  ── score_{purpose} ─────────────────────────")
        feat_cols = _get_feature_cols(info, df)
        if not feat_cols:
            feat_cols = [c for c in df.columns if c not in
                         ("video_id", "category", "purpose_tag", "stroke_label", "detection_rate")]

        X      = df[feat_cols].fillna(0).values
        y_true = (df["purpose_tag"] == purpose).astype(int).values if "purpose_tag" in df.columns else None

        scores_proba = model.predict_proba(X)[:, 1]
        y_pred_bin   = (scores_proba >= 0.5).astype(int)

        if y_true is not None:
            pos_n = y_true.sum()
            neg_n = len(y_true) - pos_n
            tp = ((y_pred_bin == 1) & (y_true == 1)).sum()
            fp = ((y_pred_bin == 1) & (y_true == 0)).sum()
            fn = ((y_pred_bin == 0) & (y_true == 1)).sum()
            tn = ((y_pred_bin == 0) & (y_true == 0)).sum()
            acc = (tp + tn) / len(y_true)
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0
            rec  = tp / (tp + fn) if (tp + fn) > 0 else 0
            f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0

            print(f"    양성={pos_n}  음성={neg_n}  |  정확도={acc:.3f}  정밀도={prec:.3f}  재현율={rec:.3f}  F1={f1:.3f}")
            print(f"    혼동행렬: TP={tp} FP={fp} FN={fn} TN={tn}")

        # 목적별 평균 점수
        if "purpose_tag" in df.columns:
            print(f"    ── 목적별 평균 예측 점수 ────────────────")
            for tag in df["purpose_tag"].dropna().unique():
                mask = df["purpose_tag"] == tag
                mean_score = scores_proba[mask].mean()
                bar = "█" * int(mean_score * 20)
                print(f"      {tag:12s}: {mean_score:.3f}  {bar}")


def evaluate_from_csv(n: int = 10, purposes: list = None):
    if purposes is None:
        purposes = ["competition", "health", "tutorial", "masters"]

    if not os.path.exists(SUMMARY_CSV):
        print(f"❌ {SUMMARY_CSV} 없음 — 먼저 02_extract_features.py 실행")
        return

    df = pd.read_csv(SUMMARY_CSV)
    print(f"  로드: {len(df)}개 비디오")

    # 최대 n개 샘플 (카테고리 균형 유지)
    if len(df) > n and "purpose_tag" in df.columns:
        per_cat = max(1, n // df["purpose_tag"].nunique())
        df_eval = df.groupby("purpose_tag").apply(
            lambda g: g.sample(min(len(g), per_cat), random_state=42)
        ).reset_index(drop=True)
    else:
        df_eval = df.sample(min(n, len(df)), random_state=42)

    print(f"  평가 샘플: {len(df_eval)}개")

    evaluate_stroke_classifier(df_eval)
    evaluate_score_models(df_eval, purposes)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=10, help="평가 샘플 수 (기본: 10)")
    parser.add_argument("--source", choices=["summary"], default="summary",
                        help="평가 데이터 소스")
    parser.add_argument("--purposes", nargs="+",
                        default=["competition", "health", "tutorial", "masters"])
    args = parser.parse_args()

    print("\n🏊 SwimTech 모델 평가 시작")
    evaluate_from_csv(n=args.n, purposes=args.purposes)
    print("\n✅ 평가 완료!")


if __name__ == "__main__":
    main()

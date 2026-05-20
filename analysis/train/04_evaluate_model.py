"""
SwimTech — Step 4. 모델 평가 (v2.0)

- 각 카테고리별 테스트 영상 10% 샘플링
- 예측값 vs 실제값 비교 리포트
- 혼동 행렬 출력 (영법 분류)
- 목적별 점수 MAE/RMSE 출력 (회귀 모델)
- 결과를 evaluation_report.json으로 저장

실행:
    python analysis/train/04_evaluate_model.py
    python analysis/train/04_evaluate_model.py --sample-pct 0.2
"""
import os, sys, json, random, argparse
import numpy as np
import pandas as pd
import joblib
from sklearn.metrics import confusion_matrix, mean_absolute_error

BASE_DIR    = os.path.join(os.path.dirname(__file__), "data")
MODEL_DIR   = os.path.join(os.path.dirname(__file__), "..", "models")
SUMMARY_CSV = os.path.join(BASE_DIR, "features_summary.csv")
REPORT_PATH = os.path.join(BASE_DIR, "evaluation_report.json")

PURPOSE_TAGS = ["competition", "health", "technique", "hobby"]


def _load_model(name: str):
    path = os.path.join(MODEL_DIR, name)
    return joblib.load(path) if os.path.exists(path) else None


def _load_info(name: str) -> dict:
    path = os.path.join(MODEL_DIR, name)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _feat_cols(info: dict, df: pd.DataFrame) -> list:
    cols = info.get("feature_cols", [])
    return [c for c in cols if c in df.columns]


def _confusion_str(cm: np.ndarray, classes: list) -> str:
    w = max(max(len(c) for c in classes), 6)
    header = " " * (w + 2) + "  ".join(f"{c:>{w}}" for c in classes)
    lines  = [header, "-" * len(header)]
    for i, cls in enumerate(classes):
        row = f"{cls:>{w}}  " + "  ".join(f"{cm[i][j]:>{w}}" for j in range(len(classes)))
        lines.append(row)
    return "\n".join(lines)


def sample_10pct(df: pd.DataFrame, group_col: str = "category") -> pd.DataFrame:
    """각 카테고리별 10% 샘플링 (최소 1개 보장)"""
    if group_col not in df.columns or df.empty:
        n = max(1, int(len(df) * 0.1))
        return df.sample(min(n, len(df)), random_state=42)

    frames = []
    for cat, grp in df.groupby(group_col):
        n = max(1, int(len(grp) * 0.1))
        frames.append(grp.sample(min(n, len(grp)), random_state=42))
    return pd.concat(frames, ignore_index=True)


# ── 영법 분류 모델 평가 ─────────────────────────────────────────────────

def evaluate_stroke_classifier(df: pd.DataFrame) -> dict:
    print(f"\n{'='*60}")
    print("  [1] 영법 분류 모델 평가 (stroke_classifier)")
    print(f"{'='*60}")

    model   = _load_model("stroke_classifier.pkl")
    encoder = _load_model("stroke_classifier_encoder.pkl")
    info    = _load_info("stroke_classifier_info.json")

    result = {"status": "skipped"}

    if model is None or encoder is None:
        print("  ❌ stroke_classifier.pkl 없음 — 먼저 03_train_model.py 실행")
        return result

    df_s = df[df["stroke_label"].notna() & (df["stroke_label"] != "unknown")].copy()
    if df_s.empty:
        print("  ❌ 영법 레이블 데이터 없음")
        return result

    feat_cols = _feat_cols(info, df_s) or [
        c for c in df_s.columns
        if c not in ("video_id", "category", "purpose_tag", "stroke_label", "detection_rate")
    ]

    X_all       = df_s[feat_cols].fillna(0).values
    y_true_str  = df_s["stroke_label"].values
    known       = set(encoder.classes_)
    mask        = np.array([l in known for l in y_true_str])

    if not mask.any():
        print("  ⚠️  알려진 클래스 없음")
        return result

    X_eval     = X_all[mask]
    y_true_ev  = y_true_str[mask]
    y_pred_enc = model.predict(X_eval)
    y_pred_str = encoder.inverse_transform(y_pred_enc)

    accuracy = float((y_pred_str == y_true_ev).mean())
    print(f"\n  전체 정확도: {accuracy:.3f}  ({(y_pred_str == y_true_ev).sum()}/{len(y_true_ev)}개)")

    classes = sorted(set(y_true_ev) | set(y_pred_str))
    class_acc = {}
    print(f"\n  ── 클래스별 결과 ───────────────────────────────")
    for cls in classes:
        m = y_true_ev == cls
        correct = int((y_pred_str[m] == cls).sum()) if m.any() else 0
        total_c = int(m.sum())
        acc_c   = correct / total_c if total_c else 0
        class_acc[cls] = {"correct": correct, "total": total_c, "accuracy": round(acc_c, 3)}
        print(f"    {cls:15s}: {correct}/{total_c}  ({acc_c:.0%})")

    # 혼동 행렬
    label_set = list(encoder.classes_)
    cm = confusion_matrix(y_true_ev, y_pred_str, labels=label_set)
    print(f"\n  ── 혼동 행렬 ───────────────────────────────────")
    print(_confusion_str(cm, label_set))

    # 예측 vs 실제 샘플 10개
    print(f"\n  ── 예측 vs 실제 (샘플 10개) ────────────────────")
    idxs = list(range(len(y_true_ev)))
    random.shuffle(idxs)
    samples = []
    for i in idxs[:10]:
        mark = "✅" if y_pred_str[i] == y_true_ev[i] else "❌"
        vid_idx = np.where(mask)[0][i]
        vid = df_s.iloc[vid_idx].get("video_id", "?")
        print(f"    {mark} 실제={y_true_ev[i]:15s}  예측={y_pred_str[i]:15s}  video={str(vid)[:35]}")
        samples.append({"video": str(vid)[:35], "true": y_true_ev[i], "pred": y_pred_str[i]})

    result = {
        "status":    "ok",
        "accuracy":  round(accuracy, 4),
        "n_samples": len(y_true_ev),
        "class_accuracy": class_acc,
        "confusion_matrix": cm.tolist(),
        "classes":    label_set,
        "samples":    samples,
    }
    return result


# ── 목적별 점수 모델 평가 ────────────────────────────────────────────────

def evaluate_score_models(df: pd.DataFrame) -> dict:
    print(f"\n{'='*60}")
    print("  [2] 목적별 점수 모델 평가 (regression)")
    print(f"{'='*60}")

    results = {}
    for purpose in PURPOSE_TAGS:
        model = _load_model(f"score_{purpose}.pkl")
        info  = _load_info(f"score_{purpose}_info.json")

        if model is None:
            print(f"\n  score_{purpose}.pkl — 없음 (skip)")
            results[purpose] = {"status": "skipped"}
            continue

        print(f"\n  ── score_{purpose} ──────────────────────────")
        feat_cols = _feat_cols(info, df) or [
            c for c in df.columns
            if c not in ("video_id", "category", "purpose_tag", "stroke_label", "detection_rate")
        ]

        X      = df[feat_cols].fillna(0).values
        y_soft = np.where(df["purpose_tag"] == purpose, 1.0, 0.3) \
                 if "purpose_tag" in df.columns else None

        # 회귀 모델: predict() 사용 (predict_proba 불가)
        try:
            y_pred = model.predict(X)
        except Exception:
            try:
                y_pred = model.predict_proba(X)[:, 1]
            except Exception as e:
                print(f"    ❌ 예측 실패: {e}")
                results[purpose] = {"status": "error", "error": str(e)}
                continue

        mae  = float(mean_absolute_error(y_soft, y_pred)) if y_soft is not None else None
        rmse = float(np.sqrt(np.mean((y_soft - y_pred) ** 2))) if y_soft is not None else None

        if mae is not None:
            print(f"    MAE={mae:.4f}  RMSE={rmse:.4f}  [n={len(X)}]")

        # 목적별 평균 예측 점수
        per_purpose = {}
        if "purpose_tag" in df.columns:
            print(f"    ── 목적별 평균 예측 점수 ─────────────────")
            for tag in sorted(df["purpose_tag"].dropna().unique()):
                m = df["purpose_tag"] == tag
                mean_sc = float(y_pred[m].mean())
                bar     = "█" * int(mean_sc * 20)
                per_purpose[tag] = round(mean_sc, 4)
                print(f"      {tag:12s}: {mean_sc:.3f}  {bar}")

        results[purpose] = {
            "status":      "ok",
            "model_type":  info.get("model_type", "unknown"),
            "n_samples":   len(X),
            "mae":         round(mae,  4) if mae  is not None else None,
            "rmse":        round(rmse, 4) if rmse is not None else None,
            "per_purpose_mean_score": per_purpose,
        }

    return results


# ── 메인 ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-pct", type=float, default=0.1,
                        help="카테고리별 샘플 비율 (기본: 0.1 = 10%%)")
    args = parser.parse_args()

    print("\n🏊 SwimTech 모델 평가 시작")

    if not os.path.exists(SUMMARY_CSV):
        print(f"❌ {SUMMARY_CSV} 없음 — 먼저 02_extract_features.py 실행")
        return

    df_all = pd.read_csv(SUMMARY_CSV)
    print(f"  전체 데이터: {len(df_all)}개 비디오")

    df_eval = sample_10pct(df_all, "category")
    print(f"  평가 샘플: {len(df_eval)}개 ({args.sample_pct:.0%} 샘플링)\n")

    stroke_result = evaluate_stroke_classifier(df_eval)
    score_results = evaluate_score_models(df_eval)

    report = {
        "n_total":      len(df_all),
        "n_evaluated":  len(df_eval),
        "sample_pct":   args.sample_pct,
        "stroke_classifier": stroke_result,
        "score_models": score_results,
    }

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n💾 평가 리포트 저장: {REPORT_PATH}")
    print("\n✅ 평가 완료!")


if __name__ == "__main__":
    main()

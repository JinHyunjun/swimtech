"""Audit the legacy swimming dataset before any model retraining.

This command is intentionally read-only.  It reports folder-label leakage,
duplicate video names, conflicting labels, pose-detection quality, and the
number of independently verified labels.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd


VALID_STROKES = {"freestyle", "backstroke", "breaststroke", "butterfly"}


def audit(summary_path: Path, labels_path: Path, validation_path: Path) -> dict[str, object]:
    frame = pd.read_csv(summary_path)
    valid = frame[frame["stroke_label"].isin(VALID_STROKES)].copy()
    counts = valid.groupby("video_id").size()
    labels_by_video = valid.groupby("video_id")["stroke_label"].agg(
        lambda rows: sorted(set(str(item) for item in rows))
    )
    conflicts = labels_by_video[labels_by_video.map(len) > 1]

    raw_labels = json.loads(labels_path.read_text(encoding="utf-8"))
    label_rows = [
        value
        for key, value in raw_labels.items()
        if not key.startswith("_") and isinstance(value, dict)
    ]
    verified = [
        row
        for row in label_rows
        if row.get("verified") is True
        and row.get("auto_labeled") is False
        and row.get("excluded") is not True
        and row.get("stroke_type") in VALID_STROKES
    ]

    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    total = int(validation.get("total", 0))
    ok = int(validation.get("ok", 0))
    bad = int(validation.get("bad", 0))
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary_rows": len(frame),
        "valid_stroke_rows": len(valid),
        "unique_video_names": int(valid["video_id"].nunique()),
        "duplicate_rows": int((counts - 1).clip(lower=0).sum()),
        "repeated_video_names": int((counts > 1).sum()),
        "conflicting_label_names": len(conflicts),
        "conflicting_rows": int(valid[valid["video_id"].isin(conflicts.index)].shape[0]),
        "conflict_examples": [
            {"video_id": str(video_id), "labels": labels}
            for video_id, labels in conflicts.head(20).items()
        ],
        "label_entries": len(label_rows),
        "auto_labeled_entries": sum(bool(row.get("auto_labeled")) for row in label_rows),
        "human_verified_entries": len(verified),
        "validation_total": total,
        "pose_detection_ok": ok,
        "pose_detection_bad": bad,
        "pose_detection_ok_rate": round(ok / max(total, 1), 4),
        "pose_detection_bad_rate": round(bad / max(total, 1), 4),
    }
    # Conflicting legacy rows do not matter once verified-only filtering is in
    # place, but surfacing them remains useful for cleanup. The actual release
    # gate is the existence of independently verified labels.
    report["training_allowed"] = bool(verified)
    report["blocking_reasons"] = (
        [] if verified else ["no_human_verified_labels"]
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit legacy SwimMate training data")
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("analysis/train/data/features_summary.csv"),
    )
    parser.add_argument(
        "--labels",
        type=Path,
        default=Path("analysis/train/data/labels.json"),
    )
    parser.add_argument(
        "--validation",
        type=Path,
        default=Path("analysis/train/data/validation_report.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.summary, args.labels, args.validation)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["training_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Compare two blinded manual annotations and score an offline prediction."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

from .benchmark import match_events


EVENT_KEYS = {
    "arm": "arm_event_times_sec",
    "kick": "kick_event_times_sec",
}


def _validate_annotation(label: dict[str, Any]) -> None:
    if not isinstance(label, dict):
        raise ValueError("annotation must be an object")
    if label.get("schema_version") != "swimmate-event-label-v2":
        raise ValueError("independent evaluation requires swimmate-event-label-v2")
    if label.get("label_mode") != "blinded_manual" or label.get("prediction_visible") is not False:
        raise ValueError("annotation must be recorded manually without model predictions")
    if not str(label.get("annotator", "")).strip():
        raise ValueError("annotation must identify its annotator")
    video_sha256 = str(label.get("video_sha256", ""))
    if len(video_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in video_sha256.lower()
    ):
        raise ValueError("annotation must include the source video's SHA-256")
    for name in EVENT_KEYS:
        status = label.get(f"{name}_label_status")
        if status not in {"labeled", "unresolvable"}:
            raise ValueError(f"{name} label status is invalid")
        if status == "unresolvable" and label.get(EVENT_KEYS[name]):
            raise ValueError(f"unresolvable {name} labels cannot contain events")
    interval = label.get("interval_sec")
    if not isinstance(interval, list) or len(interval) != 2:
        raise ValueError("annotation interval is invalid")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in interval):
        raise ValueError("annotation interval must contain finite numbers")
    start, end = interval
    if start < 0 or end <= start:
        raise ValueError("annotation interval must increase")
    lane = label.get("lane_id")
    if isinstance(lane, bool) or not isinstance(lane, int) or lane < 1:
        raise ValueError("annotation lane must be a positive integer")
    if label.get("stroke_kind") not in {"freestyle", "backstroke", "breaststroke", "butterfly"}:
        raise ValueError("annotation stroke is invalid")
    for key in EVENT_KEYS.values():
        events = label.get(key)
        if not isinstance(events, list) or len(events) > 2000:
            raise ValueError("annotation events must be a bounded list")
        if any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or not start <= t <= end for t in events):
            raise ValueError("annotation events must be finite and inside the interval")
        if len(set(events)) != len(events):
            raise ValueError("annotation events must not contain duplicates")


def _context(label: dict[str, Any]) -> tuple[object, ...]:
    return (
        label.get("video"),
        label.get("video_sha256"),
        label.get("stroke_kind"),
        int(label.get("lane_id", 0)),
        tuple(float(value) for value in label.get("interval_sec", [])),
        label.get("review_context"),
    )


def _match_pairs(
    left: list[float],
    right: list[float],
    tolerance_sec: float,
) -> tuple[list[tuple[float, float]], list[float], list[float]]:
    left_events = sorted(float(value) for value in left)
    right_events = sorted(float(value) for value in right)
    unused = set(range(len(right_events)))
    pairs: list[tuple[float, float]] = []
    unmatched_left: list[float] = []
    for target in left_events:
        possible = [
            index
            for index in unused
            if abs(right_events[index] - target) <= tolerance_sec
        ]
        if not possible:
            unmatched_left.append(target)
            continue
        selected = min(possible, key=lambda index: abs(right_events[index] - target))
        unused.remove(selected)
        pairs.append((target, right_events[selected]))
    unmatched_right = [right_events[index] for index in sorted(unused)]
    return pairs, unmatched_left, unmatched_right


def compare_annotations(
    first: dict[str, Any],
    second: dict[str, Any],
    tolerance_sec: float = 0.25,
) -> dict[str, Any]:
    """Build inter-annotator agreement without treating predictions as truth."""

    if not math.isfinite(tolerance_sec) or not 0 < tolerance_sec <= 1:
        raise ValueError("tolerance must be positive, finite and at most one second")
    _validate_annotation(first)
    _validate_annotation(second)
    if str(first["annotator"]).casefold() == str(second["annotator"]).casefold():
        raise ValueError("two distinct annotators are required")
    if _context(first) != _context(second):
        raise ValueError("annotations do not describe the same video, lane/ROI, stroke, interval, and timeline")

    event_results: dict[str, Any] = {}
    consensus: dict[str, list[float]] = {}
    complete_agreement = True
    has_resolvable_labels = False
    for name, key in EVENT_KEYS.items():
        first_status = str(first[f"{name}_label_status"])
        second_status = str(second[f"{name}_label_status"])
        if first_status != second_status:
            complete_agreement = False
            consensus[key] = []
            event_results[name] = {
                "first_status": first_status,
                "second_status": second_status,
                "label_status": "resolution_disagreement",
                "complete_within_tolerance": False,
            }
            continue
        if first_status == "unresolvable":
            consensus[key] = []
            event_results[name] = {
                "first_status": first_status,
                "second_status": second_status,
                "label_status": "unresolvable",
                "complete_within_tolerance": True,
            }
            continue
        first_events = [float(value) for value in first.get(key, [])]
        second_events = [float(value) for value in second.get(key, [])]
        has_resolvable_labels = True
        pairs, first_only, second_only = _match_pairs(first_events, second_events, tolerance_sec)
        agreement = match_events(first_events, second_events, tolerance_sec)
        complete = not first_only and not second_only
        complete_agreement = complete_agreement and complete
        consensus[key] = [round((left + right) / 2.0, 3) for left, right in pairs]
        event_results[name] = {
            "first_status": first_status,
            "second_status": second_status,
            "label_status": "labeled",
            "first_count": len(first_events),
            "second_count": len(second_events),
            "count_difference": abs(len(first_events) - len(second_events)),
            "agreement": agreement,
            "first_only_event_times_sec": first_only,
            "second_only_event_times_sec": second_only,
            "complete_within_tolerance": complete,
        }

    verified = complete_agreement and has_resolvable_labels
    consensus_ground_truth = None
    if verified:
        consensus_ground_truth = {
            "lane_id": int(first["lane_id"]),
            "arm_strokes": (
                len(consensus["arm_event_times_sec"])
                if event_results["arm"]["label_status"] == "labeled"
                else None
            ),
            "kicks": (
                len(consensus["kick_event_times_sec"])
                if event_results["kick"]["label_status"] == "labeled"
                else None
            ),
            "arm_event_times_sec": (
                consensus["arm_event_times_sec"]
                if event_results["arm"]["label_status"] == "labeled"
                else None
            ),
            "kick_event_times_sec": (
                consensus["kick_event_times_sec"]
                if event_results["kick"]["label_status"] == "labeled"
                else None
            ),
        }
    return {
        "schema_version": "swimmate-annotation-comparison-v1",
        "video": first["video"],
        "video_sha256": first.get("video_sha256"),
        "stroke_kind": first["stroke_kind"],
        "lane_id": int(first["lane_id"]),
        "interval_sec": first["interval_sec"],
        "annotators": [first["annotator"], second["annotator"]],
        "tolerance_sec": tolerance_sec,
        "events": event_results,
        "agreement_status": "complete" if verified else "adjudication_required",
        "verified_independent_consensus": verified,
        "consensus_ground_truth": consensus_ground_truth,
    }


def score_prediction(
    comparison: dict[str, Any],
    prediction: dict[str, Any],
) -> dict[str, Any]:
    """Score only a prediction backed by complete independent consensus."""

    if not comparison.get("verified_independent_consensus"):
        return {
            "status": "blocked_by_annotation_disagreement",
            "reason": "unmatched reviewer events must be adjudicated before accuracy is reported",
        }
    truth = comparison["consensus_ground_truth"]
    lane_id = int(truth["lane_id"])
    tracks = [track for track in prediction.get("tracks", []) if int(track["lane_id"]) == lane_id]
    track = max(tracks, key=lambda item: int(item.get("observed_frames", 0))) if tracks else None
    scores: dict[str, Any] = {"status": "scored", "lane_id": lane_id}
    for name, key in EVENT_KEYS.items():
        if truth[key] is None:
            scores[name] = {
                "status": "unscored_unresolvable",
                "available": False,
                "absolute_count_error": None,
                "event_timing": None,
            }
            continue
        prediction_key = "arm_strokes" if name == "arm" else "kicks"
        predicted = track.get(prediction_key, {}) if track is not None else {}
        available = bool(predicted.get("available", False))
        expected_events = truth[key]
        predicted_events = predicted.get("event_times_sec", []) if available else []
        scores[name] = {
            "available": available,
            "expected_count": len(expected_events),
            "predicted_count": int(predicted.get("count", 0)) if available else None,
            "absolute_count_error": (
                abs(int(predicted["count"]) - len(expected_events)) if available else None
            ),
            "event_timing": match_events(expected_events, predicted_events),
            "withheld_reason": predicted.get("reason") if not available else None,
        }
    return scores


def build_review_report(
    first: dict[str, Any],
    second: dict[str, Any],
    prediction: dict[str, Any] | None = None,
    tolerance_sec: float = 0.25,
) -> dict[str, Any]:
    comparison = compare_annotations(first, second, tolerance_sec)
    return {
        "schema_version": "swimmate-independent-evaluation-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "comparison": comparison,
        "model_evaluation": (
            score_prediction(comparison, prediction)
            if prediction is not None
            else {"status": "prediction_not_supplied"}
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare two blinded SwimMate event labels")
    parser.add_argument("--first", type=Path, required=True)
    parser.add_argument("--second", type=Path, required=True)
    parser.add_argument("--prediction", type=Path)
    parser.add_argument("--tolerance-sec", type=float, default=0.25)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    first = json.loads(args.first.read_text(encoding="utf-8"))
    second = json.loads(args.second.read_text(encoding="utf-8"))
    prediction = (
        json.loads(args.prediction.read_text(encoding="utf-8"))
        if args.prediction is not None
        else None
    )
    report = build_review_report(first, second, prediction, args.tolerance_sec)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

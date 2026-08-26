"""Build a compact, deterministic comparison from offline benchmark runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _best_tracks_by_lane(result: dict[str, Any]) -> dict[int, dict[str, Any]]:
    tracks: dict[int, dict[str, Any]] = {}
    for track in result.get("tracks", []):
        lane_id = int(track["lane_id"])
        current = tracks.get(lane_id)
        if current is None or int(track["observed_frames"]) > int(current["observed_frames"]):
            tracks[lane_id] = track
    return tracks


def _event_value(track: dict[str, Any], key: str) -> int | None:
    event = track[key]
    return int(event["count"]) if event["available"] else None


def _aggregate(payload: dict[str, Any]) -> dict[str, Any]:
    means: list[float] = []
    processed_frames = 0
    elapsed = 0.0
    stable_tracks = arm_outputs = kick_outputs = 0
    per_stroke: dict[str, dict[str, Any]] = {}
    suspected_cuts = 0
    for result in payload["results"]:
        benchmark = result["benchmark"]
        stroke_kind = result["stroke_kind"]
        means.append(float(benchmark["mean_detected_lanes"]))
        processed_frames += int(benchmark["processed_frames"])
        elapsed += float(benchmark["elapsed_sec"])
        suspected_cuts += len(benchmark.get("scene_stability", {}).get("suspected_cuts", []))
        stroke = per_stroke.setdefault(
            stroke_kind,
            {
                "sample_count": 0,
                "mean_detected_lanes_values": [],
                "stable_tracks": 0,
                "arm_count_outputs": 0,
                "kick_count_outputs": 0,
            },
        )
        stroke["sample_count"] += 1
        stroke["mean_detected_lanes_values"].append(float(benchmark["mean_detected_lanes"]))
        for track in result["tracks"]:
            stable = float(track["track_coverage"]) >= 0.60
            arm = bool(track["arm_strokes"]["available"])
            kick = bool(track["kicks"]["available"])
            stable_tracks += int(stable)
            arm_outputs += int(arm)
            kick_outputs += int(kick)
            stroke["stable_tracks"] += int(stable)
            stroke["arm_count_outputs"] += int(arm)
            stroke["kick_count_outputs"] += int(kick)

    for stroke in per_stroke.values():
        values = stroke.pop("mean_detected_lanes_values")
        stroke["mean_detected_lanes"] = round(sum(values) / max(len(values), 1), 3)
    return {
        "sample_count": len(payload["results"]),
        "mean_detected_lanes": round(sum(means) / max(len(means), 1), 3),
        "stable_tracks": stable_tracks,
        "arm_count_outputs": arm_outputs,
        "kick_count_outputs": kick_outputs,
        "processed_frames": processed_frames,
        "inference_fps": round(processed_frames / elapsed, 3) if elapsed else None,
        "suspected_cuts": suspected_cuts,
        "per_stroke": per_stroke,
    }


def _relative_change(before: float, after: float) -> float | None:
    return round((after / before - 1.0) * 100.0, 1) if before else None


def build_comparison(
    manifest: dict[str, Any],
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    baseline_by_id = {
        result["benchmark"]["sample_id"]: result for result in baseline["results"]
    }
    candidate_by_id = {
        result["benchmark"]["sample_id"]: result for result in candidate["results"]
    }
    base_summary = _aggregate(baseline)
    candidate_summary = _aggregate(candidate)
    samples: list[dict[str, Any]] = []
    labeled_arm = labeled_kick = 0
    for item in manifest["samples"]:
        sample_id = item["id"]
        evaluation_lane_id = int(item["evaluation_lane_id"])
        result = candidate_by_id[sample_id]
        tracks = _best_tracks_by_lane(result)
        lane_rows: list[dict[str, Any]] = []
        for lane_id, track in sorted(tracks.items()):
            lane_rows.append(
                {
                    "lane_id": lane_id,
                    "observed_frames": int(track["observed_frames"]),
                    "track_coverage": float(track["track_coverage"]),
                    "arm_strokes": _event_value(track, "arm_strokes"),
                    "arm_reason": track["arm_strokes"].get("reason"),
                    "kicks": _event_value(track, "kicks"),
                    "kick_reason": track["kicks"].get("reason"),
                }
            )
        ground_truth = item.get("ground_truth", [])
        labeled_arm += sum(row.get("arm_strokes") is not None for row in ground_truth)
        labeled_kick += sum(row.get("kicks") is not None for row in ground_truth)
        evaluation_track = tracks.get(evaluation_lane_id)
        samples.append(
            {
                "sample_id": sample_id,
                "stroke_kind": item["stroke_kind"],
                "video_prefix": item["video_prefix"],
                "interval_sec": item["interval_sec"],
                "evaluation_lane_id": evaluation_lane_id,
                "evaluation_lane_prediction": {
                    "arm_strokes": _event_value(evaluation_track, "arm_strokes")
                    if evaluation_track
                    else None,
                    "kicks": _event_value(evaluation_track, "kicks")
                    if evaluation_track
                    else None,
                    "track_coverage": float(evaluation_track["track_coverage"])
                    if evaluation_track
                    else 0.0,
                },
                "baseline_mean_detected_lanes": baseline_by_id[sample_id]["benchmark"][
                    "mean_detected_lanes"
                ],
                "candidate_mean_detected_lanes": result["benchmark"]["mean_detected_lanes"],
                "scene_stability": result["benchmark"].get("scene_stability"),
                "lane_predictions": lane_rows,
            }
        )

    return {
        "benchmark_version": candidate["benchmark_version"],
        "manifest_seed": manifest["seed"],
        "protocol": manifest["protocol"],
        "providers": {"baseline": baseline["provider"], "candidate": candidate["provider"]},
        "summary": {"baseline": base_summary, "candidate": candidate_summary},
        "coverage_improvement": {
            "mean_detected_lanes_percent": _relative_change(
                base_summary["mean_detected_lanes"], candidate_summary["mean_detected_lanes"]
            ),
            "stable_tracks_percent": _relative_change(
                base_summary["stable_tracks"], candidate_summary["stable_tracks"]
            ),
            "arm_count_outputs_percent": _relative_change(
                base_summary["arm_count_outputs"], candidate_summary["arm_count_outputs"]
            ),
            "kick_count_outputs_percent": _relative_change(
                base_summary["kick_count_outputs"], candidate_summary["kick_count_outputs"]
            ),
        },
        "count_accuracy": {
            "status": "unverified" if not (labeled_arm or labeled_kick) else "partially_labeled",
            "labeled_arm_rows": labeled_arm,
            "labeled_kick_rows": labeled_kick,
            "reason": (
                "The sampled broadcast clips have no independent event labels, and many kicks are "
                "not visually resolvable at source resolution. Predictions are not reused as truth."
            ),
        },
        "samples": samples,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare two SwimMate offline benchmark runs")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    comparison = build_comparison(manifest, baseline, candidate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

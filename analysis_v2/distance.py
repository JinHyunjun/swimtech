"""Distance-per-stroke for an explicitly measured swimmer/time interval."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from .counting import TrackCountResult


@dataclass(frozen=True)
class DistanceSegment:
    track_id: str
    start_sec: float
    end_sec: float
    distance_m: float
    distance_basis: str = "interval_total"
    distance_source: str = "user_measured"

    def __post_init__(self) -> None:
        if not self.track_id or not self.track_id.strip():
            raise ValueError("distance requires an explicit swimmer track_id")
        if not all(math.isfinite(value) for value in (self.start_sec, self.end_sec, self.distance_m)):
            raise ValueError("distance and interval must be finite")
        if self.start_sec < 0 or self.end_sec <= self.start_sec or self.distance_m <= 0:
            raise ValueError("distance must be positive and interval must increase")
        if self.distance_basis not in {"interval_total", "surface_swimming"}:
            raise ValueError("distance_basis must be interval_total or surface_swimming")
        if self.distance_source not in {"user_measured", "calibrated_pool"}:
            raise ValueError("distance_source must be user_measured or calibrated_pool")


def calculate_dps(track: TrackCountResult | None, segment: DistanceSegment) -> dict[str, object]:
    """Use the same interval for the numerator and denominator.

    Freestyle/backstroke count each arm action. Two actions are one cycle
    equivalent, including a half cycle at an interval boundary. Breaststroke
    and butterfly already count a synchronized action as one cycle. Pixel
    displacement, pool length alone, and missing kicks cannot supply distance.
    """
    result: dict[str, object] = {
        **asdict(segment),
        "available": False,
        "reason": None,
        "stroke_count": None,
        "stroke_count_unit": None,
        "cycle_equivalents": None,
        "dps_m_per_stroke": None,
        "distance_per_cycle_m": None,
        "count_source": "model_prediction",
        "accuracy_status": "unverified_model_prediction",
    }
    reason = None
    if track is None or track.track_id != segment.track_id:
        reason = "swimmer_not_found_in_interval"
    elif track.stroke_kind == "unknown":
        reason = "stroke_kind_required_for_dps"
    elif not track.arm_strokes.available:
        reason = f"stroke_count_unavailable:{track.arm_strokes.reason}"
    else:
        # One source-frame tolerance accommodates video frame quantization only.
        tolerance = 1.0 / (track.sample_rate_hz or 30.0) + 0.002
        if abs(track.started_at_sec - segment.start_sec) > tolerance or abs(track.ended_at_sec - segment.end_sec) > tolerance:
            reason = "distance_interval_not_fully_observed"
        elif track.track_coverage < 0.90 or min(
            float(track.diagnostics["left_arm_visibility"]),
            float(track.diagnostics["right_arm_visibility"]),
        ) < 0.90:
            reason = "insufficient_arm_coverage_for_dps"
        elif float(track.diagnostics.get("longest_observation_gap_sec") or 0) > 0.35:
            reason = "observation_gap_in_distance_interval"
        elif float(track.diagnostics.get("longest_arm_signal_gap_sec") or 0) > 0.35:
            reason = "arm_signal_gap_in_distance_interval"
    if reason is not None:
        result["reason"] = reason
        return result

    assert track is not None
    events = [time for time in track.arm_strokes.event_times_sec if segment.start_sec <= time < segment.end_sec]
    count = len(events)
    if count == 0:
        result["reason"] = "no_strokes_in_distance_interval"
        return result
    alternating = track.stroke_kind in {"freestyle", "backstroke"}
    cycles = count / 2.0 if alternating else float(count)
    result.update(
        available=True,
        stroke_count=count,
        stroke_count_unit="single_arm_action" if alternating else "synchronized_arm_cycle",
        cycle_equivalents=cycles,
        dps_m_per_stroke=round(segment.distance_m / count, 4),
        distance_per_cycle_m=round(segment.distance_m / cycles, 4),
    )
    return result

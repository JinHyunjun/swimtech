"""Explicit review-assisted exclusions, never automatic phase predictions."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ArmExclusion:
    """A half-open interval visually reviewed as containing no arm strokes.

    Applies to arms only: streamline swimming may still contain real kicks.
    This is calibration metadata, not independent event ground truth.
    """

    track_id: str
    start_sec: float
    end_sec: float
    reason: str
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.track_id, str) or not self.track_id.strip():
            raise ValueError("arm exclusion requires an explicit track_id")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
               for value in (self.start_sec, self.end_sec)):
            raise ValueError("arm exclusion times must be finite numbers")
        if self.start_sec < 0 or self.end_sec <= self.start_sec:
            raise ValueError("arm exclusion interval must increase and be nonnegative")
        if self.reason not in {"entry_glide", "streamline", "stationary"}:
            raise ValueError("unsupported arm exclusion reason")
        if self.source not in {"user_reviewed", "assistant_visual_review"}:
            raise ValueError("arm exclusion requires explicit review provenance")


def validate_arm_exclusions(values: Iterable[ArmExclusion]) -> tuple[ArmExclusion, ...]:
    ordered = tuple(sorted(values, key=lambda item: (item.track_id, item.start_sec)))
    for previous, current in zip(ordered, ordered[1:]):
        if previous.track_id == current.track_id and current.start_sec < previous.end_sec:
            raise ValueError("arm exclusions must not overlap for the same swimmer")
    return ordered


def arm_counting_windows(exclusions: Iterable[ArmExclusion]) -> list[tuple[float, float]]:
    """Complement of one swimmer's exclusions, preserving even sub-frame gaps."""
    windows = []
    start = -math.inf
    for item in exclusions:
        windows.append((start, item.start_sec))
        start = item.end_sec
    windows.append((start, math.inf))
    return windows


def load_arm_exclusions(path: Path, source_video_sha256: str) -> tuple[ArmExclusion, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != "swimmate-arm-exclusions-v1":
        raise ValueError("unsupported arm exclusion schema")
    if data.get("source_video_sha256") != source_video_sha256:
        raise ValueError("arm exclusions belong to a different source video")
    rows = data.get("exclusions")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("arm exclusions must be a list of interval objects")
    return validate_arm_exclusions(ArmExclusion(**row) for row in rows)

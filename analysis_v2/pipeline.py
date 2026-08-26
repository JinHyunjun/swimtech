"""End-to-end coordinator for multi-swimmer tracking and counting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from .counting import CounterConfig, TrackCountResult, count_track
from .tracking import MultiSwimmerTracker, TrackerConfig
from .types import PoseDetection, StrokeKind


MODEL_VERSION = "multiswimmer-counter-v0.1.0"


@dataclass(frozen=True)
class MultiSwimmerAnalysis:
    model_version: str
    experimental: bool
    generated_at: str
    stroke_kind: str
    processed_frames: int
    detected_track_count: int
    tracks: tuple[TrackCountResult, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "model_version": self.model_version,
            "experimental": self.experimental,
            "generated_at": self.generated_at,
            "stroke_kind": self.stroke_kind,
            "processed_frames": self.processed_frames,
            "detected_track_count": self.detected_track_count,
            "tracks": [track.to_dict() for track in self.tracks],
            "limitations": list(self.limitations),
        }


class MultiSwimmerAnalyzer:
    """Analyze a video frame stream while preserving one counter per athlete."""

    def __init__(
        self,
        stroke_kind: StrokeKind | str,
        tracker_config: TrackerConfig | None = None,
        counter_config: CounterConfig | None = None,
    ) -> None:
        self.stroke_kind = stroke_kind if isinstance(stroke_kind, StrokeKind) else StrokeKind(stroke_kind)
        self.tracker = MultiSwimmerTracker(tracker_config)
        self.counter_config = counter_config or CounterConfig()
        self.processed_frames = 0
        self._last_frame_index = -1
        self._last_timestamp = -1.0

    def process_frame(
        self,
        detections: Iterable[PoseDetection],
        frame_index: int,
        timestamp_sec: float,
    ) -> None:
        if frame_index <= self._last_frame_index:
            raise ValueError("frame_index must increase monotonically")
        if timestamp_sec <= self._last_timestamp:
            raise ValueError("timestamp_sec must increase monotonically")
        self.tracker.update(detections, frame_index, timestamp_sec)
        self.processed_frames += 1
        self._last_frame_index = frame_index
        self._last_timestamp = timestamp_sec

    def finalize(self) -> MultiSwimmerAnalysis:
        results = tuple(
            count_track(
                track,
                self.stroke_kind,
                self.counter_config,
                total_processed_frames=self.processed_frames,
            )
            for track in self.tracker.all_tracks()
            if track
        )
        limitations = (
            "Offline experimental baseline; not registered in the public API.",
            "Counts require stable, continuous footage without replay, cuts, or speed changes.",
            "Kick counts are withheld when both ankles are not sufficiently visible.",
            "Generic pose estimation must be validated on rights-cleared swimming footage.",
        )
        return MultiSwimmerAnalysis(
            model_version=MODEL_VERSION,
            experimental=True,
            generated_at=datetime.now(timezone.utc).isoformat(),
            stroke_kind=self.stroke_kind.value,
            processed_frames=self.processed_frames,
            detected_track_count=len(results),
            tracks=results,
            limitations=limitations,
        )

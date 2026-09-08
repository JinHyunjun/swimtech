"""End-to-end coordinator for multi-swimmer tracking and counting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from .counting import CounterConfig, TrackCountResult, count_track
from .distance import DistanceSegment, calculate_dps
from .phases import ArmExclusion, validate_arm_exclusions
from .tracking import MultiSwimmerTracker, TrackerConfig
from .types import PoseDetection, StrokeKind, StrokeSource


MODEL_VERSION = "multiswimmer-counter-v0.5.0"


@dataclass(frozen=True)
class MultiSwimmerAnalysis:
    model_version: str
    experimental: bool
    generated_at: str
    stroke_kind: str
    stroke_source: str
    sample_rate_hz: float | None
    processed_frames: int
    detected_track_count: int
    tracks: tuple[TrackCountResult, ...]
    limitations: tuple[str, ...]
    distance_metrics: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "model_version": self.model_version,
            "experimental": self.experimental,
            "generated_at": self.generated_at,
            "stroke_kind": self.stroke_kind,
            "stroke_source": self.stroke_source,
            "sample_rate_hz": self.sample_rate_hz,
            "processed_frames": self.processed_frames,
            "detected_track_count": self.detected_track_count,
            "tracks": [track.to_dict() for track in self.tracks],
            "limitations": list(self.limitations),
            "distance_metrics": list(self.distance_metrics),
        }


class MultiSwimmerAnalyzer:
    """Analyze a video frame stream while preserving one counter per athlete."""

    def __init__(
        self,
        stroke_kind: StrokeKind | str,
        tracker_config: TrackerConfig | None = None,
        counter_config: CounterConfig | None = None,
        stroke_source: StrokeSource | str = StrokeSource.UNVERIFIED,
    ) -> None:
        self.stroke_kind = stroke_kind if isinstance(stroke_kind, StrokeKind) else StrokeKind(stroke_kind)
        self.stroke_source = (
            stroke_source if isinstance(stroke_source, StrokeSource) else StrokeSource(stroke_source)
        )
        self.tracker = MultiSwimmerTracker(tracker_config)
        self.counter_config = counter_config or CounterConfig()
        self.processed_frames = 0
        self._last_frame_index = -1
        self._last_timestamp = -1.0
        self._first_timestamp: float | None = None
        self._processed_timestamps: list[float] = []

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
        if self._first_timestamp is None:
            self._first_timestamp = timestamp_sec
        self.processed_frames += 1
        self._last_frame_index = frame_index
        self._last_timestamp = timestamp_sec
        self._processed_timestamps.append(timestamp_sec)

    def finalize(self, distance_segments: Iterable[DistanceSegment] = (), *,
                 arm_exclusions: Iterable[ArmExclusion] = ()) -> MultiSwimmerAnalysis:
        exclusions = validate_arm_exclusions(arm_exclusions)
        track_ids = {track[0].track_id for track in self.tracker.all_tracks() if track}
        if any(item.track_id not in track_ids for item in exclusions):
            raise ValueError("arm exclusion swimmer not found in analyzed tracks")
        sample_rate_hz = None
        if self.processed_frames > 1 and self._first_timestamp is not None:
            duration = self._last_timestamp - self._first_timestamp
            if duration > 0:
                sample_rate_hz = (self.processed_frames - 1) / duration
        results = tuple(
            count_track(
                track,
                self.stroke_kind,
                self.counter_config,
                total_processed_frames=self.processed_frames,
                processed_sample_rate_hz=sample_rate_hz,
                arm_exclusions=exclusions,
            )
            for track in self.tracker.all_tracks()
            if track
        )
        distance_metrics: list[dict[str, object]] = []
        for segment in distance_segments:
            interval_rows = [
                row for track in self.tracker.all_tracks() for row in track
                if row.track_id == segment.track_id and segment.start_sec <= row.timestamp_sec < segment.end_sec
            ]
            interval_frames = sum(segment.start_sec <= time < segment.end_sec for time in self._processed_timestamps)
            interval_result = count_track(
                interval_rows, self.stroke_kind, self.counter_config,
                total_processed_frames=interval_frames, processed_sample_rate_hz=sample_rate_hz,
                arm_exclusions=exclusions,
            ) if interval_rows else None
            distance_metrics.append(calculate_dps(interval_result, segment))
        limitations = (
            "Offline experimental baseline; not registered in the public API.",
            "Counts require stable, continuous footage without replay, cuts, or speed changes.",
            "Stroke kind is externally supplied and its provenance is retained; filenames are not classifiers.",
            "Kick counts require both knees and ankles plus sufficient temporal sampling.",
            "Generic pose estimation must be validated on rights-cleared swimming footage.",
            "DPS uses a supplied distance for the same swimmer and time interval; it is an unverified model estimate.",
            "Optional arm exclusions are explicit review metadata, not learned phase predictions or independent event labels.",
        )
        return MultiSwimmerAnalysis(
            model_version=MODEL_VERSION,
            experimental=True,
            generated_at=datetime.now(timezone.utc).isoformat(),
            stroke_kind=self.stroke_kind.value,
            stroke_source=self.stroke_source.value,
            sample_rate_hz=round(sample_rate_hz, 3) if sample_rate_hz is not None else None,
            processed_frames=self.processed_frames,
            detected_track_count=len(results),
            tracks=results,
            limitations=limitations,
            distance_metrics=tuple(distance_metrics),
        )

"""Experimental multi-swimmer stroke and kick counting pipeline.

This package is deliberately isolated from the public SwimMate application.
It provides an offline baseline that can track several swimmers independently
and count motion events per track. Public routes must not import this package
until the release gates in ``docs/VIDEO_ANALYSIS_V2.md`` are satisfied.
"""

from .counting import CounterConfig, count_track
from .lanes import (
    LaneCropPoseProvider,
    LaneLayout,
    LaneMosaicPoseProvider,
    LaneRegion,
    assign_detections_to_lanes,
)
from .pipeline import MultiSwimmerAnalyzer, MultiSwimmerAnalysis
from .tracking import MultiSwimmerTracker, TrackerConfig
from .types import KeypointIndex, PoseDetection, StrokeKind, TrackObservation

__all__ = [
    "CounterConfig",
    "KeypointIndex",
    "LaneCropPoseProvider",
    "LaneLayout",
    "LaneMosaicPoseProvider",
    "LaneRegion",
    "MultiSwimmerAnalysis",
    "MultiSwimmerAnalyzer",
    "MultiSwimmerTracker",
    "PoseDetection",
    "StrokeKind",
    "TrackObservation",
    "TrackerConfig",
    "assign_detections_to_lanes",
    "count_track",
]

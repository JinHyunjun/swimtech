"""Local pose replay: compare counters on identical model detections."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

from .types import PoseDetection


SCHEMA = "swimmate-pose-cache-v1"


def video_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def serialize_frame(frame_index: int, timestamp_sec: float, detections: Iterable[PoseDetection]) -> dict[str, Any]:
    return {
        "frame_index": frame_index,
        "timestamp_sec": timestamp_sec,
        "detections": [
            {"keypoints": pose.keypoints.tolist(), "bbox": list(pose.bbox),
             "confidence": pose.confidence, "lane_hint": pose.lane_hint}
            for pose in detections
        ],
    }


def deserialize_detections(frame: dict[str, Any]) -> list[PoseDetection]:
    return [PoseDetection(**row) for row in frame["detections"]]


def write_pose_cache(path: Path, video_hash: str, fps: float, frames: list[dict[str, Any]],
                     metadata: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        json.dump({"schema_version": SCHEMA, "video_sha256": video_hash, "source_fps": fps,
                   "frames": frames, "inference": metadata}, stream, allow_nan=False)


def read_pose_cache(path: Path, expected_video_hash: str) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        data = json.load(stream)
    if data.get("schema_version") != SCHEMA:
        raise ValueError("unsupported pose cache schema")
    if data.get("video_sha256") != expected_video_hash:
        raise ValueError("pose cache belongs to a different source video")
    if not math.isfinite(data["source_fps"]) or data["source_fps"] <= 0:
        raise ValueError("pose cache source fps must be positive and finite")
    last_index, last_time = -1, -1.0
    for frame in data["frames"]:
        index, time = frame["frame_index"], frame["timestamp_sec"]
        if not math.isfinite(time) or time <= last_time or index <= last_index:
            raise ValueError("pose cache frames must increase monotonically")
        if abs(time - index / data["source_fps"]) > 0.002:
            raise ValueError("pose cache timestamp does not match source frame")
        deserialize_detections(frame)
        last_index, last_time = index, time
    return data

"""Bounded local jobs, private artifacts and review-quality diagnostics."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any
from uuid import uuid4

from ..benchmark import match_events
from ..counting import CounterConfig, _ankle_difference_signal, _projected_signal
from ..pose_cache import deserialize_detections, read_pose_cache
from ..pipeline import MultiSwimmerAnalyzer
from ..types import KeypointIndex
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MAX_BYTES = 200 * 1024 * 1024
MAX_PROJECTS = 12


def save_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(".part")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def inspect_video(path: Path) -> dict:
    import cv2
    capture = cv2.VideoCapture(str(path))
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width, height = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not capture.isOpened() or not math.isfinite(fps) or not 1 <= fps <= 120 or frames < 2:
            raise ValueError("읽을 수 있는 영상이 아닙니다. MP4(H.264) 영상을 권장합니다.")
        if frames / fps > 600 or max(width, height) > 4096:
            raise ValueError("영상은 10분·4K 이하로 잘라 올려 주세요.")
        ok, _ = capture.read()
        if not ok:
            raise ValueError("영상 첫 프레임을 읽을 수 없습니다.")
        return dict(fps=fps, frames=frames, width=width, height=height, duration=frames / fps)
    finally:
        capture.release()


def create_preview(path: Path, info: dict) -> None:
    """Local silent H.264 proxy with the same frame-index clock as inference.

    HEVC can load only its audio stream in Chromium without raising video.error.
    Never replace the original used for inference or its identity hash.
    """
    from imageio_ffmpeg import get_ffmpeg_exe
    scale = min(1, 1280 / max(info["width"], info["height"]))
    width = max(2, round(info["width"] * scale / 2) * 2)
    height = max(2, round(info["height"] * scale / 2) * 2)
    fps = str(info["fps"])
    output = path.parent / "preview.mp4"
    command = [get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-protocol_whitelist", "file,pipe", "-threads", "2", "-i", str(path),
               "-map", "0:v:0", "-an", "-sn", "-dn", "-map_metadata", "-1",
               "-vf", f"scale={width}:{height},setsar=1,setpts=N/({fps}*TB)",
               "-r", fps, "-fps_mode", "cfr", "-c:v", "libx264", "-threads", "2",
               "-preset", "veryfast", "-crf", "20", "-maxrate", "4M", "-bufsize", "8M",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)]
    try:
        with (path.parent / "preview.log").open("w", encoding="utf-8") as log:
            subprocess.run(command, stdout=log, stderr=log, check=True, timeout=300,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        preview = inspect_video(output)
        if preview["frames"] != info["frames"] or abs(preview["duration"] - info["duration"]) > 1 / info["fps"]:
            raise ValueError("미리보기와 원본 프레임이 일치하지 않습니다.")
    except (subprocess.SubprocessError, ValueError) as exc:
        raise ValueError("재생용 영상 변환에 실패했습니다. 짧은 MP4 영상으로 다시 시도해 주세요.") from exc


def review_diagnostics(cache: dict, stroke: str) -> dict:
    """Locate missing evidence; do not label physical occlusion from confidence alone."""
    analyzer = MultiSwimmerAnalyzer(stroke)
    overlays = []
    for frame in cache["frames"]:
        detections = deserialize_detections(frame)
        analyzer.process_frame(detections, frame["frame_index"], frame["timestamp_sec"])
        # One selected lane per review project. Full source coordinates retained.
        overlays.append({"time": frame["timestamp_sec"], "poses": [
            {"lane": pose.lane_hint, "points": pose.keypoints.round(4).tolist()} for pose in detections]})
    windows = []
    cfg = CounterConfig()
    for rows in analyzer.tracker.all_tracks():
        if not rows:
            continue
        timestamps = np.array([row.timestamp_sec for row in rows])
        left, _ = _projected_signal(rows, KeypointIndex.LEFT_WRIST, "longitudinal", cfg)
        right, _ = _projected_signal(rows, KeypointIndex.RIGHT_WRIST, "longitudinal", cfg)
        legs, _ = _ankle_difference_signal(rows, cfg)
        for name, values, threshold in (("arm_evidence_gap", left + right, .35),
                                        ("leg_evidence_gap", legs, .10)):
            valid = timestamps[np.isfinite(values)]
            boundaries = np.r_[timestamps[0], valid, timestamps[-1]]
            for start, end in zip(boundaries, boundaries[1:]):
                if end - start > threshold:
                    windows.append(dict(track_id=rows[0].track_id, reason=name,
                                        start_sec=round(float(start), 3), end_sec=round(float(end), 3)))
        for previous, current in zip(rows, rows[1:]):
            delta = current.timestamp_sec - previous.timestamp_sec
            if delta <= .1 and np.linalg.norm(current.detection.centroid - previous.detection.centroid) > .15:
                windows.append(dict(track_id=current.track_id, reason="possible_tracking_or_camera_jump",
                                    start_sec=round(previous.timestamp_sec, 3), end_sec=round(current.timestamp_sec, 3)))
    return {"windows": sorted(windows, key=lambda row: row["start_sec"]), "overlays": overlays,
            "status": "review_hints_not_ground_truth"}


def single_review_comparison(label: dict, result: dict, distance: float | None) -> dict:
    track = next((item for item in result["tracks"] if item["lane_id"] == label["lane_id"]), None)
    out: dict[str, Any] = {"status": "single_reviewer_comparison_not_validated_accuracy",
                           "label_mode": label["label_mode"], "manual_dps": None}
    for key, prediction_key, diagnostics_key in (
        ("arm", "arm_strokes", "merged_arm_candidate_times_sec"),
        ("kick", "kicks", "kick_candidate_times_sec"),
    ):
        if label[f"{key}_label_status"] == "unresolvable":
            out[key] = {"status": "unresolvable", "manual_count": None}
            continue
        reference = label[f"{key}_event_times_sec"]
        prediction = track[prediction_key] if track else {"available": False, "reason": "track_not_found"}
        candidates = (prediction["event_times_sec"] if prediction["available"]
                      else track["diagnostics"].get(diagnostics_key, []) if track else [])
        out[key] = dict(status="candidate_comparison" if not prediction["available"] else "prediction_comparison",
                        manual_count=len(reference), model_count=prediction.get("count") if prediction["available"] else None,
                        candidate_count=len(candidates), absolute_candidate_count_difference=abs(len(reference) - len(candidates)),
                        timing=match_events(reference, candidates, .25), withheld_reason=prediction.get("reason"))
        if key == "arm" and distance and reference:
            out["manual_dps"] = round(distance / len(reference), 4)
    return out


class Workbench:
    def __init__(self, root: Path, runner=None) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="swim-review")
        self.processes: dict[str, subprocess.Popen] = {}
        self.active: set[str] = set()
        self.runner = runner or self.run_model
        for item in self.root.glob("*/meta.json"):
            data = json.loads(item.read_text(encoding="utf-8"))
            if data.get("state") in {"running", "queued"}:
                data.update(state="interrupted", error="이전 실행이 종료됐습니다. 분석을 다시 시작해 주세요.")
                save_json(item, data)

    def directory(self, ident: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", ident):
            raise ValueError("잘못된 영상 ID입니다.")
        path = (self.root / ident).resolve()
        if path.parent != self.root:
            raise ValueError("저장 경로가 잘못됐습니다.")
        return path

    def read(self, ident: str) -> dict:
        with self.lock:
            return json.loads((self.directory(ident) / "meta.json").read_text(encoding="utf-8"))

    def update(self, ident: str, **fields) -> dict:
        with self.lock:
            data = self.read(ident)
            data.update(fields)
            save_json(self.directory(ident) / "meta.json", data)
            return data

    def list(self) -> list[dict]:
        with self.lock:
            return sorted([json.loads(path.read_text(encoding="utf-8")) for path in self.root.glob("*/meta.json")],
                          key=lambda item: item["created_at"], reverse=True)

    def allocate(self) -> tuple[str, Path]:
        with self.lock:
            if len(list(self.root.iterdir())) >= MAX_PROJECTS:
                raise ValueError("최대 12개 영상을 보관합니다. 필요 없는 영상을 삭제해 주세요.")
            ident = uuid4().hex
            path = self.directory(ident)
            path.mkdir()
            return ident, path

    def delete(self, ident: str) -> None:
        with self.lock:
            path = self.directory(ident)
            if ident in self.active or ((path / "meta.json").exists() and self.read(ident).get("state") in {"running", "queued"}):
                raise ValueError("분석을 중지한 뒤 삭제해 주세요.")
            # Resolved absolute target is checked above, never a user filename.
            shutil.rmtree(path)

    def start(self, ident: str, settings: dict) -> None:
        with self.lock:
            data = self.read(ident)
            if ident in self.active or data["state"] in {"running", "queued"}:
                raise ValueError("이미 분석 중입니다.")
            if (self.directory(ident) / "label.json").exists() or data.get("revealed"):
                raise ValueError("기록/결과와 분석 조건을 보존합니다. 다른 조건은 영상을 새로 올려 주세요.")
            self.update(ident, state="queued", settings=settings, error=None)
            self.executor.submit(self._execute, ident)

    def _execute(self, ident: str) -> None:
        with self.lock:
            if not (self.directory(ident) / "meta.json").exists():
                return
            if self.read(ident)["state"] != "queued":
                return
            self.active.add(ident)
            self.update(ident, state="running", started_at=time.time())
        try:
            self.runner(ident)
            with self.lock:
                if self.read(ident)["state"] != "cancelled":
                    self.update(ident, state="complete", finished_at=time.time())
        except Exception:
            with self.lock:
                if self.read(ident)["state"] != "cancelled":
                    self.update(ident, state="failed", error="분석하지 못했습니다. 로컬 작업 폴더의 analysis.log를 확인해 주세요.")
        finally:
            with self.lock:
                self.active.discard(ident)

    def run_model(self, ident: str) -> None:
        data = self.read(ident)
        directory = self.directory(ident)
        settings = data["settings"]
        x1, y1, x2, y2 = settings["roi"]
        save_json(directory / "lane.json", {"source": "user_selected_review_region", "lanes": [
            {"lane_id": 1, "polygon": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]}]})
        command = [sys.executable, "-m", "analysis_v2.cli", str(directory / "source.mp4"),
                   "--stroke", settings["stroke"], "--start-sec", str(settings["start_sec"]),
                   "--end-sec", str(settings["end_sec"]), "--output", str(directory / "result.json"),
                   "--provider", "lane-rtmpose", "--lane-layout", str(directory / "lane.json"),
                   "--lane-rotation", settings["rotation"], "--max-swimmers", "1",
                   "--runtime-profile", "quality", "--pose-cache-out", str(directory / "poses.json.gz")]
        if settings.get("distance_m"):
            command += ["--distance-m", str(settings["distance_m"]), "--distance-track-id", "L01",
                        "--distance-source", "user_reported"]
        with (directory / "analysis.log").open("w", encoding="utf-8") as log:
            with self.lock:
                if self.read(ident)["state"] == "cancelled":
                    return
                process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.processes[ident] = process
            try:
                code = process.wait(timeout=1800)
                if code:
                    raise RuntimeError("local counter failed")
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise
            finally:
                with self.lock:
                    self.processes.pop(ident, None)
        cache = read_pose_cache(directory / "poses.json.gz", data["sha256"])
        save_json(directory / "review.json", review_diagnostics(cache, settings["stroke"]))

    def cancel(self, ident: str) -> None:
        with self.lock:
            data = self.read(ident)
            if data["state"] not in {"running", "queued"}:
                return
            self.update(ident, state="cancelled")
            process = self.processes.get(ident)
            if process:
                process.terminate()
                process.wait(timeout=10)

    def close(self) -> None:
        for row in self.list():
            if row["state"] in {"running", "queued"}:
                self.cancel(row["id"])
        self.executor.shutdown(wait=True, cancel_futures=True)

"""Small local GUI for independent arm-stroke and kick event labels."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .types import StrokeKind


def build_annotation(
    video: str,
    stroke_kind: str,
    lane_id: int,
    start_sec: float,
    end_sec: float,
    arm_events: list[float],
    kick_events: list[float],
    annotator: str,
    reviewer: str | None = None,
    video_sha256: str | None = None,
    arm_label_status: str = "labeled",
    kick_label_status: str = "labeled",
) -> dict[str, object]:
    valid_strokes = {item.value for item in StrokeKind if item != StrokeKind.UNKNOWN}
    if stroke_kind not in valid_strokes:
        raise ValueError(f"stroke_kind must be one of {sorted(valid_strokes)}")
    if lane_id < 1 or start_sec < 0 or end_sec <= start_sec:
        raise ValueError("lane/interval is invalid")

    def clean(values: list[float]) -> list[float]:
        result = sorted({round(float(value), 3) for value in values})
        if any(value < start_sec or value > end_sec for value in result):
            raise ValueError("event time lies outside the annotation interval")
        return result

    annotator = annotator.strip()
    reviewer = reviewer.strip() if reviewer else None
    if not annotator:
        raise ValueError("annotator is required")
    if reviewer:
        raise ValueError(
            "an individual annotation cannot verify itself; create a second blinded annotation "
            "and compare both with analysis_v2.adjudication"
        )
    valid_statuses = {"labeled", "unresolvable"}
    if arm_label_status not in valid_statuses or kick_label_status not in valid_statuses:
        raise ValueError("label status must be labeled or unresolvable")
    cleaned_arm_events = clean(arm_events)
    cleaned_kick_events = clean(kick_events)
    if arm_label_status == "unresolvable" and cleaned_arm_events:
        raise ValueError("unresolvable arm labels cannot contain events")
    if kick_label_status == "unresolvable" and cleaned_kick_events:
        raise ValueError("unresolvable kick labels cannot contain events")
    return {
        "schema_version": "swimmate-event-label-v2",
        "video": video,
        "video_sha256": video_sha256,
        "stroke_kind": stroke_kind,
        "lane_id": lane_id,
        "interval_sec": [round(start_sec, 3), round(end_sec, 3)],
        "arm_label_status": arm_label_status,
        "kick_label_status": kick_label_status,
        "arm_event_times_sec": cleaned_arm_events,
        "kick_event_times_sec": cleaned_kick_events,
        "annotator": annotator,
        "label_mode": "blinded_manual",
        "prediction_visible": False,
        "verified": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Label swimmer events on a local video")
    parser.add_argument("video", type=Path)
    parser.add_argument("--stroke", choices=[item.value for item in StrokeKind if item != StrokeKind.UNKNOWN], required=True)
    parser.add_argument("--lane-id", type=int, default=1)
    parser.add_argument("--start-sec", type=float, default=0.0)
    parser.add_argument("--end-sec", type=float)
    parser.add_argument("--annotator", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    args = build_parser().parse_args()
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - offline dependency
        raise SystemExit("OpenCV is required for the annotation tool") from exc
    if not args.video.is_file():
        raise SystemExit(f"Video not found: {args.video}")

    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise SystemExit(f"Cannot open video: {args.video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / fps if frame_count else 0.0
    end_sec = min(args.end_sec if args.end_sec is not None else duration, duration)
    if end_sec <= args.start_sec:
        capture.release()
        raise SystemExit("Annotation interval is empty")

    current_frame = max(0, int(round(args.start_sec * fps)))
    end_frame = min(frame_count - 1, int(round(end_sec * fps)))
    playing = False
    arm_events: list[float] = []
    kick_events: list[float] = []
    arm_label_status = "labeled"
    kick_label_status = "labeled"
    window = "SwimMate event annotation"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, 1280, 720)

    saved = False
    try:
        while True:
            current_frame = max(0, min(current_frame, end_frame))
            capture.set(cv2.CAP_PROP_POS_FRAMES, current_frame)
            ok, frame = capture.read()
            if not ok:
                break
            current_sec = current_frame / fps
            text = (
                f"{current_sec:7.3f}s | arms {len(arm_events)} ({arm_label_status}) | "
                f"kicks {len(kick_events)} ({kick_label_status}) | "
                "SPACE play  A arm  K kick  I/U unresolvable  Z/X undo  J/L seek  Q save"
            )
            cv2.rectangle(frame, (0, 0), (frame.shape[1], 44), (0, 0, 0), -1)
            cv2.putText(frame, text, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
            cv2.imshow(window, frame)
            key = cv2.waitKey(max(1, int(round(1000 / fps))) if playing else 0) & 0xFF
            if key == ord(" "):
                playing = not playing
            elif key in (ord("a"), ord("A")) and arm_label_status == "labeled":
                arm_events.append(current_sec)
            elif key in (ord("k"), ord("K")) and kick_label_status == "labeled":
                kick_events.append(current_sec)
            elif key in (ord("i"), ord("I")):
                arm_label_status = (
                    "unresolvable" if arm_label_status == "labeled" else "labeled"
                )
                if arm_label_status == "unresolvable":
                    arm_events.clear()
            elif key in (ord("u"), ord("U")):
                kick_label_status = (
                    "unresolvable" if kick_label_status == "labeled" else "labeled"
                )
                if kick_label_status == "unresolvable":
                    kick_events.clear()
            elif key in (ord("z"), ord("Z")) and arm_events:
                arm_events.pop()
            elif key in (ord("x"), ord("X")) and kick_events:
                kick_events.pop()
            elif key in (ord("j"), ord("J")):
                playing = False
                current_frame -= max(1, int(round(fps * 0.25)))
            elif key in (ord("l"), ord("L")):
                playing = False
                current_frame += max(1, int(round(fps * 0.25)))
            elif key in (ord("q"), ord("Q")):
                saved = True
                break
            elif key == 27:
                break
            elif playing:
                current_frame += 1
                if current_frame >= end_frame:
                    playing = False
    finally:
        capture.release()
        cv2.destroyAllWindows()

    if not saved:
        print("Annotation discarded")
        return 1
    payload = build_annotation(
        args.video.name,
        args.stroke,
        args.lane_id,
        args.start_sec,
        end_sec,
        arm_events,
        kick_events,
        args.annotator,
        video_sha256=_sha256(args.video),
        arm_label_status=arm_label_status,
        kick_label_status=kick_label_status,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(arm_events)} arm and {len(kick_events)} kick events to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

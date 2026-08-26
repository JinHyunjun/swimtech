# SwimMate multi-swimmer counter v0.1

This is an **offline experimental baseline**, not a public SwimMate feature.
It changes the unit of analysis from one video to one persistent swimmer track:

```text
frame -> multiple poses -> lane-aware tracking -> per-track time series
      -> per-track arm stroke events -> per-track kick events
```

## Supported baseline

- Up to ten swimmers in one continuous race clip
- Persistent `S001`, `S002`, ... track IDs even if detection order changes
- Lane-aware association on the frame's `y` axis by default
- Freestyle/backstroke alternating arm and kick events
- Breaststroke/butterfly synchronous arm and kick events
- Explicit `not available` result when the track is too short or legs are hidden
- JSON output that keeps every swimmer's counts separate

It does not yet support replays, slow motion, shot changes, relay exchanges,
underwater/above-water transitions, or re-identification after a long cut.

## Local use

MediaPipe and OpenCV remain optional legacy/offline dependencies. They are not
enabled in the public Render dependency set.

```powershell
python -m analysis_v2.cli .\race.mp4 `
  --stroke freestyle `
  --max-swimmers 8 `
  --lane-axis y `
  --provider tiled `
  --tile-grid 3x3 `
  --pool-roi 0.05,0.25,0.95,0.90 `
  --output .\analysis\output\race-counts.json
```

For a portrait or end-of-pool camera where lanes are arranged left-to-right,
use `--lane-axis x`.

The tiled provider is the default because athletes in broadcast footage are
often too small for whole-frame pose inference. The pool ROI should exclude
spectators, officials, and score graphics. It is video metadata, not a learned
value; automatic pool/lane calibration is a later milestone.

## Output contract

Each result contains one entry per athlete track with:

- track and lane IDs
- first/last observed timestamps
- observed frame count
- whole-clip track coverage
- arm-stroke count and event timestamps
- complete cycle count
- kick count and event timestamps
- visibility and confidence
- an explicit withholding reason when the result is not reliable

Counts are withheld when an athlete is observed in less than 60% of the
processed frames. This prevents a short, fragmented track from being presented
as a full-race count.

The lane ID is an internal order assigned when a swimmer is first seen. It is
not an official competition lane number until a future start-block/lane
calibration step maps it to broadcast lane metadata.

## Dataset requirements

Every source clip must retain its source URL, channel/video ID, checked license,
clip boundaries, speed/cut flags, stroke, camera view, visibility, and manually
reviewed event timestamps. Clips from the same source video, swimmer, event, or
duplicate broadcast must stay in the same train/validation/test partition.

Only rights-cleared footage may be used for a releasable model. A public YouTube
URL or a Creative Commons flag alone is not proof that a re-uploader owns the
broadcast footage, so source provenance still needs review.

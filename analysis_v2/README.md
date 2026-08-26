# SwimMate multi-swimmer counter v0.2

This package is an **offline experiment**, not a public SwimMate feature. It
changes the unit of analysis from one video to one physical pool lane:

```text
frame -> fixed lane polygons -> one rotated crop per lane -> RTMPose
      -> physical lane tracks -> per-lane arm and kick signals
```

## What v0.2 adds

- Perspective-aware lane polygons generated from a pool quadrilateral
- Stable physical IDs such as `L01` and `L08`
- Out-of-pool person filtering before tracking
- Lane crop rotation so a horizontal swimmer is upright for pose inference
- Optional RTMPose top-down provider that skips a whole-frame person detector
- Automatic suspected-shot-change metrics in the offline benchmark
- A seeded 20-clip benchmark: five clips for each of four strokes
- A swimmer-centred frame-sheet tool for independent human review

The original overlapping-tile MediaPipe provider remains the comparison
baseline. RTMPose and ONNX Runtime are offline-only dependencies and are not
loaded by the deployed FastAPI service.

## Current result

On the 2026-08-26 fixed-shot benchmark, the mean detected lanes per frame rose
from `1.868` to `4.897`, and tracks observed in at least 60% of sampled frames
rose from `7` to `93`. These are **detection and tracking coverage** results,
not count accuracy.

The 20 broadcast clips do not yet have independent stroke/kick event labels.
Many kicks cannot be resolved even by a human at the available source
resolution. Therefore real-video count accuracy is still unverified, and the
counter must remain outside the public API/UI. See
[`evaluation/results/2026-08-26-report.md`](evaluation/results/2026-08-26-report.md).

## Local commands

MediaPipe and OpenCV remain optional legacy/offline dependencies. RTMPose
comparison additionally requires `rtmlib` and `onnxruntime`.

```powershell
python -m pip install "mediapipe==0.10.35" "rtmlib==0.0.16" "onnxruntime==1.29.0"
```

Analyze a known fixed shot with a lane layout:

```powershell
python -m analysis_v2.cli .\race.mp4 `
  --stroke freestyle `
  --provider lane-rtmpose-topdown `
  --lane-layout .\lane-layout.json `
  --lane-rotation clockwise `
  --frame-step 5 `
  --output .\analysis\output\race-counts.json
```

Run the two-provider benchmark:

```powershell
python -m analysis_v2.benchmark `
  --manifest analysis_v2/evaluation/benchmark_manifest.json `
  --provider baseline-mediapipe-tiled `
  --sample-fps 6 `
  --output tmp/analysis_v2/baseline.json

python -m analysis_v2.benchmark `
  --manifest analysis_v2/evaluation/benchmark_manifest.json `
  --provider lane-rtmpose-topdown `
  --sample-fps 6 `
  --output tmp/analysis_v2/candidate.json

python -m analysis_v2.report `
  --manifest analysis_v2/evaluation/benchmark_manifest.json `
  --baseline tmp/analysis_v2/baseline.json `
  --candidate tmp/analysis_v2/candidate.json `
  --output tmp/analysis_v2/comparison.json
```

Generate prediction-free close-up sheets for manual review:

```powershell
python -m analysis_v2.review `
  --manifest analysis_v2/evaluation/benchmark_manifest.json `
  --sample freestyle-1 `
  --lane 6 `
  --output-dir tmp/analysis_v2/review
```

## Output contract

Each result contains one entry per physical lane track with:

- first/last observed timestamps and track coverage
- arm-stroke count and event timestamps
- complete cycle count
- kick count and event timestamps
- visibility, confidence, warnings, and explicit withholding reasons

Counts are withheld when an athlete is observed in less than 60% of the
processed frames or the relevant joints are not sufficiently visible. An
available count is still a model prediction; it is not considered accurate
until compared with an independent label.

## Unsupported input

- A clip containing broadcast shot changes without pre-segmentation
- Replays, slow motion, speed ramps, or relay exchanges
- Automatic lane calibration from start blocks or lane ropes
- Reliable kick labels from distant above-water views
- Identity re-identification across a camera cut

The benchmark records a histogram-based shot-change score, but the public
release gate requires automatic splitting or hard withholding in the complete
pipeline.

## Dataset and release requirements

Every source clip must retain its source URL, channel/video ID, checked license,
clip boundaries, speed/cut flags, stroke, camera view, visibility, and manually
reviewed event timestamps. Clips from the same source video, swimmer, event, or
duplicate broadcast must stay in the same train/validation/test partition.

Only rights-cleared footage may be used for a releasable model. A public YouTube
URL or a Creative Commons flag alone is not proof that a re-uploader owns the
broadcast footage. Public activation additionally requires independent labels,
an error-based accuracy report, asynchronous processing infrastructure, and a
video retention/deletion policy.

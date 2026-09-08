# SwimMate multi-swimmer counter v0.4.0

This package is an **offline experiment**, not a public SwimMate feature. It
changes the unit of analysis from one video to one physical pool lane:

```text
frame -> fixed lane polygons -> one rotated crop per lane -> RTMPose
      -> physical lane tracks -> per-lane arm and kick signals
```

## What v0.4 adds

The current priority is stroke/kick events and distance per stroke (DPS).
Technique grading and a new stroke classifier are deferred. This release
changes the temporal counter; it does not retrain RTMPose's neural weights.

- Separate 0.30 s arm and 0.09 s kick filters preserve fast kick motion.
- Resample by timestamps and split at missing detections or long joint gaps;
  smoothing cannot create strokes across an occlusion.
- Prominence stops at a higher neighbouring peak; sub-frame peak timing avoids
  merging distinct fast kicks due to frame rounding.
- Both arms must meet visibility requirements. Gaps with potentially missed
  events withhold interval totals while retaining candidates in `diagnostics`.
- CLI uses every source frame by default. Effective pose sample rate is
  reported separately from the camera/processed rate.
- Source-hash-bound local pose caches let counter changes run without repeating
  GPU inference, and allow comparisons on identical poses.
- Explicit per-swimmer distance intervals produce DPS and distance per cycle
  with named count units and completeness checks.

Nine analytic kick signals at 20/30/60 fps and 2/4/6 beats per second have
total absolute count error **67 -> 3** versus v0.3 on identical inputs. This is
a synthetic signal result, **not real-video accuracy**. The private freestyle
clip still has 0.800 s arm and 0.634 s kick signal gaps; its 13 arm and 12 kick
candidates are not complete counts. See
[`evaluation/results/2026-09-08-v0.4-counting-dps.md`](evaluation/results/2026-09-08-v0.4-counting-dps.md).

## What v0.3 added

- Explicit stroke-label provenance (`user_confirmed`, `event_metadata`, or
  `benchmark_manifest`) instead of treating a legacy directory name as a
  classifier
- A left/right arm-pattern check that withholds synchronous-stroke counts when
  observed motion is alternating
- An alternating-arm identity gate that withholds counts when both detected
  wrists repeatedly follow the same physical arm
- Time-based smoothing so supported 10/20/30 fps inputs use comparable signal
  windows
- Physiological refractory periods that merge near-duplicate arm and kick
  events
- Kick gating based on knee and ankle visibility, effective sample rate, and
  stroke-to-kick ratio

The v0.2 lane and runtime work remains in place:

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

## Current local runtime profiles

The runtime is now selected explicitly instead of silently staying on CPU:

- `auto` / `balanced`: RTMPose-M with OpenVINO Arc GPU when available
- `quality`: RTMPose-X with OpenVINO Arc GPU for slower offline review
- `portable`: RTMPose-S with ONNX Runtime CPU

On the Galaxy Book4 Pro test machine, RTMPose-M/Arc measured 36.24 pose fps for
one lane and is the default. RTMPose-X/Arc measured 10.06 pose fps and recovered
more arm visibility in one private clip, but still could not establish kick
accuracy. See
[`evaluation/results/2026-08-28-galaxy-book4-pro.md`](evaluation/results/2026-08-28-galaxy-book4-pro.md).

Across all 20 fixed-shot clips, the new balanced GPU runtime processed sampled
frames at 7.72 aggregate fps, about 5.8x the previous CPU benchmark. Higher
coverage is not treated as higher accuracy because the clips still lack
independent event labels.

```powershell
python -m pip install -r analysis_v2/requirements-offline.txt

python -m analysis_v2.runtime_benchmark .\video\sample.mp4 `
  --timestamp-sec 5 `
  --output tmp\analysis_v2\runtime.json
```

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
  --stroke-source user_confirmed `
  --provider lane-rtmpose-topdown `
  --lane-layout .\lane-layout.json `
  --lane-rotation clockwise `
  --runtime-profile balanced `
  --frame-step 1 `
  --output .\analysis\output\race-counts.json
```

Use a detector-guided provider (`lane-rtmpose` or
`lane-mosaic-rtmpose`) for real footage. `lane-rtmpose-topdown` is retained for
reproducibility, but it can hallucinate a pose because it treats the complete
lane crop as one person.

Create the first blinded event label before tuning counts:

```powershell
python -m analysis_v2.annotation .\video\sample.mp4 `
  --stroke freestyle --lane-id 1 --start-sec 5.7 --end-sec 17.7 `
  --annotator reviewer-a `
  --output tmp\analysis_v2\labels\sample-a.json
```

Run the same command in a separate session for `reviewer-b` and save to
`sample-b.json`. Neither reviewer should see model output or the other label.
The source video's SHA-256 is stored automatically, so labels made from
different files cannot be combined.

Keys in the annotation window: `Space` play/pause, `A` arm event, `K` kick
event, `I` arm unresolvable, `U` kick unresolvable, `Z`/`X` undo, `J`/`L`
seek, `Q` save, `Esc` discard. Empty events mean a visible zero; use `I` or
`U` when the motion cannot be resolved. For freestyle/backstroke, mark one
arm event at each hand's maximum forward extension/entry. Mark one kick event
at the completion of each visible downward beat by either foot. For
breaststroke/butterfly, mark the synchronized arm cycle and each distinct
propulsive kick at the same consistent phase throughout the clip.

Compare the two independent labels and score a prediction only when every
resolvable event has one-to-one agreement within 0.25 seconds:

```powershell
python -m analysis_v2.adjudication `
  --first tmp\analysis_v2\labels\sample-a.json `
  --second tmp\analysis_v2\labels\sample-b.json `
  --prediction tmp\analysis_v2\runtime\local-freestyle-v04-replay.json `
  --output tmp\analysis_v2\labels\sample-evaluation.json
```

If either reviewer marks an event type unresolvable, that type is excluded
instead of being interpreted as zero. If unmatched events remain, model
accuracy is blocked until the reviewers adjudicate the disagreement.

## Recount identical poses without GPU inference

Add `--pose-cache-out tmp/analysis_v2/poses.json.gz` to a video run. The cache
contains private per-frame poses, source FPS, SHA-256 and inference settings;
it is a local research artifact, not a model-training label.

```powershell
python -m analysis_v2.cli .\race.mp4 --stroke freestyle `
  --pose-cache-in tmp/analysis_v2/poses.json.gz `
  --output tmp/analysis_v2/recount.json
```

The original video is read only for its hash during replay. Different source
files are rejected. Replay retains the original inference settings in `run`.

## DPS for a known distance

Supply the **actual distance covered during the same analysis interval**.
Pool length alone is insufficient when a clip shows only part of a length.
Pixel motion is not converted into metres without calibration.

```powershell
# Example only: use 24 only if this swimmer covered 24 m in seconds 0..12.
python -m analysis_v2.cli .\race.mp4 --stroke freestyle `
  --pose-cache-in tmp/analysis_v2/poses.json.gz `
  --start-sec 0 --end-sec 12 `
  --distance-m 24 --distance-track-id L01 `
  --distance-basis surface_swimming `
  --output tmp/analysis_v2/dps.json
```

- Freestyle/backstroke: each arm action is one stroke. `DPS = distance / arm
  actions`; cycle equivalents are actions / 2, including half cycles. For
  example, 13 m / 13 actions gives 1 m/stroke and 2 m/cycle equivalent.
- Breaststroke/butterfly: a synchronized arm action is one cycle; the two
  distance metrics are equal.
- `interval_total` includes any push-off/glide distance within the interval;
  `surface_swimming` requires a measured surface-swimming interval. The tool
  does not guess or subtract underwater distances.
- Missing swimmer, uncertain counts, incomplete time coverage, long gaps,
  unknown stroke, zero events or invalid distance return an explicit reason
  and null DPS. Arm visibility and track coverage must both reach 90% for DPS.
- Reliable arm events can yield DPS even when kicks are unresolvable. All
  available model-derived DPS values retain `unverified_model_prediction`.

These units follow [USMS's distinction between individual arm strokes and
right-left cycles](https://www.usms.org/fitness-and-training/articles-and-videos/articles/distance-per-stroke?Oldid=82).
USMS also explains why [push-off distance affects stroke-count comparisons](https://www.usms.org/fitness-and-training/articles-and-videos/articles/how-many-strokes-should-you-be-taking).

For several swimmers or separate lengths, use `--distance-segments file.json`
instead of `--distance-m`. The JSON is a list of records:

```json
[
  {"track_id":"L01","start_sec":0,"end_sec":12,"distance_m":24,"distance_basis":"surface_swimming"},
  {"track_id":"L02","start_sec":0,"end_sec":12,"distance_m":20,"distance_basis":"surface_swimming"}
]
```

Each record is recounted on its own half-open `[start_sec, end_sec)` interval.
Results appear in `distance_metrics`. No supplied distance means an empty
list, not an assumed 25 m/50 m length. Intervals should show complete arm
actions: events cut off at the video boundary may not be confirmable.

Audit the legacy data before any retraining. Exit code 2 means training is
blocked:

```powershell
python analysis/train/07_audit_training_data.py `
  --output tmp\analysis_v2\training-data-audit.json
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
- stroke-label provenance, effective sample rate, and observed arm pattern
- observed candidate counts/times and longest joint gaps in `diagnostics`
- explicit stroke units and cycle equivalents, without flooring half cycles

`available=false` means the total could not be established. Its legacy `count:0`
placeholder must **not** be displayed as a confirmed zero. Diagnostic candidates
cover visible segments only and are not a replacement for the withheld total.

Counts are withheld when an athlete is observed in less than 60% of the
processed frames, the relevant joints are not sufficiently visible, temporal
sampling is inadequate, the two arms cannot be distinguished, or the selected
stroke conflicts with the observed temporal pattern. An available count is
still a model prediction; it is not considered accurate until compared with an
independent label.

## 2026-09-07 private local safety check

The user-confirmed freestyle clip `이강해.mp4` was rerun on the Galaxy Book4
Pro with detector-guided RTMPose-X/OpenVINO Arc GPU. At every second source
frame (14.992 fps), v0.3 withheld both arm and kick counts because the two arms
collapsed into a synchronous pose artifact and flutter kicks were
undersampled. At full source rate (29.984 fps), it retained 13 arm-event
candidates / 6 complete-cycle candidates but withheld seven kick candidates
because 1.17 kicks per cycle was implausibly low for the selected stroke.

This check proves the new failure gates execute on real footage. It does
**not** prove that 13 is the correct arm count; the clip still needs an
independent human event annotation. See
[`evaluation/results/2026-09-07-v0.3-safety-gates.md`](evaluation/results/2026-09-07-v0.3-safety-gates.md).

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

The legacy classifier trainer now accepts only `verified=true`,
`auto_labeled=false` labels and deduplicates by source video name. The current
dataset contains no such labels, so retraining is intentionally blocked instead
of producing another misleading accuracy number.

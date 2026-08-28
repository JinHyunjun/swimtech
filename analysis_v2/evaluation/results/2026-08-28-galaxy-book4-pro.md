# Galaxy Book4 Pro video model audit — 2026-08-28

This is an offline engineering result, not a released SwimMate capability.
Counts remain blocked from the public API/UI until independently reviewed
event labels satisfy the release gate.

## Machine and active runtime

- Samsung 940XGK (Galaxy Book4 Pro)
- Intel Core Ultra 5 125H, 14 cores / 18 logical processors
- 16 GB RAM
- Intel Arc integrated GPU
- Intel AI Boost NPU
- Windows 11, Python 3.12.2
- Previous runtime: ONNX Runtime 1.29.0 with CPU provider only
- Added offline runtime: OpenVINO 2026.3.1; CPU, GPU, and NPU devices are detected

The previous configuration did not use either the Arc GPU or the NPU.
Hardware acceleration cannot repair an incorrect pose, but it provides enough
headroom to run a larger detector/pose model and denser temporal sampling.

## RTMPose top-down microbenchmark

One frame from a private, rights-controlled freestyle clip was used. Numbers
include RTMPose preprocessing and pose inference for one lane after two warm-up
runs. They are machine-specific and are not accuracy measurements.

| Model | Device | Single-lane fps | Pose confidence on the test frame | Decision |
|---|---:|---:|---:|---|
| RTMPose-S (`lightweight`) | CPU | 28.64 | 0.200 | Too weak for the quality default |
| RTMPose-S (`lightweight`) | Arc GPU | 57.37 | 0.204 | Speed-only fallback |
| RTMPose-M (`balanced`) | CPU | 12.02 | 0.284 | CPU fallback |
| RTMPose-M (`balanced`) | Arc GPU | **36.24** | 0.285 | **Default for temporal/multi-lane experiments** |
| RTMPose-X (`performance`) | CPU | 3.21 | 0.576 | Impractical on this CPU |
| RTMPose-X (`performance`) | Arc GPU | 10.06 | **0.596** | Slow quality review mode |
| All current RTMPose ONNX files | NPU | unavailable | — | Dynamic batch is rejected by the current NPU compiler |

The automatic profile now selects RTMPose-M + OpenVINO GPU. The explicit
`quality` profile selects RTMPose-X + OpenVINO GPU. NPU is deliberately not
selected automatically; a fixed-shape export and a separate benchmark are
required before it can be used.

The complete 20-clip fixed-shot coverage benchmark processed 715 sampled
frames in 92.56 seconds (7.72 aggregate fps), versus the previous 1.33 fps.
Mean detected lanes changed from 4.897 to 5.833, tracks with at least 60%
coverage from 93 to 118, and non-withheld arm outputs from 73 to 103. These are
throughput/coverage observations only. Because the benchmark still has zero
independent event labels and uses the reproducibility-only top-down provider,
none of these increases is claimed as count accuracy.

## End-to-end local comparison

The same 12-second freestyle interval was sampled at roughly 15 source fps.
Unlike the previous whole-lane top-down path, this comparison used a person
detector before pose estimation.

| Profile | Pipeline fps | Track coverage | Arm visibility | Leg visibility | Result |
|---|---:|---:|---:|---:|---|
| RTMPose-M + Arc GPU | 7.11 | 67.2% | 32.2% | 31.4% | Arm/kick counts withheld |
| RTMPose-X + Arc GPU | 2.25 | 83.3% | 55.0% | 57.3% | 11 arm events predicted; kick withheld |

The 11-arm output is **not an accuracy result**. No independent event timeline
exists for this clip. The experiment only proves that the larger model recovers
more visible arm observations while remaining too slow and still failing the
kick visibility gate.

## Why accuracy did not improve

1. **No independent truth.** The earlier 20-clip benchmark has zero reviewed
   arm/kick timelines. Tuning against predictions cannot measure improvement.
2. **Contaminated stroke labels.** Folder names were treated as truth even when
   a folder contained another stroke. The local freestyle clip was initially
   evaluated as butterfly, proving this failure mode in practice.
3. **Train/evaluation leakage.** The legacy evaluator sampled the same summary
   table used for training. Its 94.44% result is not a held-out result; the
   saved classifier's cross-validation accuracy is 45.87%.
4. **Duplicate/conflicting videos.** Of 197 valid-stroke feature rows, 20 are
   duplicate rows and six video names carry conflicting stroke labels.
5. **No human labels.** All 330 entries in `labels.json` are auto-labeled; zero
   are independently verified. Retraining is now blocked in this state.
6. **Generic pose domain gap.** Ordinary human-pose models hallucinate on
   horizontal, partially submerged, reflected, foamy, or occluded bodies.
7. **Wrong localization.** Whole-lane top-down inference forces the network to
   return one pose even when the crop contains water, deck staff, or several
   swimmers. High confidence/coverage is therefore not proof of a swimmer.
8. **Temporal model gap.** Counting isolated wrist/ankle peaks cannot stabilize
   left/right swaps, recovery phases, glides, camera motion, or splashes.
9. **Kick observability.** Distant 12–15 fps footage often contains no usable
   ankle signal. A larger model cannot reconstruct motion absent from pixels.

The read-only dataset audit reports 356 summary rows, 20 duplicate rows, six
conflicting video names, zero human-verified labels, only 56/409 videos with an
80% pose-detection rate, and 194/409 below 50%.

## Revised model path

```text
explicit stroke + active interval
  -> water/lane calibration
  -> swimmer detector (never force a pose from the whole lane)
  -> lane-aware temporal tracker
  -> RTMPose-M GPU (default) / RTMPose-X GPU (review)
  -> pose validity + visibility + motion support gates
  -> stroke-specific temporal state model
  -> event timestamps with abstention
  -> independent event-level evaluation
```

The next learned component should be a small temporal classifier/state model
over normalized pose and optical-flow features, not a newly trained pose
backbone. This 16 GB laptop can train such a TCN/GRU-sized head, while pose
backbone training is neither data- nor memory-efficient here.

## Required accuracy protocol

- Label swimmer/lane, stroke, active interval, every arm event, every kick
  event, and visibility/unknown intervals.
- Use two people for annotation/review; self-reviewed labels remain unverified.
- Split by source video/swimmer/event, never by frame.
- Match events within ±0.25 seconds and report precision, recall, F1, timing
  MAE, count MAE, abstention coverage, and wrong-person rate.
- Report each stroke and camera view separately.
- Never convert a withheld result to zero or reuse a prediction as truth.

Only after this protocol produces an independently verified test result should
the model version, release notes, Notion service guide, or public API change.

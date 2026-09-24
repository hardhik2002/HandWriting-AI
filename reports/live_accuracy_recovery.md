# TouchWrite live accuracy recovery

## Real Root Cause

The failure is a domain-shift interaction, not a V1/V2 pipeline mismatch. Current touchscreen ink
is much flatter and wider than the historical golden sample. At the old 8 px recognition width,
closely spaced strokes in the long touchscreen line merge into heavier shapes. TrOCR then resolves
the weak visual evidence with plausible text substitutions. Reducing only the recognition width to
6 px recovered most of the current sentence while preserving the historical golden prediction.

The full sentence was also captured as one 27-stroke recognition unit. Automatic whitespace
segmentation found the seven intended groups, but recognizing those groups independently made the
short words substantially worse. Segmentation is retained as a diagnostic utility, not enabled in
the live path.

## Historical vs Touchscreen Comparison

| Metric | Historical `hardhik` | Touchscreen `hardhik` |
|---|---:|---:|
| Sample | `ba216970-66de-4d3e-b192-7669dd273b86` | `98ae9fd3-cb6c-4533-84f2-6a9fd66f5a8a` |
| Strokes / points | 12 / 354 | 9 / 323 |
| Raw ink aspect ratio | 2.96 | 5.12 |
| Event frequency | 97.6 Hz | 94.1 Hz |
| Median event interval | 8.39 ms | 8.46 ms |
| Mean point spacing | 3.56 px | 2.21 px |
| Mean turning angle | 13.9 degrees | 21.0 degrees |
| Total writing duration | 9028 ms | 4339 ms |
| Mean inter-stroke pause | 502 ms | 126 ms |
| Pressure coverage | 0% | 100% |
| Width-6 model occupancy | 12.63% | 14.03% |
| Width-6 prediction | `hardhik` | `hardhijk` |

The event rates are nearly equal, so sparse touchscreen sampling is not the differentiator. The
touchscreen word was written about twice as fast, with shorter pauses, denser points, fewer strokes,
and a 73% larger aspect ratio. See `reports/trajectory_comparison/hardhik_comparison.png` for raw,
smoothed, processed, and 384x384 views.

## 384×384 Geometry Investigation

The installed slow `ViTImageProcessor` resizes the 512x128 renderer output directly to 384x384
using bilinear interpolation and normalizes with mean/std 0.5. That is a 0.75 horizontal scale and
3.0 vertical scale: vertical geometry is magnified 4x relative to horizontal geometry.

This is distortion, but it is the checkpoint's expected preprocessing convention. Replacing it
with aspect-preserving full-image letterboxing dropped current exact accuracy from 33.3% to 0% and
raised CER from 39.7% to 74.6%. The production path therefore keeps processor-direct geometry.

The live display measured 1280x720 logical pixels over 309x173 mm: 105.22 physical DPI X and
105.71 physical DPI Y. The sub-0.5% X/Y difference cannot explain the 2.96 to 5.12 trajectory aspect
change.

## Occupancy Findings

Width 6 lowers foreground occupancy without changing the renderer canvas or cropping policy. For
the current sentence, source occupancy is 9.21% and model-input occupancy is 10.46%. The two `hi`
samples remain unusually sparse at 3.31% and 3.59% model occupancy, while current standalone
`hardhik` is 14.03%.

Explicit 5%, 10%, 15%, 20%, 25%, and 30% occupancy variants all broke the historical golden sample
and produced only 16.7% current exact accuracy with 66.7%-69.8% CER. There is no globally safe
occupancy target in this dataset.

## Sampling / Smoothing Findings

No-smoothing reproduced the baseline 39.7% current CER. Uniform 2 px spatial resampling worsened it
to 41.3%. Historical and touchscreen event rates were already similar at about 95-98 Hz. Neither
sampling density nor the moving-average stage is the primary cause, so both runtime behaviors remain
unchanged.

## Language-Prior Findings

Beam sequence scores are now captured as ranking diagnostics, not presented as calibrated
confidence. Correct clear phrases score near zero: `where are you` -0.031 and `how are you` -0.092.
Failures are weaker: the two `hi` samples score -0.809 and -0.849, and current standalone
`hardhijk` scores -0.850. The improved full line scores -0.391.

The beams contain plausible punctuation and English-like substitutions for ambiguous short/flat
ink. This is evidence of decoder-language-prior dominance when visual evidence is weak. No
dictionary, spell checker, LLM, or expected-output rule was added.

## TrOCR Base Benchmark

Using stroke width 6 on one historical and six current verified top-level samples:

| Metric | Result |
|---|---:|
| Historical exact accuracy | 100% (1/1) |
| Current exact accuracy | 33.3% (2/6) |
| Current CER | 20.6% |
| First inference | 11,359 ms |
| Warm median | 3,078 ms |
| Warm p95 | 8,455 ms |
| Process working-set delta | 1,682 MB |

Base remains the production model because it preserves the historical gate and gives the best
current-sentence result. It is not accurate enough to claim general handwriting success.

## TrOCR Large Benchmark

`microsoft/trocr-large-handwritten` was safely skipped. PyTorch reported no CUDA device and only
about 3 GB of free system RAM was available; the benchmark requires at least 6 GiB free before
loading Large. A crash or paging-heavy run would not be useful evidence.

## Other Model Benchmarks

`microsoft/trocr-small-handwritten` was benchmarked on the identical inputs. It was much faster
(428 ms warm median, 967 ms warm p95) and used about 179 MB additional working set, but it failed the
historical gate (`hardhik` -> `herdhik`). Its current sentence was
`ni how are you , I am bardfix`; current exact accuracy was 33.3% and CER 19.0%. It is not adopted.

Trajectory-native research options were reviewed. OnlineHTR publishes an IAM-OnDB trajectory model
but documents inference on arbitrary personal handwriting as unfinished. InkSight converts offline
images into online ink rather than directly solving this trajectory-recognition task. Neither is a
production-compatible replacement here.

## Best Preprocessing Variant

| Variant | Historical exact | Current exact | Current CER |
|---|---:|---:|---:|
| Old width 8 | 100% | 33.3% | 39.7% |
| **Width 6** | **100%** | **33.3%** | **20.6%** |
| Width 10 | 100% | 33.3% | 46.0% |
| Width 12 | 100% | 33.3% | 47.6% |
| No smoothing | 100% | 33.3% | 39.7% |
| Resample 2 px | 100% | 33.3% | 41.3% |
| Full letterbox | 100% | 0% | 74.6% |
| Occupancy targets | 0% | 16.7% | 66.7%-69.8% |

Width 6 is the only tested variant that materially lowers current CER without a historical
regression. `Settings.stroke_width` now defaults to 6. The archived width-8 fixture remains
explicitly reproducible for pixel-level historical comparison.

## Current Sentence Comparison

Expected: `hi how are you, I am hardhik`

| Pipeline | Prediction | Character errors |
|---|---|---:|
| Saved live width 8 | `in hour more slow , I am headline` | 25 |
| Replayed width 6 | `in how are you , I am hardhik` | 3 |
| TrOCR Small, width 6 | `ni how are you , I am bardfix` | 8 |

The width-6 replay fixes `how are you`, `I am`, and `hardhik` within the exact saved physical
trajectory. The remaining model errors are `hi` -> `in` and an inserted space before the comma.

## Historical Regression

The historical golden sample remains exactly `hardhik` under the new runtime default. The old
width-8 rendered fixture is still covered separately for byte/pixel reproducibility; changing the
live recognition width does not rewrite archived sample artifacts.

## Touchscreen Regression

The permanent verified manifest contains the two physical `hi` samples, standalone `hardhik`, the
successful `how are you` and `where are you` phrases, and the full current sentence. Width 6 produces
2/6 exact with 20.6% aggregate CER. It retains the two successful phrases and substantially improves
the sentence, but standalone `hi` and `hardhik` remain failing cases.

A guided collection workflow was added because the pretrained image models are still inadequate
for short personal touchscreen words. It records repeatable A-Z, a-z, 0-9, short-word, common-word,
and technical prompts with immutable trajectory/image references, known label, session ID, and
model predictions.

## Performance

No extra live inference stage was added. Width 6 changes raster thickness only. Base CPU inference
is still too slow for a fluid preview on this machine (3.08 s warm median in the model comparison).
Small is substantially faster but fails accuracy gates, and Large cannot be loaded safely. Model
loading remains lazy and cached once per process.

## Tests

Automated coverage includes model-input geometry, resampling endpoint/dot preservation, word
segmentation, immutable manifests, guided collection records, and archived renderer behavior. Run:

```powershell
pytest -q
ruff check touchwrite tests
python -m compileall -q touchwrite
python -m touchwrite.tools.regress_whiteboard
```

The preprocessing and recognizer JSON outputs are generated evidence and intentionally ignored by
Git; their Markdown summaries and permanent labeled manifests are versioned.

## Files Changed

- Recognition: score-bearing candidates and sequence-score diagnostics.
- Rendering configuration: measured 6 px default recognition width.
- Diagnostics: extended trajectory timing, geometry, pressure, smoothness, and occupancy metrics.
- Research tools: bounded preprocessing, recognizer, trajectory visualization, resampling, and
  conservative segmentation utilities.
- Evaluation data: separate historical and current-touchscreen verified manifests.
- Collection: guided append-only session manifests and CLI.
- Dependencies: SentencePiece for the official TrOCR Small tokenizer.

## Final Architecture

The production path remains deliberately small:

```text
raw immutable strokes
  -> existing moving-average smoothing
  -> existing 512x128 aspect-preserving renderer (6 px recognition stroke)
  -> official slow TrOCR processor (direct 384x384 resize)
  -> TrOCR Base deterministic beam search
  -> raw editable prediction + scored diagnostic alternatives
  -> immutable sample store / optional guided-label session
```

Letterboxing, forced occupancy, resampling, per-word auto-segmentation, Small, and Large are not in
the live path. The next accuracy step is collecting repeated labeled physical examples for
personalization, not adding output-specific correction rules.

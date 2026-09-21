# TouchWrite recognition diagnosis

Assessment date: 2026-09-21

## Executive finding

The primary failure was geometric, not a broken TrOCR checkpoint. TouchWrite normalized X and Y by
different canvas dimensions, then rendered those normalized values as though their units were equal.
On the first `hardhik` sample, the stored physical trajectory aspect ratio was 4.110 while the
renderer used 1.439—a 2.857× horizontal compression. The 512×192 result was then resized by the
TrOCR processor to 384×384, compressing the model-visible word further. The exact old model input
shows overlapping, vertically elongated letters.

The session also contains point-click noise and one incomplete sample. These are separate issues:
an isolated far-right point in sample `936a77a8` rendered as a period, while sample `76d7df85`
contains only an `is`-like trace and cannot truthfully be labeled as `hardhik`.

## Exact pipeline before diagnosis

```text
mouse events -> normalized Point(x, y) -> moving-average x/y only
-> normalized-coordinate bounding box -> 512x192 grayscale rendering
-> RGB conversion -> TrOCRProcessor resize to 384x384
-> deterministic beam=4 generation -> first decoded beam -> trim whitespace
```

There was no OpenCV operation in this runtime path, so there was no BGR/RGB conversion bug. Images
were opaque grayscale, converted to RGB immediately before the processor, with black ink on a white
background and pixel range 0–255.

## Failed sample inspection

| Property | `936a77a8` | `76d7df85` |
|---|---:|---:|
| Historical prediction | `2 . Hardix .` | `100 lb ... .` |
| Expected label | `hardhik` | Unknown; image is not a complete word |
| Strokes / points | 12 / 443 | 4 / 132 |
| Zero-length point strokes | 4 | 1 |
| Normalized trajectory aspect | 1.439 | 0.354 |
| Raw-coordinate aspect | 4.110 | 1.086 |
| Old raw/processed dimensions | 512×192 | 512×192 |
| Old raw/processed mode | L / L | L / L |
| Old foreground bbox | 148,20–364,173 | 226,19–286,173 |
| Old processed ink percentage | 9.714% | 3.179% |
| Pixel range | 0–255 | 0–255 |
| Old preprocessing | padding 24, width 8, supersample 3, smoothing 3 | same |

`936a77a8` included a zero-length point at raw coordinate `(429.3, 62.0)`, about 65 pixels beyond
the substantive word. It is visible as the final period in the historical rendering. Nearby point
strokes were retained because they plausibly represent dots over `i`.

`76d7df85` spans only raw X 53.3–120.7 and contains two connected shapes. Its exact new model input
visually resembles `is`; no OCR model can recover seven missing letters from this evidence. It is
excluded from labeled accuracy metrics.

Native gesture contacts were not mixed into the handwriting buffer: the touchpad provider sends
them only to `GestureEngine`, and right-button events are intercepted as commits before left-stroke
capture. The zero-length records are ordinary left press/release pairs. Thus there is evidence of
isolated click noise and incomplete capture, but not two-finger coordinates being rendered as ink.

## Controlled preprocessing comparison

Two visually verified `hardhik` samples were labeled. Historical stroke arrays were SHA-256 checked
before and after labeling and remained unchanged.

| Variant | `936a77a8` | `cff0bd65` | Finding |
|---|---|---|---|
| Historical pipeline | `2 . Hardix .` | `2 monthik ... .` | Severe geometric distortion |
| Physical aspect, square letterbox, width 8 | `modix .` | `naurdhi k` | Better but mismatched to TrOCR's line-image resize |
| Inverted polarity | `most bank .` | `membershire .` | Clearly worse |
| 512×128 raw-aspect canvas, width 8, beam 8 | `hardix` | `hardhik` | Best fixed general pipeline |

The chosen 512×128 canvas retains physical trajectory geometry before the checkpoint's documented
384×384 processor resize. It does not hardcode the aspect of a particular word. Light smoothing had
no material benefit by itself, but remains safe after it was fixed to update raw render coordinates.

The production rerun changed the two labeled samples from 0/2 exact matches to 1/2. Aggregate
case-sensitive CER fell from 1.5000 to 0.1429. Per-sample results:

| Expected | Before | After | Before CER | After CER |
|---|---|---|---:|---:|
| `hardhik` | `2 . Hardix .` | `hardix` | 1.2857 | 0.2857 |
| `hardhik` | `2 monthik ... .` | `hardhik` | 1.7143 | 0.0000 |

The selected `hardhik` output is a direct TrOCR beam candidate. Candidate selection merely enforces
TouchWrite's existing one-word boundary by preferring the first candidate without whitespace or
surrounding punctuation. It performs no dictionary lookup and contains no user-name rule.

## Processor and generation controls

- Slow processor: `ViTImageProcessor`; fast processor: `ViTImageProcessorFast`.
- Both produced `hardhi K` as raw top beam and selected `hardhik` on the same corrected sample.
- Maximum absolute tensor difference was `5.9139e-8`; mean was `6.8023e-10`.
- `use_fast=False` is explicit for reproducibility and avoids requiring torchvision in production.
- Generation is deterministic: `do_sample=False`, 8 beams, 8 returned sequences, 24 maximum new
  tokens, early stopping, and length penalty 1.0.

## Model health and pooler warning

The model recognized a genuine IAM-derived reference line from the public
[`cyttic/iam-lines-real`](https://huggingface.co/datasets/cyttic/iam-lines-real) test split with expected text
`is to be made at a meeting of Labour` as `is to be made at # meeting of Labour` (one substitution,
CER 0.0278). This supports a working checkpoint and decoder.

Transformers 4.57.6 constructs a ViT pooler whose two parameters are absent from the checkpoint,
causing the warning. `VisionEncoderDecoderModel.forward` consumes `encoder_outputs[0]` (the last
hidden state), not the pooler output. A controlled intervention replaced both pooler parameters with
large random values; generated token IDs remained byte-identical. The warning is therefore noisy
but does not affect this inference path, and no dependency downgrade is justified.

## Timing

Measured on CPU with the corrected `cff0bd65` sample:

- Model load: 3794.6 ms
- First inference after load: 2993.4 ms
- Five warm runs: 2800.7, 2766.9, 2784.3, 2837.9, 2859.0 ms
- Warm median: 2800.7 ms
- Warm p95: 2854.8 ms
- Typical processor conversion: about 10 ms
- Generation dominates latency; decoding is about 1 ms

The same recognizer object was used for all repetitions, verifying one model load.

## Implemented fix

1. Render from retained raw window coordinates instead of distorted normalized units.
2. Use a measured 512×128 canvas with padding 16, stroke width 8, and 3× supersampling.
3. Smooth both normalized and raw coordinate fields.
4. Exclude only isolated zero-length strokes far from substantive ink at render time; raw
   trajectories remain intact and nearby dots are preserved.
5. Make processor mode and deterministic generation parameters explicit.
6. Increase the candidate beam to 8 and apply the one-word structural constraint.
7. Record model-load, processor, generation, decoding, and total timings separately.
8. Add optional exact model-input debug artifacts and a GUI-independent recognition CLI.

## Remaining limitation

This fixes the demonstrated preprocessing failure and one clean sample exactly, but does not make
the ambiguous `936a77a8` handwriting exact and cannot reconstruct the missing content in
`76d7df85`. More corrected real samples are required before comparing another checkpoint. TrOCR
Large was not downloaded: the machine had only 2.8 GB free RAM during diagnosis, making a controlled
CPU comparison unsafe and likely to page heavily.

# Recognition pipeline

## Baseline model

V1 uses `microsoft/trocr-base-handwritten` through Hugging Face Transformers. It is an
encoder-decoder image recognizer pretrained/fine-tuned for handwritten text and supports a local
CPU path. The application explicitly segments input at word boundaries, which reduces the long-line
segmentation problem.

TrOCR is a baseline, not a permanent assumption. `HandwritingRecognizer` accepts a typed
`RecognitionSample` and returns text, model identity, measured duration, optional calibrated
confidence, and alternatives. `OnlineHandwritingRecognizer` and `EnsembleRecognizer` preserve the
replacement boundary.

## Preprocessing

1. Preserve the original `HandwrittenWord` trajectory.
2. Optionally smooth each stroke with a three-sample moving average while preserving endpoints.
3. Calculate the normalized ink bounding box.
4. Fit it into a 512×192 image with controlled padding and preserved aspect ratio.
5. Supersample 3×, draw rounded strokes, and downsample with Lanczos.
6. Convert the model image to RGB through the model processor.
7. Use beam generation and retain unique alternatives.

Both unsmoothed `raw.png` and smoothed/model-ready `processed.png` are stored.

## Runtime behavior

The processor and model load lazily on the first commit and remain cached on the recognizer object.
`QThreadPool` executes loading and inference away from the UI thread. CUDA is selected only when
PyTorch reports it available; an unavailable requested CUDA device falls back to CPU with a log.

TrOCR generation scores are not calibrated confidence probabilities, so V1 reports confidence as
unavailable instead of fabricating a value.

## Measured smoke result

On the assessed machine, a generated 512×192 image containing the word `hello` was recognized as
`hello` by `microsoft/trocr-base-handwritten` on CPU. Model-only inference measured 3379.4 ms after
loading; `hello .` was retained as an alternative. This is a functional smoke test, not an accuracy
benchmark and not representative of touchpad handwriting.

## Evaluation

`python -m touchwrite.tools.evaluate` evaluates only samples with human corrections. It reports:

- exact word accuracy;
- character error rate using Levenshtein distance divided by reference character count;
- word error rate;
- average measured inference latency;
- per-sample expected and predicted strings.

Do not compare models on training samples used for personalization. Create user-stratified train,
validation, and held-out test splits once enough labels exist.


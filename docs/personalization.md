# Personalization

## Collection from first use

Every successfully recognized word is assigned a UUID and saved to a new directory. Trajectories
contain normalized and raw coordinates, timestamp, contact ID, down state, deltas, velocity, stroke
ID, and order. Metadata keeps raw prediction, final prediction, model, confidence when genuinely
available, and corrected text.

The **Correct last prediction** action writes only label fields using atomic file replacement. It
does not overwrite trajectory or image files. Export corrected samples with:

```powershell
python -m touchwrite.tools.export_dataset
```

## Data quality before training

Twenty words are not enough for a reliable personal model. Collect repeated coverage of lowercase,
uppercase, digits, punctuation, common words, and the user's names/domain vocabulary. Review labels
and exclude accidental strokes. Keep multiple natural versions of each word.

A useful initial target is thousands of labeled words with a held-out session-based test split.
Split by recording session—not random near-duplicates—so evaluation measures generalization.

## Next online model

The trajectory model input should be a masked sequence such as:

```text
[x, y, dx, dy, velocity, pen_state, stroke_boundary]
```

A compact Transformer encoder with CTC projection is a reasonable first experiment. A BiLSTM-CTC
baseline should also be trained because it is simpler and can outperform larger models on modest
personal datasets. Neither should replace TrOCR until held-out exact word accuracy and CER are
better at an acceptable latency.

## Future fusion

An ensemble should compare image and online candidate sequences, then apply a reversible contextual
ranking step. Fusion weights must be fit on validation data. Store all component predictions so a
later correction never destroys evidence from the original model.


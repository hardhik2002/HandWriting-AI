# TouchWrite preprocessing benchmark

Model: `microsoft/trocr-base-handwritten`

| Variant | Historical exact | Touchscreen exact | Touchscreen CER | Segment exact | Segment CER | Median ms |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 100.0% | 33.3% | 39.7% | 14.3% | 122.7% | 2892 |
| stroke_6 | 100.0% | 33.3% | 20.6% | 14.3% | 113.6% | 4045 |
| stroke_10 | 100.0% | 33.3% | 46.0% | 14.3% | 140.9% | 4703 |
| stroke_12 | 100.0% | 33.3% | 47.6% | 14.3% | 122.7% | 5057 |
| no_smoothing | 100.0% | 33.3% | 39.7% | 14.3% | 122.7% | 7723 |
| resample_2 | 100.0% | 33.3% | 41.3% | 14.3% | 122.7% | 4990 |
| full_letterbox | 100.0% | 0.0% | 74.6% | 14.3% | 95.5% | 11965 |
| occupancy_05 | 0.0% | 16.7% | 69.8% | 14.3% | 81.8% | 6721 |
| occupancy_10 | 0.0% | 16.7% | 66.7% | 14.3% | 104.5% | 6262 |
| occupancy_15 | 0.0% | 16.7% | 66.7% | 14.3% | 104.5% | 5323 |
| occupancy_20 | 0.0% | 16.7% | 66.7% | 14.3% | 104.5% | 5593 |
| occupancy_25 | 0.0% | 16.7% | 66.7% | 14.3% | 104.5% | 4702 |
| occupancy_30 | 0.0% | 16.7% | 66.7% | 14.3% | 104.5% | 4857 |

"""Export corrected TouchWrite samples as portable JSON Lines metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def export_dataset(data_dir: Path, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("w", encoding="utf-8") as destination:
        for metadata_path in sorted(data_dir.glob("*/metadata.json")):
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            label = metadata.get("corrected_text")
            if not label:
                continue
            sample_dir = metadata_path.parent
            record = {
                "word_id": metadata["word_id"],
                "label": label,
                "prediction": metadata.get("prediction"),
                "trajectory": str(sample_dir / "trajectory.json"),
                "raw_image": str(sample_dir / "raw.png"),
                "processed_image": str(sample_dir / "processed.png"),
            }
            destination.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/handwriting"))
    parser.add_argument("--output", type=Path, default=Path("reports/dataset.jsonl"))
    arguments = parser.parse_args()
    count = export_dataset(arguments.data_dir, arguments.output)
    print(f"Exported {count} labeled samples to {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


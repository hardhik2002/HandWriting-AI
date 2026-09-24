"""Benchmark enabled local handwriting recognizers on identical labeled manifests."""

from __future__ import annotations

import argparse
import gc
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

from touchwrite.config.settings import Settings
from touchwrite.diagnostics.accuracy import character_error_count
from touchwrite.recognition.base import RecognitionSample
from touchwrite.recognition.image_recognizer import ImageHandwritingRecognizer
from touchwrite.tools.benchmark_preprocessing import (
    BASELINE_VARIANT,
    load_evaluation_items,
    percentile,
    render_variant,
)

DEFAULT_MODELS = (
    "microsoft/trocr-base-handwritten",
    "microsoft/trocr-small-handwritten",
)
LARGE_MODEL = "microsoft/trocr-large-handwritten"


def available_memory_bytes() -> int | None:
    if os.name != "nt":
        return None
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("memory_load", ctypes.c_ulong),
            ("total_physical", ctypes.c_ulonglong),
            ("available_physical", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("available_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended_virtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.available_physical)


def process_working_set_bytes() -> int | None:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("page_fault_count", wintypes.DWORD),
            ("peak_working_set_size", ctypes.c_size_t),
            ("working_set_size", ctypes.c_size_t),
            ("quota_peak_paged_pool_usage", ctypes.c_size_t),
            ("quota_paged_pool_usage", ctypes.c_size_t),
            ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
            ("quota_non_paged_pool_usage", ctypes.c_size_t),
            ("pagefile_usage", ctypes.c_size_t),
            ("peak_pagefile_usage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCounters),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    handle = kernel32.GetCurrentProcess()
    if not psapi.GetProcessMemoryInfo(
        handle, ctypes.byref(counters), counters.cb
    ):
        return None
    return int(counters.working_set_size)


def benchmark_model(
    model_name: str,
    items: list[dict[str, Any]],
    settings: Settings,
) -> dict[str, Any]:
    memory_before = process_working_set_bytes()
    available_before = available_memory_bytes()
    recognizer = ImageHandwritingRecognizer(
        model_name,
        settings.model_device,
        settings.beam_width,
        settings.max_new_tokens,
        settings.processor_use_fast,
    )
    records = []
    for item in items:
        if item["domain"] == "touchscreen-segment":
            continue
        model_source = render_variant(item["word"], settings, BASELINE_VARIANT)
        started = time.perf_counter()
        result = recognizer.recognize(
            RecognitionSample(item["word"], model_source, "")
        )
        latency_ms = (time.perf_counter() - started) * 1000
        prediction = result.text.strip()
        records.append(
            {
                "sample_id": item["sample_id"],
                "domain": item["domain"],
                "expected": item["expected"],
                "prediction": prediction,
                "exact": prediction == item["expected"],
                "character_errors": character_error_count(item["expected"], prediction),
                "latency_ms": latency_ms,
                "sequence_score": result.sequence_score,
                "beam_candidates": [
                    {
                        "text": candidate.text,
                        "score": candidate.score,
                    }
                    for candidate in result.alternatives
                ],
            }
        )
    memory_after = process_working_set_bytes()
    domains = {}
    for domain in ("historical", "touchscreen"):
        selected = [record for record in records if record["domain"] == domain]
        errors = sum(record["character_errors"] for record in selected)
        characters = sum(len(record["expected"]) for record in selected)
        domains[domain] = {
            "samples": len(selected),
            "exact_accuracy": sum(record["exact"] for record in selected) / len(selected),
            "cer": errors / characters,
        }
    latencies = [record["latency_ms"] for record in records]
    return {
        "model": model_name,
        "status": "completed",
        "preprocessing": "stroke_6",
        "metrics": domains,
        "first_inference_ms": latencies[0] if latencies else None,
        "warm_median_ms": statistics.median(latencies[1:]) if len(latencies) > 1 else None,
        "warm_p95_ms": percentile(latencies[1:], 0.95) if len(latencies) > 1 else None,
        "working_set_delta_mb": (
            (memory_after - memory_before) / (1024 * 1024)
            if memory_before is not None and memory_after is not None
            else None
        ),
        "available_memory_before_mb": (
            available_before / (1024 * 1024) if available_before is not None else None
        ),
        "samples": records,
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# TouchWrite recognizer benchmark",
        "",
        "| Model | Status | Historical exact | Touchscreen exact | Touchscreen CER | "
        "Warm median ms | Warm p95 ms | RAM delta MB |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for model in report["models"]:
        if model["status"] != "completed":
            lines.append(
                f"| {model['model']} | {model['status']}: {model['reason']} | "
                "-- | -- | -- | -- | -- | -- |"
            )
            continue
        historical = model["metrics"]["historical"]
        touchscreen = model["metrics"]["touchscreen"]
        lines.append(
            "| {model} | completed | {historical:.1%} | {touchscreen:.1%} | {cer:.1%} | "
            "{median:.0f} | {p95:.0f} | {memory:.0f} |".format(
                model=model["model"],
                historical=historical["exact_accuracy"],
                touchscreen=touchscreen["exact_accuracy"],
                cer=touchscreen["cer"],
                median=model["warm_median_ms"] or 0.0,
                p95=model["warm_p95_ms"] or 0.0,
                memory=model["working_set_delta_mb"] or 0.0,
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="*", default=list(DEFAULT_MODELS))
    parser.add_argument("--include-large", action="store_true")
    parser.add_argument(
        "--output-json", type=Path, default=Path("reports/recognizer_benchmark.json")
    )
    parser.add_argument(
        "--output-md", type=Path, default=Path("reports/recognizer_benchmark.md")
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = Settings.from_environment()
    items = load_evaluation_items(
        Path("tests/fixtures/historical_accuracy.json"),
        Path("tests/fixtures/touchscreen_accuracy.json"),
        settings.data_dir,
    )
    models = list(dict.fromkeys(args.models))
    if args.include_large:
        models.append(LARGE_MODEL)
    output = []
    for model_name in models:
        available = available_memory_bytes()
        if model_name == LARGE_MODEL and (available is None or available < 6 * 1024**3):
            output.append(
                {
                    "model": model_name,
                    "status": "skipped",
                    "reason": "requires at least 6 GiB free RAM for a safe CPU benchmark",
                    "available_memory_mb": available / (1024 * 1024) if available else None,
                }
            )
            continue
        print(f"benchmarking recognizer {model_name}", flush=True)
        try:
            output.append(benchmark_model(model_name, items, settings))
        except Exception as error:  # optional benchmark adapters must fail independently
            output.append(
                {
                    "model": model_name,
                    "status": "failed",
                    "reason": str(error),
                }
            )
        gc.collect()
    report = {"models": output}
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_markdown(report, args.output_md)
    print(json.dumps({"models": len(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

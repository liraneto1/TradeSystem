"""Offline chronological forecast evaluation; not a trading backtest."""

import argparse
import csv
from dataclasses import asdict
import hashlib
import json
import math
import platform
from importlib.metadata import version
from pathlib import Path
import sys

from .market import INTERVALS, parse_candles
from .kronos_setup import ROOT, lock, verify_source, weight_hashes


def load_dataset(path):
    metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
    with (path / "candles.csv").open(encoding="utf-8", newline="") as stream:
        rows = [[r[k] for k in ("open_time", "open", "high", "low", "close", "volume", "close_time", "amount")]
                for r in csv.DictReader(stream)]
    candles = parse_candles(rows, metadata["interval"], metadata["end_time_exclusive"])
    if (len(candles) != metadata["count"] or not candles or
            candles[0].open_time != metadata["start_time"] or
            candles[-1].close_time + 1 != metadata["end_time_exclusive"]):
        raise ValueError("Dataset does not match metadata")
    return candles, metadata


class KronosForecaster:
    def __init__(self, seed=42):
        pins = lock()
        source = ROOT / ".vendor/Kronos"
        verify_source(source, pins["source_revision"])
        prepared = json.loads((ROOT / "models/prepared.json").read_text())
        if prepared != {"pins": pins, "sha256": weight_hashes()}:
            raise ValueError("Local weights do not match pinned preparation; run kronos_setup")
        import torch
        import numpy as np
        import pandas as pd
        # Upstream uses absolute imports from its `model` package.
        if "model" in sys.modules:
            raise RuntimeError("Run forecast in a fresh process to avoid upstream module collisions")
        sys.path.insert(0, str(source))
        from model import Kronos, KronosTokenizer, KronosPredictor
        torch.set_num_threads(4)
        self.torch, self.np, self.pd, self.seed = torch, np, pd, seed
        tokenizer = KronosTokenizer.from_pretrained(str(ROOT / "models/tokenizer"), local_files_only=True)
        model = Kronos.from_pretrained(str(ROOT / "models/model"), local_files_only=True)
        tokenizer.eval()
        model.eval()
        self.predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512)

    def predict(self, history, horizon, step):
        if not 2 <= len(history) <= 512 or not 1 <= horizon <= 512:
            raise ValueError("Context 2..512 and horizon 1..512 required")
        pd = self.pd
        frame = pd.DataFrame([{k: float(v) for k, v in asdict(c).items()
                               if k in ("open", "high", "low", "close", "volume", "amount")} for c in history])
        past = pd.Series(pd.to_datetime([c.open_time for c in history], unit="ms", utc=True))
        future_ms = [history[-1].open_time + step * (i + 1) for i in range(horizon)]
        future = pd.Series(pd.to_datetime(future_ms, unit="ms", utc=True))
        self.torch.manual_seed(self.seed)
        self.np.random.seed(self.seed)
        with self.torch.inference_mode():
            result = self.predictor.predict(frame, past, future, pred_len=horizon,
                                            T=1.0, top_p=0.9, sample_count=1, verbose=False)
        values = [float(x) for x in result["close"]]
        if len(values) != horizon or any(not math.isfinite(x) or x <= 0 for x in values):
            raise ValueError("Invalid model forecast")
        return values


def evaluate(candles, predictor, *, step, lookback=128, horizon=4, windows=5):
    if not 2 <= lookback <= 512 or not 1 <= horizon <= 512 or windows < 1:
        raise ValueError("Invalid evaluation dimensions")
    if len(candles) < lookback + horizon * windows:
        raise ValueError("Insufficient history for non-overlapping evaluation windows")
    rows = []
    start = len(candles) - windows * horizon
    for origin in range(start, len(candles), horizon):
        history = candles[origin - lookback:origin]
        values = predictor.predict(history, horizon, step)
        if len(values) != horizon or any(not math.isfinite(float(x)) or x <= 0 for x in values):
            raise ValueError("Invalid predictions")
        baseline = float(history[-1].close)
        for offset, prediction in enumerate(values):
            actual = candles[origin + offset]
            rows.append({"origin_time": history[-1].close_time, "target_time": actual.open_time,
                         "horizon_step": offset + 1, "actual_close": float(actual.close),
                         "predicted_close": float(prediction), "baseline_close": baseline})
    mae = lambda field: sum(abs(r[field] - r["actual_close"]) for r in rows) / len(rows)
    model_mae, baseline_mae = mae("predicted_close"), mae("baseline_close")
    return rows, {"model_mae_usdt": model_mae, "baseline_mae_usdt": baseline_mae,
                  "model_beats_baseline": model_mae < baseline_mae, "windows": windows,
                  "horizon": horizon, "lookback": lookback, "target_count": len(rows),
                  "warning": "Forecast error only; no trading PnL, costs or profitability claim. Training-data overlap not audited."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lookback", type=int, default=128)
    parser.add_argument("--horizon", type=int, default=4)
    parser.add_argument("--windows", type=int, default=5)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output must be a new directory")
    candles, metadata = load_dataset(args.dataset)
    rows, metrics = evaluate(candles, KronosForecaster(), step=INTERVALS[metadata["interval"]],
                             lookback=args.lookback, horizon=args.horizon, windows=args.windows)
    metrics.update({"pins": lock(), "seed": 42, "device": "cpu", "sample_count": 1,
                    "temperature": 1.0, "top_p": 0.9, "weight_sha256": weight_hashes(),
                    "python": platform.python_version(),
                    "packages": {name: version(name) for name in
                                 ("torch", "numpy", "pandas", "huggingface_hub", "einops", "safetensors")},
                    "dataset_metadata": metadata,
                    "dataset_sha256": hashlib.sha256((args.dataset / "candles.csv").read_bytes()).hexdigest()})
    args.output.mkdir(parents=True)
    with (args.output / "predictions.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in metrics.items() if k not in ("pins", "dataset_metadata")}, indent=2))


if __name__ == "__main__":
    main()

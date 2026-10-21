"""Causal SMC research signals. Signals are proposals, not filled trades."""

import argparse
import csv
from dataclasses import asdict, dataclass
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path

from .forecast import load_dataset
from .market import Candle, INTERVALS


@dataclass(frozen=True)
class SMCConfig:
    pivot_left: int = 2
    pivot_right: int = 2
    atr_period: int = 14
    confirmation_bars: int = 6
    entry_expiry_bars: int = 4
    displacement_atr: D = D("1")
    min_gap_atr: D = D("0.05")
    stop_buffer_atr: D = D("0.10")
    reward_risk: D = D("2")

    def __post_init__(self):
        for key in ("pivot_left", "pivot_right", "atr_period", "confirmation_bars", "entry_expiry_bars"):
            value = getattr(self, key)
            if type(value) is not int or value < 1:
                raise ValueError(f"{key} must be a positive integer")
        if self.confirmation_bars < 2:
            raise ValueError("Confirmation requires at least two bars after sweep")
        for key in ("displacement_atr", "min_gap_atr", "stop_buffer_atr", "reward_risk"):
            value = getattr(self, key)
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{key} must be finite and positive")

    @classmethod
    def load(cls, path):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        for key in ("displacement_atr", "min_gap_atr", "stop_buffer_atr", "reward_risk"):
            if key in raw:
                raw[key] = D(str(raw[key]))
        return cls(**raw)


@dataclass(frozen=True)
class Pivot:
    index: int
    price: D
    confirmed_index: int


def confirmed_pivot(candles, index, left, right, kind):
    """At close `index`, only the candidate `index-right` can become known."""
    candidate = index - right
    if candidate < left:
        return None
    name = "high" if kind == "HIGH" else "low"
    price = getattr(candles[candidate], name)
    others = [getattr(candles[j], name) for j in range(candidate-left, index+1) if j != candidate]
    if (kind == "HIGH" and all(price > x for x in others)) or (kind == "LOW" and all(price < x for x in others)):
        return Pivot(candidate, price, index)
    return None


def previous_atr(candles, index, period):
    """Arithmetic mean of previous true ranges; excludes the current bar."""
    if index < period:
        return None
    ranges = []
    for j in range(index-period, index):
        c = candles[j]
        previous_close = candles[j-1].close if j else c.open
        ranges.append(max(c.high-c.low, abs(c.high-previous_close), abs(c.low-previous_close)))
    return sum(ranges, D(0)) / period


@dataclass(frozen=True)
class Sweep:
    side: str
    index: int
    liquidity: Pivot
    structure: Pivot
    extreme: D
    atr: D


@dataclass(frozen=True)
class SMCSignal:
    side: str
    sweep_index: int
    signal_index: int
    signal_time: int
    liquidity_pivot_index: int
    liquidity_known_time: int
    liquidity_level: D
    structure_level: D
    gap_low: D
    gap_high: D
    limit_entry: D
    stop: D
    target: D
    active_from: int
    expires_at: int


def generate_signals(candles: list[Candle], config: SMCConfig, *, step: int) -> list[SMCSignal]:
    if type(step) is not int or step <= 0:
        raise ValueError("Positive interval in milliseconds required")
    for i, candle in enumerate(candles):
        values = (candle.open, candle.high, candle.low, candle.close, candle.volume, candle.amount)
        if (any(not x.is_finite() for x in values) or min(values[:4]) <= 0 or
                min(values[4:]) < 0 or candle.high < max(candle.open, candle.close, candle.low) or
                candle.low > min(candle.open, candle.close) or candle.open_time % step or
                candle.open_time < 0 or candle.close_time != candle.open_time+step-1 or
                (i and candle.open_time != candles[i-1].open_time+step)):
            raise ValueError("Invalid or non-contiguous candle history")
    high = low = pending = None
    used_high, used_low = set(), set()
    signals = []
    for i, c in enumerate(candles):
        # Only pivots known BEFORE this candle are eligible as liquidity levels.
        breach_low = low is not None and low.index not in used_low and c.low < low.price
        breach_high = high is not None and high.index not in used_high and c.high > high.price
        if breach_low:
            used_low.add(low.index)
        if breach_high:
            used_high.add(high.index)
        emitted = False
        if pending:
            invalid = c.low <= pending.extreme if pending.side == "LONG" else c.high >= pending.extreme
            if i - pending.index > config.confirmation_bars or invalid:
                pending = None
            elif i >= pending.index + 2:
                a, b = candles[i-2], candles[i-1]
                atr = previous_atr(candles, i-1, config.atr_period)
                bull = pending.side == "LONG"
                gap_low, gap_high = (a.high, c.low) if bull else (c.high, a.low)
                displacement = b.close-b.open if bull else b.open-b.close
                structure_break = c.close > pending.structure.price if bull else c.close < pending.structure.price
                if (atr and structure_break and displacement >= atr*config.displacement_atr and
                        gap_high-gap_low >= atr*config.min_gap_atr):
                    entry = (gap_low+gap_high)/2
                    buffer = pending.atr*config.stop_buffer_atr
                    stop = pending.extreme-buffer if bull else pending.extreme+buffer
                    distance = entry-stop if bull else stop-entry
                    target = entry+distance*config.reward_risk if bull else entry-distance*config.reward_risk
                    if distance > 0 and stop > 0 and target > 0:
                        signals.append(SMCSignal(
                            pending.side, pending.index, i, c.close_time,
                            pending.liquidity.index, candles[pending.liquidity.confirmed_index].close_time,
                            pending.liquidity.price, pending.structure.price, gap_low, gap_high,
                            entry, stop, target, c.close_time+1,
                            c.close_time+config.entry_expiry_bars*step))
                        emitted = True
                    pending = None
        atr = previous_atr(candles, i, config.atr_period)
        # Outside bars taking both sides are ambiguous and never create a new setup.
        if pending is None and not emitted and atr and not (breach_low and breach_high):
            if breach_low and high is not None and low.price < c.close < high.price:
                pending = Sweep("LONG", i, low, high, c.low, atr)
            elif breach_high and low is not None and low.price < c.close < high.price:
                pending = Sweep("SHORT", i, high, low, c.high, atr)
        # A pivot confirmed at this close is available from the NEXT candle.
        high = confirmed_pivot(candles, i, config.pivot_left, config.pivot_right, "HIGH") or high
        low = confirmed_pivot(candles, i, config.pivot_left, config.pivot_right, "LOW") or low
    return signals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[1]/"config/smc.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = SMCConfig.load(args.config)
    candles, metadata = load_dataset(args.dataset)
    signals = generate_signals(candles, config, step=INTERVALS[metadata["interval"]])
    summary = {"strategy": "SMC sweep-MSS-FVG v0.1", "candles": len(candles),
               "signals": len(signals), "long": sum(x.side == "LONG" for x in signals),
               "short": sum(x.side == "SHORT" for x in signals), "config": asdict(config),
               "dataset_sha256": hashlib.sha256((args.dataset/"candles.csv").read_bytes()).hexdigest(),
               "dataset_metadata": metadata,
               "warning": "Candidates only. No fills, quantity, funding, liquidation, fees or PnL calculated."}
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output/"signals.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(SMCSignal.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(signal) for signal in signals)
    (args.output/"summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"SMC candidates: {len(signals)} ({summary['long']} long, {summary['short']} short). No trades executed.")


if __name__ == "__main__":
    main()

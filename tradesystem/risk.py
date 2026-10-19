"""Deterministic sizing; no exchange credentials or network access."""

from dataclasses import dataclass, fields
from decimal import Decimal, ROUND_FLOOR
import json
from pathlib import Path

D = Decimal


def positive(value: Decimal) -> bool:
    return value.is_finite() and value > 0


@dataclass(frozen=True)
class RiskConfig:
    capital_usdt: Decimal
    max_leverage: Decimal
    risk_per_trade: Decimal
    daily_loss_limit: Decimal
    max_margin_fraction: Decimal
    fee_rate_per_side: Decimal
    slippage_rate_per_side: Decimal

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if not value.is_finite() or value < 0:
                raise ValueError(f"Invalid {field.name}")
        if not positive(self.capital_usdt) or not D(1) <= self.max_leverage <= D(10):
            raise ValueError("Capital must be positive; leverage must be between 1 and 10")
        for name in ("risk_per_trade", "daily_loss_limit", "max_margin_fraction"):
            if not D(0) < getattr(self, name) <= D(1):
                raise ValueError(f"Invalid fraction: {name}")

    @classmethod
    def load(cls, path: str | Path):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if raw.pop("mode", None) != "paper":
            raise ValueError("Only paper mode is implemented")
        return cls(**{key: D(str(value)) for key, value in raw.items()})


@dataclass(frozen=True)
class InstrumentRules:
    step_size: Decimal
    min_quantity: Decimal
    min_notional: Decimal

    def __post_init__(self):
        if not all(positive(x) for x in (self.step_size, self.min_quantity, self.min_notional)):
            raise ValueError("Instrument filters must be finite and positive")


@dataclass(frozen=True)
class OrderPlan:
    side: str
    entry: Decimal
    stop: Decimal
    quantity: Decimal
    leverage: Decimal
    estimated_stop_loss: Decimal


def size_order(config: RiskConfig, rules: InstrumentRules, *, side: str,
               entry: Decimal, stop: Decimal, leverage: Decimal,
               equity: Decimal, available_margin: Decimal,
               daily_pnl: Decimal, has_position: bool = False) -> OrderPlan:
    if not all(positive(x) for x in (entry, stop, leverage, equity)):
        raise ValueError("Prices, leverage and equity must be finite and positive")
    if not available_margin.is_finite() or available_margin < 0 or not daily_pnl.is_finite():
        raise ValueError("Invalid account state")
    if has_position:
        raise ValueError("Only one open position is permitted")
    if side not in ("LONG", "SHORT"):
        raise ValueError("Invalid side")
    if (side == "LONG" and stop >= entry) or (side == "SHORT" and stop <= entry):
        raise ValueError("Stop must be on the loss side")
    if not D(1) <= leverage <= config.max_leverage:
        raise ValueError("Leverage exceeds policy")
    if daily_pnl <= -config.capital_usdt * config.daily_loss_limit:
        raise ValueError("Daily loss limit reached")
    # Fixed initial capital is the daily reference in this prototype.
    remaining_daily_budget = config.capital_usdt * config.daily_loss_limit + min(daily_pnl, D(0))
    risk_budget = min(equity * config.risk_per_trade, remaining_daily_budget)
    cost_rate = config.fee_rate_per_side + config.slippage_rate_per_side
    loss_per_unit = abs(entry - stop) + (entry + stop) * cost_rate
    margin_budget = min(available_margin, equity * config.max_margin_fraction)
    # Reserve estimated entry costs in addition to initial margin.
    margin_per_unit = entry / leverage + entry * cost_rate
    raw_quantity = min(risk_budget / loss_per_unit, margin_budget / margin_per_unit)
    quantity = (raw_quantity / rules.step_size).to_integral_value(rounding=ROUND_FLOOR) * rules.step_size
    if quantity < rules.min_quantity or quantity * entry < rules.min_notional:
        raise ValueError("Risk budget cannot satisfy instrument minimums")
    return OrderPlan(side, entry, stop, quantity, leverage, quantity * loss_per_unit)

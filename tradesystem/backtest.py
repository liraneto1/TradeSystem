"""Exploratory isolated-margin SMC backtest. No exchange orders or credentials."""

import argparse
from collections import Counter
import csv
from dataclasses import asdict, dataclass
from decimal import Decimal as D, ROUND_FLOOR, ROUND_CEILING
import hashlib
import json
from pathlib import Path

from .forecast import load_dataset
from .market import Candle, INTERVALS
from .risk import InstrumentRules, OrderPlan, RiskConfig, size_order
from .smc import SMCConfig, SMCSignal, generate_signals

DAY = 86_400_000


@dataclass(frozen=True)
class ExecutionRules:
    lot: InstrumentRules
    tick_size: D
    max_quantity: D
    min_price: D
    max_price: D

    def __post_init__(self):
        if any(not x.is_finite() or x <= 0 for x in
               (self.tick_size, self.max_quantity, self.min_price, self.max_price)):
            raise ValueError("Execution filters must be finite and positive")
        if self.max_price < self.min_price or self.max_quantity < self.lot.min_quantity:
            raise ValueError("Invalid execution filter bounds")

    @classmethod
    def from_metadata(cls, metadata):
        filters = {f["filterType"]: f for f in metadata["symbol_snapshot"]["filters"]}
        lot, price = filters["LOT_SIZE"], filters["PRICE_FILTER"]
        return cls(InstrumentRules(D(lot["stepSize"]), D(lot["minQty"]),
                                   D(filters["MIN_NOTIONAL"]["notional"])),
                   D(price["tickSize"]), D(lot["maxQty"]), D(price["minPrice"]), D(price["maxPrice"]))

    def round(self, value, upward):
        return (value/self.tick_size).to_integral_value(rounding=ROUND_CEILING if upward else ROUND_FLOOR)*self.tick_size


@dataclass(frozen=True)
class BacktestConfig:
    leverage: D = D(2)
    maintenance_margin_rate: D = D("0.005")
    daily_timezone: str = "UTC"
    liquidation_model: str = "isolated_fixed_rate_writeoff"

    def __post_init__(self):
        if not self.leverage.is_finite() or not D(1) <= self.leverage <= D(10):
            raise ValueError("Leverage must be 1..10")
        if not self.maintenance_margin_rate.is_finite() or not D(0) < self.maintenance_margin_rate < D(1):
            raise ValueError("Invalid assumed maintenance margin rate")
        if self.maintenance_margin_rate >= 1/self.leverage:
            raise ValueError("Maintenance requirement must be below initial isolated margin")
        if self.daily_timezone != "UTC" or self.liquidation_model != "isolated_fixed_rate_writeoff":
            raise ValueError("Unsupported daily timezone or liquidation model")

    @classmethod
    def load(cls, path):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        for key in ("leverage", "maintenance_margin_rate"):
            raw[key] = D(str(raw[key]))
        return cls(**raw)


@dataclass
class Position:
    signal: SMCSignal
    plan: OrderPlan
    target: D
    entry_bar: int
    entry_cost: D
    isolated_margin: D
    funding_paid: D = D(0)


def prepare_order(signal, risk, execution, config, balance, daily_pnl):
    bull = signal.side == "LONG"
    entry = execution.round(signal.limit_entry, upward=not bull)
    stop = execution.round(signal.stop, upward=not bull)
    target = execution.round(signal.target, upward=bull)
    if not signal.gap_low <= entry <= signal.gap_high:
        raise ValueError("Rounded entry outside FVG")
    if not all(execution.min_price <= p <= execution.max_price for p in (entry, stop, target)):
        raise ValueError("Price outside exchange bounds")
    if (bull and not stop < entry < target) or (not bull and not target < entry < stop):
        raise ValueError("Invalid rounded stop/entry/target")
    plan = size_order(risk, execution.lot, side=signal.side, entry=entry, stop=stop,
                      leverage=config.leverage, equity=balance, available_margin=balance,
                      daily_pnl=daily_pnl)
    if plan.quantity > execution.max_quantity:
        raise ValueError("Quantity exceeds exchange maximum")
    return plan, target


def mark_pnl(position, price):
    direction = D(1) if position.plan.side == "LONG" else D(-1)
    return direction*(price-position.plan.entry)*position.plan.quantity


def liquidation_price(position, maintenance_rate):
    plan = position.plan
    margin_per_unit = position.isolated_margin/plan.quantity
    if plan.side == "LONG":
        return max(D(0), (plan.entry-margin_per_unit)/(1-maintenance_rate))
    return (plan.entry+margin_per_unit)/(1+maintenance_rate)


def exit_decision(position, candle, mark, config, newly_filled=False):
    """Worst-case OHLC convention; liquidation takes priority, then stop, then target."""
    bull = position.plan.side == "LONG"
    liq = liquidation_price(position, config.maintenance_margin_rate)
    if position.isolated_margin <= 0 or (mark.low <= liq if bull else mark.high >= liq):
        return "LIQUIDATION_MODEL", liq
    stop = position.plan.stop
    if (candle.low <= stop if bull else candle.high >= stop):
        # A gap through the stop executes at the worse opening price.
        return "STOP", min(candle.open, stop) if bull else max(candle.open, stop)
    # On the entry candle a favorable excursion may have occurred before the fill.
    if not newly_filled and (candle.high >= position.target if bull else candle.low <= position.target):
        return "TARGET", position.target
    return None


def run_backtest(candles, marks, funding, signals, risk, execution, config):
    if not candles or len(marks) != len(candles):
        raise ValueError("Matching trade and mark candles required")
    if config.leverage > risk.max_leverage:
        raise ValueError("Backtest leverage exceeds policy")
    step = candles[0].close_time-candles[0].open_time+1
    # Reuse candle validation without changing the supplied strategy signals.
    generate_signals(candles, SMCConfig(), step=step)
    generate_signals(marks, SMCConfig(), step=step)
    if any(c.open_time != m.open_time for c,m in zip(candles, marks)):
        raise ValueError("Trade and mark timestamps differ")
    index = {c.open_time: i for i,c in enumerate(candles)}
    funding_by_bar = {}
    last_funding_time = -1
    for event in funding:
        time = int(event["time"])
        rate, price = D(str(event["rate"])), D(str(event["mark_price"]))
        bucket = time//step*step
        if (time <= last_funding_time or bucket not in index or not rate.is_finite() or
                not price.is_finite() or price <= 0):
            raise ValueError("Funding must be sorted, unique and within dataset coverage")
        funding_by_bar.setdefault(index[bucket], []).append((time, rate, price))
        last_funding_time = time
    signals_by_index = {}
    for s in signals:
        if (s.side not in ("LONG", "SHORT") or not 0 <= s.sweep_index < s.signal_index < len(candles) or
                s.signal_time != candles[s.signal_index].close_time or s.active_from != s.signal_time+1 or
                s.expires_at < s.active_from or (s.expires_at-s.signal_time) % step):
            raise ValueError("Invalid signal chronology")
        if s.signal_index in signals_by_index:
            raise ValueError("Multiple signals at one close are unsupported")
        signals_by_index[s.signal_index] = s
    balance = risk.capital_usdt
    pending = position = None
    trades, orders, curve, funding_log = [], [], [], []
    day, day_start, halted = None, balance, False
    peak, max_drawdown = balance, D(0)
    cost_rate = risk.fee_rate_per_side+risk.slippage_rate_per_side

    def settle_funding(i, c, mark, newly_filled=False):
        nonlocal balance
        if position is None:
            return
        for time, rate, price in funding_by_bar.get(i, []):
            if newly_filled and time <= c.open_time:
                continue
            raw_payment = (1 if position.plan.side == "LONG" else -1)*position.plan.quantity*price*rate
            # Charge possible debits; credit only an uninterrupted carried position.
            ambiguous = newly_filled or (time > c.open_time and exit_decision(position, c, mark, config) is not None)
            payment = max(D(0), raw_payment) if ambiguous else raw_payment
            balance -= payment
            position.funding_paid += payment
            position.isolated_margin -= payment
            funding_log.append({"time": time, "payment": payment, "raw_payment": raw_payment,
                                "conservative_intrabar": ambiguous})

    def finish(reason, price, c):
        nonlocal balance, position
        p = position
        if reason == "LIQUIDATION_MODEL":
            # Simplified isolated settlement: write off remaining allocated collateral.
            gross, exit_cost = -max(p.isolated_margin, D(0)), D(0)
        else:
            gross = mark_pnl(p, price)
            exit_cost = price*p.plan.quantity*cost_rate
        balance += gross-exit_cost
        trades.append({"side": p.plan.side, "signal_time": p.signal.signal_time,
                       "entry_bar_open": p.entry_bar, "exit_bar_close": c.close_time,
                       "entry": p.plan.entry, "exit": price, "quantity": p.plan.quantity,
                       "stop": p.plan.stop, "target": p.target, "reason": reason,
                       "gross_pnl": gross, "entry_cost": p.entry_cost, "exit_cost": exit_cost,
                       "funding_paid": p.funding_paid,
                       "net_pnl": gross-p.entry_cost-exit_cost-p.funding_paid})
        position = None

    for i, (c, mark) in enumerate(zip(candles, marks)):
        current_day = c.open_time//DAY
        if current_day != day:
            day, halted = current_day, False
            day_start = balance+(mark_pnl(position, mark.open) if position else 0)
        settle_funding(i, c, mark)
        if position:
            decision = exit_decision(position, c, mark, config)
            if decision:
                finish(*decision, c)
        if pending:
            signal, plan, target = pending
            sweep = candles[signal.sweep_index]
            bull = signal.side == "LONG"
            if c.open_time > signal.expires_at:
                orders.append({"time": c.open_time, "signal_time": signal.signal_time, "status": "EXPIRED"})
                pending = None
            elif (c.open <= sweep.low if bull else c.open >= sweep.high):
                orders.append({"time": c.open_time, "signal_time": signal.signal_time, "status": "INVALIDATED_AT_OPEN"})
                pending = None
            elif c.open_time >= signal.active_from:
                touched = c.low <= plan.entry if bull else c.high >= plan.entry
                if touched:
                    try:
                        if halted:
                            raise ValueError("Daily loss lock active")
                        fresh, _ = prepare_order(signal, risk, execution, config, balance, balance-day_start)
                        if fresh.quantity < plan.quantity:
                            raise ValueError("Reserved quantity no longer fits risk budget")
                    except ValueError as error:
                        orders.append({"time": c.open_time, "signal_time": signal.signal_time,
                                       "status": "REJECTED_AT_FILL", "detail": str(error)})
                    else:
                        entry_cost = plan.quantity*plan.entry*cost_rate
                        balance -= entry_cost
                        position = Position(signal, plan, target, c.open_time, entry_cost,
                                            plan.quantity*plan.entry/config.leverage)
                        settle_funding(i, c, mark, newly_filled=True)
                        orders.append({"time": c.open_time, "signal_time": signal.signal_time, "status": "FILLED"})
                        decision = exit_decision(position, c, mark, config, newly_filled=True)
                        if decision:
                            finish(*decision, c)
                    pending = None
                elif (c.low <= sweep.low if bull else c.high >= sweep.high):
                    orders.append({"time": c.close_time, "signal_time": signal.signal_time, "status": "INVALIDATED"})
                    pending = None
        if i == len(candles)-1 and position:
            finish("END_OF_DATA", c.close, c)
        equity = balance+(mark_pnl(position, mark.close) if position else 0)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak-equity)/peak)
        if equity-day_start <= -risk.capital_usdt*risk.daily_loss_limit:
            halted = True
        curve.append({"time": c.close_time, "wallet_balance": balance, "equity": equity,
                      "daily_pnl": equity-day_start, "daily_halted": halted})
        if i in signals_by_index:
            signal = signals_by_index[i]
            if position or pending:
                status, detail = "SKIPPED_BUSY", "One position or pending order at a time"
            elif halted:
                status, detail = "REJECTED", "Daily loss lock active"
            else:
                try:
                    plan, target = prepare_order(signal, risk, execution, config, balance, equity-day_start)
                except ValueError as error:
                    status, detail = "REJECTED", str(error)
                else:
                    pending = (signal, plan, target)
                    status, detail = "PENDING", ""
            orders.append({"time": c.close_time, "signal_time": signal.signal_time, "status": status, "detail": detail})
    if pending:
        orders.append({"time": candles[-1].close_time, "signal_time": pending[0].signal_time,
                       "status": "CANCELLED_END_OF_DATA"})
    net = balance-risk.capital_usdt
    if abs(sum((t["net_pnl"] for t in trades), D(0))-net) > D("1e-18"):
        raise ArithmeticError("Trade ledger and wallet do not reconcile")
    summary = {"initial_balance": risk.capital_usdt, "final_balance": balance, "net_pnl": net,
               "return_pct": net/risk.capital_usdt*100, "closed_trades": len(trades),
               "wins": sum(t["net_pnl"] > 0 for t in trades),
               "max_close_equity_drawdown_pct": max_drawdown*100,
               "order_statuses": dict(Counter(o["status"] for o in orders)),
               "rejection_reasons": dict(Counter(o["detail"] for o in orders if o["status"].startswith("REJECTED"))),
               "funding_payments": len(funding_log), "funding_net_paid": sum((e["payment"] for e in funding_log), D(0)),
               "warning": "Exploratory simulation. Constant assumed maintenance rate; isolated writeoff model. Not Binance liquidation replication. Current filters reused historically. No partial fills or order queue."}
    return {"summary": summary, "trades": trades, "orders": orders, "equity": curve, "funding": funding_log}


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=root/"config/backtest.json")
    parser.add_argument("--risk-config", type=Path, default=root/"config/paper.json")
    parser.add_argument("--strategy-config", type=Path, default=root/"config/smc.json")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output must be a new directory")
    candles, metadata = load_dataset(args.dataset)
    supplemental_path = args.dataset/"futures.json"
    extra = json.loads(supplemental_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256((args.dataset/"candles.csv").read_bytes()).hexdigest()
    if (extra["dataset_sha256"] != digest or any(extra[k] != metadata[k] for k in
            ("symbol", "interval", "start_time", "end_time_exclusive"))):
        raise ValueError("Futures supplement does not match dataset")
    marks = [Candle(int(x["open_time"]), *(D(str(x[k])) for k in ("open", "high", "low", "close", "volume")),
                    int(x["close_time"]), D(str(x["amount"]))) for x in extra["marks"]]
    risk, config = RiskConfig.load(args.risk_config), BacktestConfig.load(args.config)
    strategy = SMCConfig.load(args.strategy_config)
    signals = generate_signals(candles, strategy, step=INTERVALS[metadata["interval"]])
    result = run_backtest(candles, marks, extra["funding"], signals, risk, ExecutionRules.from_metadata(metadata), config)
    result["summary"].update({"risk_config": asdict(risk), "backtest_config": asdict(config),
                              "strategy_config": asdict(strategy), "dataset_metadata": metadata,
                              "signals": len(signals), "dataset_sha256": digest,
                              "supplement_sha256": hashlib.sha256(supplemental_path.read_bytes()).hexdigest()})
    args.output.mkdir(parents=True)
    for name in ("trades", "orders", "equity", "funding"):
        rows = result[name]
        fields = sorted({key for row in rows for key in row}) or ["no_records"]
        with (args.output/f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    (args.output/"summary.json").write_text(json.dumps(result["summary"], indent=2, default=str), encoding="utf-8")
    print(json.dumps({k:v for k,v in result["summary"].items() if k not in
                      ("risk_config", "backtest_config", "strategy_config", "dataset_metadata")}, indent=2, default=str))


if __name__ == "__main__":
    main()

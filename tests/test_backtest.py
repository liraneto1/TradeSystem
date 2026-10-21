from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
import unittest

from tradesystem.backtest import BacktestConfig, ExecutionRules, run_backtest
from tradesystem.market import Candle
from tradesystem.risk import RiskConfig, InstrumentRules
from tradesystem.smc import SMCSignal


def bar(i, o=102, h=104, l=99, c=102):
    return Candle(i*60000, *(D(str(x)) for x in (o,h,l,c)), D(1), (i+1)*60000-1, D(100))


def history(n=7):
    bars = [bar(i) for i in range(n)]
    bars[0] = bar(0, l=96)
    return bars


def signal(index=1):
    return SMCSignal("LONG", 0, index, (index+1)*60000-1, 0, 59999, D(98), D(103),
                     D(99), D(101), D(100), D(95), D(110),
                     (index+1)*60000, (index+5)*60000-1)


class BacktestTests(unittest.TestCase):
    def setUp(self):
        self.risk = RiskConfig.load(Path(__file__).resolve().parents[1]/"config/paper.json")
        self.rules = ExecutionRules(InstrumentRules(D(".001"), D(".001"), D(1)), D(".1"), D(1000), D(".1"), D(1000000))
        self.config = BacktestConfig()

    def test_invalid_margin_model_is_rejected(self):
        with self.assertRaises(ValueError):
            BacktestConfig(leverage=D(10), maintenance_margin_rate=D(".2"))

    def run_case(self, bars=None, signals=None, funding=None, risk=None, rules=None, config=None, marks=None):
        bars = history() if bars is None else bars
        return run_backtest(bars, bars if marks is None else marks, funding or [],
                            [signal()] if signals is None else signals,
                            risk or self.risk, rules or self.rules, config or self.config)

    def test_next_bar_entry_and_target_with_cost_reconciliation(self):
        bars = history()
        bars[3] = bar(3, h=111)
        r = self.run_case(bars)
        trade, = r["trades"]
        self.assertEqual(trade["entry_bar_open"], bars[2].open_time)
        self.assertEqual(trade["reason"], "TARGET")
        expected = trade["quantity"]*(D(10)-D(210)*D(".0007"))
        self.assertEqual(trade["net_pnl"], expected)
        self.assertEqual(r["summary"]["final_balance"], D(100)+expected)

    def test_no_fill_in_signal_bar(self):
        bars = [bar(i, o=103, h=105, l=101, c=104) for i in range(7)]
        bars[0] = bar(0, l=96)
        bars[1] = bar(1, l=99)
        r = self.run_case(bars)
        self.assertEqual(r["trades"], [])
        self.assertEqual(r["summary"]["order_statuses"]["EXPIRED"], 1)

    def test_same_bar_stop_wins_over_target(self):
        bars = history()
        bars[3] = bar(3, h=111, l=94)
        trade, = self.run_case(bars)["trades"]
        self.assertEqual((trade["reason"], trade["exit"]), ("STOP", D(95)))

    def test_no_target_on_entry_candle(self):
        bars = history(4)
        bars[2] = bar(2, h=111)
        trade, = self.run_case(bars)["trades"]
        self.assertEqual(trade["reason"], "END_OF_DATA")

    def test_gap_through_stop_uses_worse_open(self):
        bars = history()
        bars[3] = bar(3, o=90, h=92, l=89, c=91)
        trade, = self.run_case(bars)["trades"]
        self.assertEqual(trade["exit"], D(90))

    def test_invalidation_at_open_prevents_fill(self):
        bars = history()
        bars[2] = bar(2, o=95, h=102, l=94, c=101)
        r = self.run_case(bars)
        self.assertEqual(r["trades"], [])
        self.assertIn("INVALIDATED_AT_OPEN", r["summary"]["order_statuses"])

    def test_pending_expires_before_late_touch(self):
        bars = [bar(i, o=103,h=105,l=101,c=104) for i in range(7)]
        bars[0] = bar(0, l=96)
        bars[6] = bar(6)
        self.assertEqual(self.run_case(bars)["trades"], [])

    def test_minimum_does_not_force_bigger_quantity(self):
        rules = replace(self.rules, lot=replace(self.rules.lot, min_notional=D(50)))
        r = self.run_case(rules=rules)
        self.assertEqual(r["summary"]["closed_trades"], 0)
        self.assertEqual(r["summary"]["order_statuses"], {"REJECTED":1})
        self.assertEqual(r["summary"]["rejection_reasons"], {"Risk budget cannot satisfy instrument minimums":1})

    def test_one_pending_or_position(self):
        r = self.run_case(signals=[signal(), signal(2)])
        self.assertEqual(r["summary"]["order_statuses"]["SKIPPED_BUSY"], 1)
        self.assertEqual(r["summary"]["closed_trades"], 1)

    def test_funding_debit_credit_and_no_charge_before_entry(self):
        for rate in (D(".001"), D("-.001")):
            events = [{"time":120000, "rate":str(rate), "mark_price":"100"},
                      {"time":180000, "rate":str(rate), "mark_price":"100"}]
            r = self.run_case(funding=events)
            trade, = r["trades"]
            self.assertEqual(trade["funding_paid"], trade["quantity"]*100*rate)
            self.assertEqual(r["summary"]["funding_payments"], 1)
            self.assertEqual(r["summary"]["net_pnl"], trade["net_pnl"])

    def test_funding_outside_history_is_not_silently_ignored(self):
        with self.assertRaises(ValueError):
            self.run_case(funding=[{"time":9999999, "rate":".001", "mark_price":"100"}])

    def test_intrabar_funding_debit_is_conservative(self):
        r = self.run_case(funding=[{"time":120001,"rate":".001","mark_price":"100"}])
        trade, = r["trades"]
        self.assertEqual(trade["funding_paid"], trade["quantity"]*D(".1"))

    def test_liquidation_uses_mark_not_trade_low(self):
        bars = history()
        marks = history()
        marks[3] = bar(3, o=102, h=104, l=45, c=60)
        r = self.run_case(bars, marks=marks)
        trade, = r["trades"]
        self.assertEqual(trade["reason"], "LIQUIDATION_MODEL")
        self.assertEqual(trade["net_pnl"], -trade["quantity"]*100/2-trade["entry_cost"])

    def test_daily_lock_after_gap_loss(self):
        bars = history()
        bars[3] = bar(3, o=80,h=82,l=79,c=81)
        risk = replace(self.risk, risk_per_trade=D(".03"))
        r = self.run_case(bars, signals=[signal(), signal(3)], risk=risk)
        self.assertTrue(r["equity"][3]["daily_halted"])
        self.assertEqual(r["orders"][-1]["detail"], "Daily loss lock active")

    def test_daily_lock_resets_at_utc_midnight(self):
        bars = history()
        bars[3] = bar(3, o=80,h=82,l=79,c=81)
        shift = 86400000-4*60000
        bars = [replace(c, open_time=c.open_time+shift, close_time=c.close_time+shift) for c in bars]
        signals = [replace(s, signal_time=s.signal_time+shift, active_from=s.active_from+shift,
                           expires_at=s.expires_at+shift) for s in (signal(),signal(4))]
        r = self.run_case(bars, signals=signals, risk=replace(self.risk, risk_per_trade=D(".03")))
        self.assertTrue(r["equity"][3]["daily_halted"])
        self.assertFalse(r["equity"][4]["daily_halted"])
        self.assertEqual(sum(o["status"] == "PENDING" for o in r["orders"]), 2)

    def test_ambiguous_intrabar_credit_is_not_awarded(self):
        bars = history()
        bars[3] = bar(3, h=111)
        r = self.run_case(bars, funding=[{"time":180001,"rate":"-.001","mark_price":"100"}])
        self.assertEqual(r["trades"][0]["funding_paid"], 0)
        self.assertTrue(r["funding"][0]["conservative_intrabar"])

    def test_tick_rounding_and_max_quantity(self):
        s = replace(signal(), limit_entry=D("100.09"), stop=D("94.99"), target=D("110.01"))
        r = self.run_case(signals=[s])
        trade, = r["trades"]
        self.assertEqual((trade["entry"], trade["stop"], trade["target"]), (D("100.0"),D("94.9"),D("110.1")))
        rules = replace(self.rules, max_quantity=D(".002"))
        r = self.run_case(rules=rules)
        self.assertEqual(r["summary"]["closed_trades"], 0)
        self.assertIn("exceeds exchange maximum", r["orders"][0]["detail"])

    def test_short_target_and_funding_sign(self):
        bars = history()
        bars[4] = bar(4, h=111)
        bars = [replace(c, open=300-c.open, high=300-c.low, low=300-c.high, close=300-c.close) for c in bars]
        s = signal()
        s = replace(s, side="SHORT", gap_low=D(199), gap_high=D(201), limit_entry=D(200),
                    stop=D(205), target=D(190))
        r = self.run_case(bars, signals=[s], funding=[{"time":180000,"rate":".001","mark_price":"200"}])
        trade, = r["trades"]
        self.assertEqual(trade["reason"], "TARGET")
        self.assertLess(trade["funding_paid"], 0)

    def test_rejects_signal_with_future_activation_error(self):
        with self.assertRaises(ValueError):
            self.run_case(signals=[replace(signal(), active_from=1)])

    def test_rejects_misaligned_marks(self):
        marks = history()
        marks[3] = replace(marks[3], open_time=0)
        with self.assertRaises(ValueError):
            self.run_case(marks=marks)

import unittest
from decimal import Decimal as D
from pathlib import Path
from tradesystem.risk import RiskConfig, InstrumentRules, size_order
from tradesystem.paper import PaperBroker


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.config = RiskConfig.load(Path(__file__).resolve().parents[1] / "config/paper.json")
        self.rules = InstrumentRules(D("0.001"), D("0.001"), D("5"))
        self.args = dict(side="LONG", entry=D("100"), stop=D("99"), leverage=D("2"),
                         equity=D("100"), available_margin=D("100"), daily_pnl=D("0"))

    def plan(self, **kwargs):
        return size_order(self.config, self.rules, **(self.args | kwargs))

    def test_risk_and_margin_caps(self):
        plan = self.plan()
        self.assertLessEqual(plan.estimated_stop_loss, D("0.5"))
        self.assertLessEqual(plan.quantity * plan.entry / plan.leverage, D("20"))
        self.assertEqual(plan.quantity % self.rules.step_size, 0)

    def test_remaining_daily_budget(self):
        self.assertLessEqual(self.plan(daily_pnl=D("-1.9")).estimated_stop_loss, D("0.1"))

    def test_rejects_invalid_or_blocked_orders(self):
        for change in (dict(leverage=D("11")), dict(stop=D("101")),
                       dict(daily_pnl=D("-2")), dict(has_position=True),
                       dict(entry=D("NaN")), dict(available_margin=D("0")),
                       dict(side="BUY")):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.plan(**change)

    def test_exchange_minimum_does_not_increase_risk(self):
        with self.assertRaises(ValueError):
            size_order(self.config, InstrumentRules(D("1"), D("1"), D("100")), **self.args)

    def test_long_and_short_stop_accounting(self):
        for side, stop in (("LONG", "99"), ("SHORT", "101")):
            with self.subTest(side=side):
                plan = self.plan(side=side, stop=D(stop))
                broker = PaperBroker(self.config)
                broker.open(plan)
                with self.assertRaises(ValueError):
                    broker.open(plan)
                pnl = broker.close(plan.stop)
                self.assertEqual(pnl, -plan.estimated_stop_loss)
                self.assertEqual(broker.balance, self.config.capital_usdt + pnl)

    def test_live_mode_rejected(self):
        from unittest.mock import patch
        with patch.object(Path, "read_text", return_value='{"mode":"live"}'):
            with self.assertRaises(ValueError):
                RiskConfig.load("unused.json")


if __name__ == "__main__":
    unittest.main()

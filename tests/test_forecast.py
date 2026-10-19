import unittest
from decimal import Decimal as D
from tradesystem.market import Candle
from tradesystem.forecast import evaluate
from tradesystem.kronos_setup import verify_source
from unittest.mock import patch
from pathlib import Path


def candles(n):
    return [Candle(i * 60000, D(100+i), D(102+i), D(99+i), D(101+i), D(1),
                   (i+1)*60000-1, D(100)) for i in range(n)]


class ForecastTests(unittest.TestCase):
    def test_rejects_changed_upstream_source(self):
        for outputs in (["different\n", ""], ["expected\n", " M model/kronos.py"]):
            with patch("tradesystem.kronos_setup.subprocess.check_output", side_effect=outputs):
                with self.assertRaises(ValueError):
                    verify_source(Path("unused"), "expected")

    def test_evaluation_never_passes_future_prices_to_predictor(self):
        observed = []
        class Spy:
            def predict(self, history, horizon, step):
                observed.append([c.open_time for c in history])
                return [float(history[-1].close)] * horizon
        rows, metrics = evaluate(candles(12), Spy(), step=60000, lookback=4, horizon=2, windows=3)
        self.assertEqual(observed, [[i*60000 for i in range(j-4,j)] for j in (6,8,10)])
        self.assertEqual(len({r['target_time'] for r in rows}), 6)
        self.assertTrue(all(r['origin_time'] < r['target_time'] for r in rows))
        self.assertEqual(metrics['model_mae_usdt'], 1.5)
        self.assertFalse(metrics['model_beats_baseline'])

    def test_rejects_insufficient_history_before_inference(self):
        with self.assertRaises(ValueError):
            evaluate(candles(4), None, step=60000, lookback=4, horizon=1, windows=1)

    def test_rejects_invalid_forecast(self):
        class Bad:
            def predict(self, history, horizon, step):
                return [float('nan')]
        with self.assertRaises(ValueError):
            evaluate(candles(5), Bad(), step=60000, lookback=4, horizon=1, windows=1)

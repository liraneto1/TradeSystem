import unittest
from dataclasses import replace
from decimal import Decimal as D
from tradesystem.market import Candle
from tradesystem.smc import SMCConfig, confirmed_pivot, generate_signals, previous_atr


def history():
    # At 3 a high pivot is known; at 6 a low pivot is known. Sweep at 7,
    # bullish displacement at 8, FVG + structure break confirmed at 9.
    values = [(100,102,98,101), (101,104,99,102), (102,103,98,100),
              (100,102,97,99), (99,101,95,98), (98,102,97,100),
              (100,103,98,101), (101,102,94,99), (99,110,98,109),
              (109,112,105,111)]
    return [Candle(i*60000, *(D(x) for x in row), D(1), (i+1)*60000-1, D(100))
            for i, row in enumerate(values)]


class SMCTests(unittest.TestCase):
    def setUp(self):
        self.config = SMCConfig(pivot_left=1, pivot_right=2, atr_period=3)

    def signals(self, bars=None, config=None):
        return generate_signals(history() if bars is None else bars, config or self.config, step=60000)

    def test_pivot_is_known_only_after_right_bars(self):
        bars = history()
        self.assertIsNone(confirmed_pivot(bars, 2, 1, 2, "HIGH"))
        self.assertEqual(confirmed_pivot(bars, 3, 1, 2, "HIGH").index, 1)

    def test_long_setup_and_activation_after_confirmation(self):
        signal, = self.signals()
        self.assertEqual((signal.side, signal.sweep_index, signal.signal_index), ("LONG", 7, 9))
        self.assertEqual((signal.gap_low, signal.gap_high, signal.limit_entry), (D(102), D(105), D("103.5")))
        self.assertLess(signal.liquidity_known_time, history()[7].open_time)
        self.assertLess(signal.stop, D(94))
        self.assertAlmostEqual(signal.target-signal.limit_entry, 2*(signal.limit_entry-signal.stop), delta=D("1e-20"))
        self.assertEqual(signal.active_from, 600000)
        self.assertEqual(signal.expires_at, 839999)

    def test_short_is_symmetric(self):
        bars = [replace(c, open=D(300)-c.open, high=D(300)-c.low, low=D(300)-c.high,
                        close=D(300)-c.close) for c in history()]
        short, = self.signals(bars)
        long, = self.signals()
        self.assertEqual(short.side, "SHORT")
        self.assertEqual(short.limit_entry, D(300)-long.limit_entry)
        self.assertEqual(short.stop, D(300)-long.stop)
        self.assertAlmostEqual(short.target, D(300)-long.target, delta=D("1e-20"))

    def test_prefix_invariance_no_future_repainting(self):
        bars = history()
        bars += [replace(bars[-1], open_time=i*60000, close_time=(i+1)*60000-1) for i in range(10,18)]
        full = self.signals(bars)
        for n in range(1, len(bars)+1):
            self.assertEqual(self.signals(bars[:n]), [s for s in full if s.signal_index < n])

    def test_rejects_without_sweep_reclaim(self):
        bars = history()
        bars[7] = replace(bars[7], close=D(94))
        self.assertEqual(self.signals(bars), [])

    def test_rejects_without_structure_break(self):
        bars = history()
        bars[1] = replace(bars[1], high=D(115))
        self.assertEqual(self.signals(bars), [])

    def test_rejects_without_gap(self):
        bars = history()
        bars[9] = replace(bars[9], low=D(101))
        self.assertEqual(self.signals(bars), [])

    def test_rejects_without_displacement(self):
        self.assertEqual(self.signals(config=replace(self.config, displacement_atr=D(100))), [])

    def test_invalidation_by_new_extreme(self):
        bars = history()
        bars[8] = replace(bars[8], low=D(93))
        self.assertEqual(self.signals(bars), [])

    def test_expiry(self):
        bars = history()
        # Delay the displacement and confirmation until after the 2-bar window.
        quiet = replace(bars[7], low=D(97), high=D(102), open=D(100), close=D(101))
        bars.insert(8, quiet)
        bars = [replace(c, open_time=i*60000, close_time=(i+1)*60000-1) for i,c in enumerate(bars)]
        self.assertEqual(self.signals(bars, replace(self.config, confirmation_bars=2)), [])

    def test_outside_bar_both_sides_is_ignored(self):
        bars = history()
        bars[7] = replace(bars[7], high=D(105))
        self.assertEqual(self.signals(bars), [])

    def test_atr_excludes_current_bar(self):
        bars = history()
        before = previous_atr(bars, 7, 3)
        bars[7] = replace(bars[7], high=D(9999))
        self.assertEqual(previous_atr(bars, 7, 3), before)

    def test_invalid_input_and_config(self):
        for change in ({"pivot_right":0}, {"reward_risk":D("NaN")}, {"confirmation_bars":1}):
            with self.assertRaises(ValueError):
                SMCConfig(**change)
        bars = history()
        bars[5] = replace(bars[5], open_time=0)
        with self.assertRaises(ValueError):
            self.signals(bars)

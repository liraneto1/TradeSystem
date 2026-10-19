import unittest
from decimal import Decimal as D
from unittest.mock import patch

from tradesystem.market import PublicClient, instrument_rules, parse_candles, save_dataset


def row(t):
    return [t, "100", "102", "99", "101", "10", t + 59999, "1000", 5, "1", "100", "0"]


def info():
    return {"symbols": [{"symbol": "BTCUSDT", "status": "TRADING", "contractType": "PERPETUAL",
                         "quoteAsset": "USDT", "filters": [
                             {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                             {"filterType": "MIN_NOTIONAL", "notional": "100"}]}]}


class MarketTests(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(len(parse_candles([row(0), row(60000)], "1m", 120000)), 2)
        for rows in ([row(0), row(0)], [row(60000), row(0)], [row(0), row(120000)],
                     [row(180000)], [[0, "NaN", "102", "99", "101", "1", 59999, "1"]],
                     [[0, "100", "98", "99", "101", "1", 59999, "1"]]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                parse_candles(rows, "1m", 180000)

    def test_filters_from_exchange_not_precision(self):
        rules = instrument_rules(info(), "BTCUSDT")
        self.assertEqual(rules.step_size, D("0.001"))
        self.assertEqual(rules.min_notional, D("100"))
        snapshot = info()
        snapshot["symbols"][0]["status"] = "BREAK"
        with self.assertRaises(ValueError):
            instrument_rules(snapshot, "BTCUSDT")

    def test_pagination_uses_server_clock_and_excludes_open_candle(self):
        calls = []
        def get(path, **params):
            calls.append((path, params))
            if path.endswith("time"):
                return {"serverTime": 500 * 60000 + 1234}
            if path.endswith("exchangeInfo"):
                return info()
            return [row(t) for t in range(params["startTime"],
                                         params["startTime"] + params["limit"] * 60000, 60000)]
        client = PublicClient()
        with patch.object(client, "get", side_effect=get):
            candles, metadata = client.collect(interval="1m", count=500)
        self.assertEqual(len(candles), 500)
        self.assertEqual(candles[-1].close_time, 500 * 60000 - 1)
        self.assertEqual([x[1]["limit"] for x in calls if x[0].endswith("klines")], [499, 1])
        self.assertEqual(metadata["count"], 500)

    def test_missing_page_fails(self):
        client = PublicClient()
        with patch.object(client, "get", side_effect=[{"serverTime": 120000}, info(), []]):
            with self.assertRaises(ValueError):
                client.collect(interval="1m", count=2)

    def test_write_dataset_and_refuse_overwrite(self):
        import tempfile
        from pathlib import Path
        root = Path(__file__).resolve().parents[1] / "data"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            target = Path(folder) / "snapshot"
            candles = parse_candles([row(0)], "1m", 60000)
            save_dataset(candles, {"source": "test"}, target)
            self.assertIn("1000", (target / "candles.csv").read_text())
            self.assertIn("test", (target / "metadata.json").read_text())
            with self.assertRaises(FileExistsError):
                save_dataset(candles, {}, target)

    def test_input_guard_before_network(self):
        client = PublicClient()
        with patch.object(client, "get") as get:
            for args in ({"symbol": "../../bad"}, {"count": 0}, {"interval": "1M"}):
                with self.assertRaises(ValueError):
                    client.collect(**args)
            get.assert_not_called()

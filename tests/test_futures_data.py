import unittest
from unittest.mock import Mock
from tradesystem.futures_data import collect_supplement


def row(t):
    return [t, "100", "102", "99", "101", "0", t+59999, "0"]


class FuturesDataTests(unittest.TestCase):
    def setUp(self):
        self.metadata = {"start_time":0, "end_time_exclusive":120000, "interval":"1m", "symbol":"BTCUSDT"}

    def test_collects_marks_and_funding_without_fixed_schedule(self):
        client = Mock(BASE_URL="https://fapi.binance.com")
        client.get.side_effect = [[row(0), row(60000)],
                                 [{"symbol":"BTCUSDT","fundingTime":60001,"fundingRate":".001","markPrice":"100"}], []]
        data = collect_supplement(client, self.metadata)
        self.assertEqual(len(data["marks"]), 2)
        self.assertEqual(data["funding"][0]["time"], 60001)

    def test_missing_mark_history_is_rejected(self):
        client = Mock()
        client.get.return_value = []
        with self.assertRaises(ValueError):
            collect_supplement(client, self.metadata)

    def test_duplicate_funding_is_rejected(self):
        client = Mock()
        event = {"symbol":"BTCUSDT","fundingTime":60000,"fundingRate":".001","markPrice":"100"}
        client.get.side_effect = [[row(0),row(60000)], [event,event]]
        with self.assertRaises(ValueError):
            collect_supplement(client, self.metadata)

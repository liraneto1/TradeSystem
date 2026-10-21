"""Public USD-M market data only. No authenticated endpoints or trading."""

import argparse
import csv
from dataclasses import asdict, dataclass
from decimal import Decimal as D
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import urlopen

from .risk import InstrumentRules

INTERVALS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}


@dataclass(frozen=True)
class Candle:
    open_time: int
    open: D
    high: D
    low: D
    close: D
    volume: D
    close_time: int
    amount: D


def parse_candles(rows, interval: str, cutoff: int) -> list[Candle]:
    step = INTERVALS[interval]
    result = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 8:
            raise ValueError("Invalid kline schema")
        candle = Candle(int(row[0]), *(D(str(x)) for x in row[1:6]), int(row[6]), D(str(row[7])))
        prices = (candle.open, candle.high, candle.low, candle.close)
        if (any(not x.is_finite() or x <= 0 for x in prices) or
                any(not x.is_finite() or x < 0 for x in (candle.volume, candle.amount)) or
                candle.high < max(candle.open, candle.close, candle.low) or
                candle.low > min(candle.open, candle.close) or
                candle.open_time < 0 or candle.open_time % step or
                candle.close_time != candle.open_time + step - 1):
            raise ValueError("Invalid candle values or timestamps")
        if result and candle.open_time != result[-1].open_time + step:
            raise ValueError("Duplicate, unordered or missing candles")
        if candle.close_time >= cutoff:
            raise ValueError("Unclosed candle in historical response")
        result.append(candle)
    return result


def instrument_rules(info, symbol: str) -> InstrumentRules:
    matches = [x for x in info["symbols"] if x["symbol"] == symbol]
    if len(matches) != 1:
        raise ValueError("Symbol not found")
    item = matches[0]
    if item["status"] != "TRADING" or item["contractType"] != "PERPETUAL" or item["quoteAsset"] != "USDT":
        raise ValueError("Only trading USDT perpetual contracts are supported")
    filters = {x["filterType"]: x for x in item["filters"]}
    lot = filters["LOT_SIZE"]
    return InstrumentRules(D(lot["stepSize"]), D(lot["minQty"]), D(filters["MIN_NOTIONAL"]["notional"]))


class PublicClient:
    BASE_URL = "https://fapi.binance.com"

    def get(self, path, **params):
        if path not in ("/fapi/v1/time", "/fapi/v1/exchangeInfo", "/fapi/v1/klines",
                        "/fapi/v1/markPriceKlines", "/fapi/v1/fundingRate"):
            raise ValueError("Endpoint not allowed")
        url = self.BASE_URL + path + ("?" + urlencode(params) if params else "")
        # No automatic retries: fail on throttling or regional restrictions.
        with urlopen(url, timeout=20) as response:
            return json.load(response)

    def collect(self, symbol="BTCUSDT", interval="15m", count=400):
        if not re.fullmatch(r"[A-Z0-9]{5,24}", symbol):
            raise ValueError("Invalid symbol")
        if interval not in INTERVALS or not 1 <= count <= 10_000:
            raise ValueError("Unsupported interval or count (1..10000)")
        server_time = int(self.get("/fapi/v1/time")["serverTime"])
        step = INTERVALS[interval]
        end = server_time // step * step
        start = end - count * step
        info = self.get("/fapi/v1/exchangeInfo")
        rules = instrument_rules(info, symbol)
        candles = []
        cursor = start
        while cursor < end:
            page_count = min(499, (end - cursor) // step)
            rows = self.get("/fapi/v1/klines", symbol=symbol, interval=interval,
                            startTime=cursor, endTime=end - 1, limit=page_count)
            page = parse_candles(rows, interval, end)
            if not page or page[0].open_time != cursor or len(page) > page_count or page[-1].open_time >= end:
                raise ValueError("Incomplete or out-of-range market data")
            candles.extend(page)
            cursor = page[-1].open_time + step
        if len(candles) != count:
            raise ValueError("Unexpected history length")
        metadata = {"source": self.BASE_URL, "symbol": symbol, "interval": interval,
                    "server_time": server_time, "start_time": start, "end_time_exclusive": end,
                    "count": count, "rules": {k: str(v) for k, v in asdict(rules).items()},
                    "symbol_snapshot": next(x for x in info["symbols"] if x["symbol"] == symbol)}
        return candles, metadata


def save_dataset(candles, metadata, output: Path):
    # A fresh directory avoids mixing snapshots from different collections.
    output.mkdir(parents=True, exist_ok=False)
    with (output / "candles.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(Candle.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(x) for x in candles)
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Collect closed Binance USD-M candles; read-only")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", choices=INTERVALS, default="15m")
    parser.add_argument("--count", type=int, default=400)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        candles, metadata = PublicClient().collect(args.symbol, args.interval, args.count)
        save_dataset(candles, metadata, args.output)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(1, f"Collection failed: {error}\n")
    print(f"Saved {len(candles)} closed candles to {args.output.resolve()}")
    print(f"Current LOT_SIZE / MIN_NOTIONAL: {metadata['rules']}")


if __name__ == "__main__":
    main()

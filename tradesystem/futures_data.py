"""Read-only historical mark and funding supplement for a collected dataset."""

import argparse
from dataclasses import asdict
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path

from .forecast import load_dataset
from .market import PublicClient, INTERVALS, parse_candles


def collect_supplement(client, metadata):
    start, end = metadata["start_time"], metadata["end_time_exclusive"]
    step, symbol = INTERVALS[metadata["interval"]], metadata["symbol"]
    marks, cursor = [], start
    while cursor < end:
        limit = min(499, (end-cursor)//step)
        rows = client.get("/fapi/v1/markPriceKlines", symbol=symbol, interval=metadata["interval"],
                          startTime=cursor, endTime=end-1, limit=limit)
        page = parse_candles(rows, metadata["interval"], end)
        if not page or page[0].open_time != cursor or len(page) > limit or page[-1].close_time >= end:
            raise ValueError("Incomplete mark-price history")
        marks.extend(asdict(c) for c in page)
        cursor = page[-1].close_time+1
    funding, cursor = [], start
    while cursor < end:
        page = client.get("/fapi/v1/fundingRate", symbol=symbol, startTime=cursor, endTime=end-1, limit=1000)
        if not page:
            break
        for event in page:
            time = int(event["fundingTime"])
            rate, price = D(str(event["fundingRate"])), D(str(event["markPrice"]))
            if (event["symbol"] != symbol or not cursor <= time < end or
                    (funding and time <= funding[-1]["time"]) or
                    not rate.is_finite() or not price.is_finite() or price <= 0):
                raise ValueError("Invalid funding history")
            funding.append({"time": time, "rate": str(rate), "mark_price": str(price)})
        cursor = funding[-1]["time"]+1
    return {"source": client.BASE_URL, "symbol": symbol, "interval": metadata["interval"],
            "start_time": start, "end_time_exclusive": end, "marks": marks, "funding": funding}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    args = parser.parse_args()
    _, metadata = load_dataset(args.dataset)
    output = args.dataset/"futures.json"
    if output.exists():
        parser.error("futures.json already exists; use a fresh dataset")
    supplement = collect_supplement(PublicClient(), metadata)
    supplement["dataset_sha256"] = hashlib.sha256((args.dataset/"candles.csv").read_bytes()).hexdigest()
    with output.open("x", encoding="utf-8") as stream:
        json.dump(supplement, stream, indent=2, default=str)
    print(f"Saved {len(supplement['marks'])} mark candles and {len(supplement['funding'])} funding events")


if __name__ == "__main__":
    main()

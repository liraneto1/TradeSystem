"""Offline smoke demo with synthetic prices and illustrative filters."""

from decimal import Decimal as D
from pathlib import Path
from .risk import RiskConfig, InstrumentRules, size_order
from .paper import PaperBroker


def main():
    config = RiskConfig.load(Path(__file__).resolve().parent.parent / "config" / "paper.json")
    broker = PaperBroker(config)
    plan = size_order(config, InstrumentRules(D("0.001"), D("0.001"), D("5")),
                      side="LONG", entry=D("100"), stop=D("99"), leverage=D("2"),
                      equity=broker.balance, available_margin=broker.balance, daily_pnl=D("0"))
    broker.open(plan)
    pnl = broker.close(plan.stop)
    print("PAPER DEMO — synthetic prices; no Binance connection")
    print(f"Quantity: {plan.quantity}; leverage: {plan.leverage}x")
    print(f"Net PnL: {pnl:.4f} USDT; balance: {broker.balance:.4f} USDT")


if __name__ == "__main__":
    main()

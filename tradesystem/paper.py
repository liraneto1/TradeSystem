"""Single-position simulation. Prices supplied by caller, no live orders."""

from decimal import Decimal
from .risk import OrderPlan, RiskConfig, positive


class PaperBroker:
    def __init__(self, config: RiskConfig):
        self.config = config
        self.balance = config.capital_usdt
        self.position: OrderPlan | None = None

    def open(self, plan: OrderPlan):
        if self.position is not None:
            raise ValueError("Position already open")
        # Intended for plans produced by the risk engine; not a live execution boundary.
        if (plan.side not in ("LONG", "SHORT") or
                not all(positive(x) for x in (plan.quantity, plan.entry, plan.stop, plan.leverage)) or
                not Decimal(1) <= plan.leverage <= self.config.max_leverage):
            raise ValueError("Invalid plan")
        cost = plan.quantity * plan.entry * (self.config.fee_rate_per_side + self.config.slippage_rate_per_side)
        if plan.quantity * plan.entry / plan.leverage + cost > self.balance:
            raise ValueError("Insufficient simulated margin")
        self.balance -= cost
        self.position = plan

    def close(self, price: Decimal) -> Decimal:
        if self.position is None or not positive(price):
            raise ValueError("Position and positive exit price required")
        plan = self.position
        direction = Decimal(1) if plan.side == "LONG" else Decimal(-1)
        gross = direction * (price - plan.entry) * plan.quantity
        rate = self.config.fee_rate_per_side + self.config.slippage_rate_per_side
        self.balance += gross - plan.quantity * price * rate
        self.position = None
        return gross - plan.quantity * (plan.entry + price) * rate

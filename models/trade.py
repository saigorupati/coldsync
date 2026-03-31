from typing import TypedDict


class Trade(TypedDict, total=False):
    ticker: str
    type: str              # "no_buy_tier_A", "exit_10pct", "exit_20pct", "exit_30pct"
    side: str              # "no"
    action: str            # "buy" or "sell"
    intended_price: float
    fill_price: float
    count: int             # number of contracts
    cost_usd: float
    status: str
    question: str
    close_time: str
    city_date: str
    order_id: str

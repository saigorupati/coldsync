from typing import TypedDict


class MarketBin(TypedDict, total=False):
    ticker: str
    event_ticker: str
    question: str
    yes_price: float       # midpoint for probability scoring
    no_price: float        # 1 - yes_price
    no_ask: float          # actual price to buy NO (for execution)
    spread: float
    depth_2c_usd: float
    close_time: str
    volume: float
    city_date: str
    temp_low: float
    temp_high: float
    is_open_low: bool
    is_open_high: bool

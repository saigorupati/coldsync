from typing import TypedDict
from datetime import datetime


class Position(TypedDict, total=False):
    ticker: str
    event_ticker: str
    question: str
    no_contracts: int
    no_cost: float
    entry_price_no: float    # average entry price per NO contract
    exit_stage: int          # 0=none, 1=cut_some, 2=cut_heavy, 3=full_exit
    city_date: str
    close_time: str
    resolved: bool
    resolved_outcome: str
    payout: float
    pnl: float
    created_at: datetime
    resolved_at: datetime

from typing import TypedDict
from datetime import datetime


class RiskState(TypedDict, total=False):
    id: int
    phase: int
    scale_factor: float
    scale_expires: datetime
    paused_until: datetime
    starting_balance: float
    started_at: datetime

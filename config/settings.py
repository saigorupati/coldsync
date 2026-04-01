from dataclasses import dataclass, field
from enum import IntEnum


class Phase(IntEnum):
    LEARNING = 1   # first 2 weeks
    STANDARD = 2   # after 14 days, >90% No win rate
    SCALED = 3     # after 30+ days, P&L > 10% of starting


@dataclass
class StrategyConfig:
    # --- Phase-dependent parameters ---
    phase: Phase = Phase.LEARNING

    @property
    def safety_buffer_pct(self) -> float:
        return {Phase.LEARNING: 0.25, Phase.STANDARD: 0.20, Phase.SCALED: 0.15}[self.phase]

    @property
    def max_unresolved_pct(self) -> float:
        return {Phase.LEARNING: 0.50, Phase.STANDARD: 0.65, Phase.SCALED: 0.75}[self.phase]

    # --- Fixed sizing (% of wallet_balance) ---
    max_per_market_pct: float = 0.02
    max_per_market_tier_a_pct: float = 0.03
    max_per_city_date_pct: float = 0.10

    # --- Tier sizes (% of wallet_balance) ---
    tier_a_pct: float = 0.025
    tier_b_pct: float = 0.015
    tier_c_pct: float = 0.0075
    tier_d_pct: float = 0.01

    # --- No price filters ---
    no_price_min: float = 0.90
    no_price_max: float = 0.98       # Cap at 98c — 99c leaves no margin after fees
    no_price_sweet_min: float = 0.90
    no_price_sweet_max: float = 0.96  # Kalshi: sweet spot slightly wider

    # --- Distortion thresholds ---
    prob_sum_min_excess: float = 0.005  # Kalshi: smaller ladders (6 bins) → lower natural excess
    prob_sum_strong_excess: float = 0.02
    prob_sum_extreme_excess: float = 0.06
    neighbor_spread_ratio: float = 1.3
    neighbor_spread_extreme: float = 2.0
    center_of_mass_std_threshold: float = 1.5

    # --- Timing ---
    max_hours_before_resolution: int = 30   # Kalshi: markets close ~midnight ET, morning scans see 25-30h
    extended_hours_tier_d: int = 72
    scan_interval_seconds: int = 60

    # --- Liquidity thresholds ---
    max_spread: float = 0.08          # Kalshi: thinner books than Polymarket
    preferred_spread: float = 0.05
    min_depth_multiplier_tier_a: float = 2.0
    min_depth_multiplier_other: float = 1.0
    max_book_take_pct: float = 0.50
    max_slippage: float = 0.02
    min_market_volume: float = 200.0  # Kalshi: lower overall volume than Polymarket
    min_order_size: float = 5.0

    # --- Exit / Scale-out parameters (replaces hedge) ---
    exit_down_10_cut_pct: float = 0.33       # sell 33% at -20% (stage 1)
    exit_down_20_cut_pct: float = 0.66       # sell 66% of remaining at -30% (stage 2)
    exit_down_30_full_exit: bool = True       # fully exit at -40% (stage 3)
    exit_check_interval_seconds: float = 5.0  # polling fallback when WS down

    # --- Stage 4: YES Flip (reversal after full NO exit) ---
    yes_flip_enabled: bool = True            # enable YES flip after full NO exit
    yes_flip_trigger_loss_pct: float = 0.50  # trigger when NO dropped 50%+ from entry
    yes_flip_loss_fraction: float = 0.50     # spend up to 50% of realized NO loss
    yes_flip_max_usd: float = 10.00          # absolute cap on YES flip spend
    yes_flip_stop_loss_pct: float = 0.60     # sell YES if it drops 60% from entry
    yes_flip_max_yes_price: float = 0.40     # don't buy YES above 40c (no value)
    yes_flip_max_total_usd: float = 30.00    # global cap across all active YES flips

    # --- Risk controls ---
    loss_warning_count: int = 2
    loss_warning_size_reduction: float = 0.75
    loss_hard_pause_count: int = 3
    loss_hard_pause_wallet_pct: float = 0.03
    city_freeze_trigger: int = 2
    city_freeze_hours: int = 24
    bad_structure_pause_count: int = 3
    bad_structure_pause_hours: int = 12
    bad_structure_size_reduction: float = 0.50

    # --- Scaling triggers ---
    scale_up_streak: int = 5
    scale_up_factor: float = 1.10
    scale_down_daily_losses: int = 2
    scale_down_factor: float = 0.75
    scale_down_hours: int = 48

    # --- Phase advancement ---
    phase_1_min_days: int = 14
    phase_1_min_no_win_rate: float = 0.90
    phase_2_min_days: int = 30
    phase_2_min_pnl_pct: float = 0.10

    # --- City config ---
    whitelisted_cities: list = field(default_factory=lambda: [
        "NYC", "CHI", "MIA", "LA", "DEN",
        "ATL", "PHX", "HOU",
        # "AUS", "BOS", "DAL", "DC",
        # "LV", "MIN", "NOLA", "OKC",
        # "PHIL", "SATX", "SEA", "SFO",
    ])
    blocked_cities: list = field(default_factory=list)

    # --- Kalshi-specific ---
    kalshi_env: str = "demo"
    ws_reconnect_delay_seconds: float = 5.0

    # --- Dry run mode ---
    dry_run: bool = False

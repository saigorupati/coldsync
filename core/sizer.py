class PositionSizer:
    def __init__(self, config):
        self.config = config

    def calculate(self, tier, wallet_balance: float, free_cash: float,
                  market_exposure: float, city_date_exposure: float,
                  total_unresolved: float, depth_2c: float,
                  scale_factor: float = 1.0,
                  limit_order: bool = False) -> float:
        tier_pcts = {
            "A": self.config.tier_a_pct,
            "B": self.config.tier_b_pct,
            "C": self.config.tier_c_pct,
            "D": self.config.tier_d_pct,
        }
        base_pct = tier_pcts.get(tier.value, 0)
        if base_pct == 0:
            return 0.0

        tier_size = wallet_balance * base_pct * scale_factor

        market_cap_pct = (self.config.max_per_market_tier_a_pct
                          if tier.value == "A"
                          else self.config.max_per_market_pct)
        market_cap_remaining = wallet_balance * market_cap_pct - market_exposure

        city_cap_remaining = wallet_balance * self.config.max_per_city_date_pct - city_date_exposure

        unresolved_cap_remaining = wallet_balance * self.config.max_unresolved_pct - total_unresolved

        liquidity_cap = depth_2c * self.config.max_book_take_pct if not limit_order else float('inf')

        safety = wallet_balance * self.config.safety_buffer_pct
        free_cash_cap = free_cash - safety

        order_size = min(
            tier_size,
            market_cap_remaining,
            city_cap_remaining,
            unresolved_cap_remaining,
            liquidity_cap,
            free_cash_cap,
        )

        if order_size < self.config.min_order_size:
            return 0.0

        return max(order_size, 0.0)

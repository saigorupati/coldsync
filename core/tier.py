from datetime import datetime, timezone
from enum import Enum


class Tier(Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    SKIP = "SKIP"


class TierClassifier:
    def __init__(self, config):
        self.config = config

    def classify(self, scored_bin: dict, ladder_result: dict, city_date_exposure: float,
                 wallet_balance: float) -> tuple:
        m = scored_bin["market"]
        score = scored_bin["score"]
        excess = ladder_result["excess"]
        no_price = m["no_price"]
        spread = m["spread"]
        depth = m["depth_2c_usd"]
        volume = m["volume"]

        raw_close = m.get("close_time", "")
        if not raw_close:
            return Tier.SKIP, "no_close_time"
        close_time = datetime.fromisoformat(raw_close.replace("Z", "+00:00"))
        hours_left = (close_time - datetime.now(timezone.utc)).total_seconds() / 3600

        if no_price < 0.85:
            return Tier.SKIP, f"no_price {no_price:.2f} < 0.85"
        if spread > self.config.max_spread:
            return Tier.SKIP, f"spread {spread:.3f} > {self.config.max_spread}"
        if volume < self.config.min_market_volume:
            return Tier.SKIP, f"volume {volume:.0f} < {self.config.min_market_volume}"
        if excess < self.config.prob_sum_min_excess:
            return Tier.SKIP, f"excess {excess:.3f} < {self.config.prob_sum_min_excess}"
        if score < 1.0:
            return Tier.SKIP, f"score {score:.1f} < 1.0"
        if wallet_balance > 0 and city_date_exposure >= wallet_balance * self.config.max_per_city_date_pct:
            return Tier.SKIP, "city_date_exposure"

        if hours_left > self.config.max_hours_before_resolution:
            if hours_left <= self.config.extended_hours_tier_d:
                if no_price >= self.config.no_price_min and score >= 3.0:
                    return Tier.D, ""
            return Tier.SKIP, f"hours_left {hours_left:.0f} > {self.config.max_hours_before_resolution}"

        if (self.config.no_price_min <= no_price <= self.config.no_price_max
                and hours_left <= 12
                and score >= 3.0
                and spread <= self.config.preferred_spread
                and (wallet_balance == 0 or depth >= self.config.min_depth_multiplier_tier_a * (wallet_balance * self.config.tier_a_pct))):
            return Tier.A, ""

        if (self.config.no_price_min <= no_price <= self.config.no_price_max
                and hours_left <= self.config.max_hours_before_resolution
                and score >= 2.0
                and spread <= self.config.max_spread):
            return Tier.B, ""

        if (0.85 <= no_price < self.config.no_price_min
                and score >= 1.0):
            return Tier.C, ""

        if self.config.no_price_min <= no_price <= self.config.no_price_max and score >= 1.0:
            return Tier.C, ""

        return Tier.SKIP, f"no_tier_match no={no_price:.2f} hrs={hours_left:.0f} sc={score:.1f}"

import statistics


class DistortionScorer:
    def __init__(self, config):
        self.config = config

    def score_ladder(self, ladder: list[dict]) -> dict:
        if len(ladder) < 2:
            return {"prob_sum": 0, "excess": 0, "bins": []}

        yes_prices = [b["yes_price"] for b in ladder]
        prob_sum = sum(yes_prices)
        excess = prob_sum - 1.0

        total_weight = sum(yes_prices) or 1
        com = sum(i * p for i, p in enumerate(yes_prices)) / total_weight
        if len(yes_prices) > 2:
            variance = sum(p * (i - com) ** 2 for i, p in enumerate(yes_prices)) / total_weight
            std_dev = variance ** 0.5 if variance > 0 else 1.0
        else:
            std_dev = 1.0

        scored_bins = []
        for i, b in enumerate(ladder):
            neighbors = []
            if i > 0:
                neighbors.append(yes_prices[i - 1])
            if i < len(ladder) - 1:
                neighbors.append(yes_prices[i + 1])

            neighbor_avg = statistics.mean(neighbors) if neighbors else yes_prices[i]
            neighbor_ratio = yes_prices[i] / neighbor_avg if neighbor_avg > 0.001 else 0

            com_distance = abs(i - com) / std_dev if std_dev > 0 else 0

            score = 0.0
            no_price = b["no_price"]
            if no_price >= self.config.no_price_min:
                if neighbor_ratio >= self.config.neighbor_spread_ratio:
                    score += 2.0
                if neighbor_ratio >= self.config.neighbor_spread_extreme:
                    score += 1.0

                if com_distance >= self.config.center_of_mass_std_threshold:
                    score += 1.5
                if com_distance >= self.config.center_of_mass_std_threshold * 2:
                    score += 0.5

                if excess >= self.config.prob_sum_strong_excess:
                    score += 1.0
                if excess >= self.config.prob_sum_extreme_excess:
                    score += 1.0

                if no_price >= 0.95:
                    score += 1.5
                elif no_price >= 0.92:
                    score += 1.0
                elif no_price >= self.config.no_price_min:
                    score += 0.5

            scored_bins.append({
                "market": b,
                "neighbor_ratio": neighbor_ratio,
                "com_distance": com_distance,
                "score": score,
            })

        return {
            "prob_sum": prob_sum,
            "excess": excess,
            "bins": scored_bins,
        }

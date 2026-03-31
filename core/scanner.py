import asyncio
import logging
from datetime import datetime, timedelta, timezone

from config.cities import CityConfig, get_active_cities
from services.kalshi_rest import KalshiClient

logger = logging.getLogger("coldsync.scanner")


class LadderScanner:
    def __init__(self, config, kalshi: KalshiClient):
        self.config = config
        self.kalshi = kalshi

    async def scan(self) -> dict[str, list[dict]]:
        now = datetime.now(timezone.utc)
        dates = [(now + timedelta(days=d)).date() for d in range(0, 2)]
        active_cities = get_active_cities(self.config)

        ladders = {}

        # Scan one city at a time to stay under rate limits
        for city in active_cities:
            # Fetch all dates for this city sequentially
            for dt in dates:
                try:
                    result = await self._fetch_event_ladder(city, dt)
                    if result is not None:
                        city_date, bins = result
                        if bins:
                            ladders[city_date] = bins
                except Exception as e:
                    logger.warning("Scan error for %s on %s: %s", city.code, dt, e)

        return ladders

    async def _fetch_event_ladder(self, city: CityConfig, dt) -> tuple[str, list[dict]] | None:
        try:
            markets = await self.kalshi.get_city_markets(city.kalshi_series, dt)
        except Exception as e:
            logger.warning("Failed to fetch markets for %s on %s: %s", city.code, dt, e)
            return None

        if not markets:
            return None

        city_date = f"{city.code}|{dt.isoformat()}"
        logger.info("%s: %d markets found (vols: %s)", city_date, len(markets),
                    [f"{m.ticker}={m.volume}" for m in markets])

        # Fetch orderbooks sequentially (batch endpoint not available)
        bins = []
        for m in markets:
            try:
                ob = await self.kalshi.get_orderbook(m.ticker)
                enriched = self._enrich_market(m, ob)
                if enriched is not None:
                    bins.append(enriched)
            except Exception as e:
                logger.warning("Enrich exception in %s for %s: %s", city_date, m.ticker, e)
        if markets and not bins:
            logger.info("%s: %d markets found, 0 passed enrichment", city_date, len(markets))
        elif bins:
            logger.info("%s: %d/%d bins enriched", city_date, len(bins), len(markets))
        return city_date, bins

    def _enrich_market(self, market, ob) -> dict | None:
        if ob is None or not ob.yes_asks:
            logger.debug("No orderbook/asks for %s", market.ticker)
            return None

        yes_ask = ob.best_ask()
        yes_bid = ob.best_bid()
        if yes_ask is None:
            return None

        yes_mid = (yes_ask + (yes_bid or yes_ask)) / 2
        no_mid = 1.0 - yes_mid
        no_ask = 1.0 - (yes_bid or yes_ask)  # cost to buy NO

        if no_mid < 0.03:
            logger.debug("Skipping %s — no_mid %.3f too low", market.ticker, no_mid)
            return None

        spread = (yes_ask - yes_bid) if (yes_ask and yes_bid) else 0.10
        if spread > 0.10:
            spread = abs(no_ask - no_mid)

        # Depth within 2c of best NO ask
        depth_2c = sum(
            entry["price"] * entry["quantity"]
            for entry in ob.yes_bids  # YES bids = NO asks
            if entry["price"] >= (yes_bid or 0) - 0.02
        )

        return {
            "ticker": market.ticker,
            "event_ticker": market.event_ticker,
            "question": market.yes_sub_title,
            "yes_price": yes_mid,
            "no_price": no_mid,
            "no_ask": no_ask,
            "spread": spread,
            "depth_2c_usd": depth_2c,
            "close_time": market.close_time,
            "volume": market.volume,
            "city_date": "",  # set by caller
            "temp_low": market.temp_low,
            "temp_high": market.temp_high,
            "is_open_low": market.is_open_low,
            "is_open_high": market.is_open_high,
        }

    async def close(self):
        pass  # kalshi client managed externally

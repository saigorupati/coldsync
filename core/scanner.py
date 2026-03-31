import asyncio
import logging
from datetime import datetime, timedelta, timezone

from config.cities import CityConfig, get_active_cities
from services.kalshi_rest import KalshiClient, KalshiOrderbook

logger = logging.getLogger("coldsync.scanner")

# How long to cache discovered tickers before re-fetching from REST
DISCOVERY_CACHE_TTL_SECONDS = 300  # 5 minutes


class LadderScanner:
    def __init__(self, config, kalshi: KalshiClient, ws=None):
        self.config = config
        self.kalshi = kalshi
        self.ws = ws  # KalshiWebSocket — if set, prefer WS orderbook data

        # Cache: (city_code, date_str) -> (markets_list, timestamp)
        self._discovery_cache: dict[str, tuple[list, float]] = {}

    async def scan(self) -> dict[str, list[dict]]:
        now = datetime.now(timezone.utc)
        dates = [(now + timedelta(days=d)).date() for d in range(0, 2)]
        active_cities = get_active_cities(self.config)

        ladders = {}

        for city in active_cities:
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

    async def _discover_markets(self, city: CityConfig, dt) -> list:
        """Discover markets for a city/date, with caching to reduce REST calls."""
        cache_key = f"{city.code}|{dt.isoformat()}"
        now = datetime.now(timezone.utc).timestamp()

        cached = self._discovery_cache.get(cache_key)
        if cached:
            markets, ts = cached
            if now - ts < DISCOVERY_CACHE_TTL_SECONDS and markets:
                return markets

        markets = await self.kalshi.get_city_markets(city.kalshi_series, dt)
        self._discovery_cache[cache_key] = (markets, now)
        return markets

    def _cleanup_discovery_cache(self):
        """Remove stale cache entries (yesterday's markets, etc.)."""
        now = datetime.now(timezone.utc).timestamp()
        stale_keys = [
            k for k, (_, ts) in self._discovery_cache.items()
            if now - ts > 3600  # 1 hour
        ]
        for k in stale_keys:
            del self._discovery_cache[k]

    async def _fetch_event_ladder(self, city: CityConfig, dt) -> tuple[str, list[dict]] | None:
        try:
            markets = await self._discover_markets(city, dt)
        except Exception as e:
            logger.warning("Failed to fetch markets for %s on %s: %s", city.code, dt, e)
            return None

        if not markets:
            return None

        city_date = f"{city.code}|{dt.isoformat()}"

        # Subscribe to WS channels for discovered tickers (idempotent)
        if self.ws and self.ws.is_connected:
            tickers = [m.ticker for m in markets]
            await self.ws.subscribe_orderbook(tickers)
            await self.ws.subscribe_ticker(tickers)

        bins = []
        ws_hits = 0
        rest_hits = 0

        for m in markets:
            try:
                ob = None

                # Try WS local orderbook first
                if self.ws and self.ws.has_orderbook(m.ticker):
                    ws_data = self.ws.get_orderbook_data(m.ticker)
                    if ws_data:
                        ob = KalshiOrderbook(
                            ticker=m.ticker,
                            yes_bids=ws_data["yes_bids"],
                            yes_asks=ws_data["yes_asks"],
                        )
                        ws_hits += 1

                # Fall back to REST
                if ob is None:
                    ob = await self.kalshi.get_orderbook(m.ticker)
                    rest_hits += 1

                # Use ticker channel volume if available (more up-to-date)
                volume = m.volume
                if self.ws:
                    td = self.ws.get_ticker_data(m.ticker)
                    if td and td.get("volume") is not None:
                        volume = td["volume"]

                enriched = self._enrich_market(m, ob, volume)
                if enriched is not None:
                    bins.append(enriched)
            except Exception as e:
                logger.warning("Enrich exception in %s for %s: %s", city_date, m.ticker, e)

        if markets and not bins:
            logger.info("%s: %d markets found, 0 passed enrichment", city_date, len(markets))
        elif bins:
            logger.info("%s: %d/%d bins enriched (ws=%d, rest=%d)",
                        city_date, len(bins), len(markets), ws_hits, rest_hits)
        return city_date, bins

    def _enrich_market(self, market, ob, volume: int = 0) -> dict | None:
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
            "volume": volume,
            "city_date": "",  # set by caller
            "temp_low": market.temp_low,
            "temp_high": market.temp_high,
            "is_open_low": market.is_open_low,
            "is_open_high": market.is_open_high,
        }

    async def close(self):
        self._cleanup_discovery_cache()

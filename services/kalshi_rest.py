"""Async Kalshi REST client with RSA-PSS authentication."""

import asyncio
import base64
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx
from cryptography.hazmat.primitives.asymmetric import padding, utils as crypto_utils
from cryptography.hazmat.primitives import hashes, serialization

logger = logging.getLogger("coldsync.kalshi")

PROD_BASE = "https://api.elections.kalshi.com/trade-api/v2"
DEMO_BASE = "https://demo-api.kalshi.co/trade-api/v2"
PROD_WS = "wss://api.elections.kalshi.com/trade-api/ws/v2"
DEMO_WS = "wss://demo-api.kalshi.co/trade-api/ws/v2"


@dataclass
class KalshiMarket:
    """Represents a single market bin from Kalshi."""
    ticker: str
    event_ticker: str
    question: str = ""
    yes_price: float = 0.0
    no_price: float = 0.0
    yes_bid: float = 0.0
    yes_ask: float = 0.0
    spread: float = 0.0
    volume: int = 0
    temp_low: Optional[int] = None
    temp_high: Optional[int] = None
    close_time: str = ""


@dataclass
class Orderbook:
    """Parsed orderbook with yes bids/asks as [(price, quantity), ...]."""
    yes_bids: list = field(default_factory=list)
    yes_asks: list = field(default_factory=list)
    ticker: str = ""

    def best_bid(self) -> Optional[float]:
        return self.yes_bids[0][0] if self.yes_bids else None

    def best_ask(self) -> Optional[float]:
        return self.yes_asks[0][0] if self.yes_asks else None

    def spread(self) -> float:
        b, a = self.best_bid(), self.best_ask()
        if b is not None and a is not None:
            return a - b
        return 1.0

    def depth_within(self, cents: float = 0.02) -> float:
        """Total USD available within `cents` of best ask."""
        if not self.yes_asks:
            return 0.0
        ref = self.yes_asks[0][0]
        total = 0.0
        for price, qty in self.yes_asks:
            if price <= ref + cents:
                total += price * qty
            else:
                break
        return total


class KalshiClient:
    """Async Kalshi API client with RSA-PSS request signing."""

    TEMP_SERIES_PREFIX = "KXTEMP"

    def __init__(self, key_id: str, private_key_pem: str, env: str = "demo"):
        self.key_id = key_id
        self.env = env
        self.base_url = PROD_BASE if env == "prod" else DEMO_BASE
        self.ws_url = PROD_WS if env == "prod" else DEMO_WS

        self._private_key = None
        if private_key_pem:
            pem = private_key_pem
            if "\\n" in pem:
                pem = pem.replace("\\n", "\n")
            if not pem.startswith("-----"):
                pem = f"-----BEGIN RSA PRIVATE KEY-----\n{pem}\n-----END RSA PRIVATE KEY-----"
            try:
                self._private_key = serialization.load_pem_private_key(
                    pem.encode(), password=None
                )
            except Exception as e:
                logger.error("Failed to load private key: %s", e)

        self._client = httpx.AsyncClient(timeout=15.0)
        self._sem = asyncio.Semaphore(2)
        self._last_request = 0.0
        self._min_interval = 0.12

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------
    def _sign_request(self, method: str, path: str, timestamp_ms: int) -> str:
        msg = f"{timestamp_ms}{method}{path}"
        digest = hashlib.sha256(msg.encode()).digest()
        sig = self._private_key.sign(
            digest,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            crypto_utils.Prehashed(hashes.SHA256()),
        )
        return base64.b64encode(sig).decode()

    def _auth_headers(self, method: str, path: str) -> dict:
        ts = int(time.time() * 1000)
        sig = self._sign_request(method.upper(), path, ts)
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": str(ts),
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # HTTP wrappers with rate limiting
    # ------------------------------------------------------------------
    async def _rate_limit(self):
        now = time.monotonic()
        elapsed = now - self._last_request
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_request = time.monotonic()

    async def _get(self, path: str, params: dict = None) -> dict:
        async with self._sem:
            await self._rate_limit()
            full_path = f"/trade-api/v2{path}"
            headers = self._auth_headers("GET", full_path) if self._private_key else {}
            url = f"{self.base_url}{path}"
            resp = await self._client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, body: dict) -> dict:
        async with self._sem:
            await self._rate_limit()
            full_path = f"/trade-api/v2{path}"
            headers = self._auth_headers("POST", full_path) if self._private_key else {}
            url = f"{self.base_url}{path}"
            resp = await self._client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            return resp.json()

    async def _delete(self, path: str) -> dict:
        async with self._sem:
            await self._rate_limit()
            full_path = f"/trade-api/v2{path}"
            headers = self._auth_headers("DELETE", full_path) if self._private_key else {}
            url = f"{self.base_url}{path}"
            resp = await self._client.delete(url, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def close(self):
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Price parsing helpers
    # ------------------------------------------------------------------
    def _parse_volume(self, raw: dict) -> int:
        """Parse volume from volume_fp (string) or volume (int)."""
        vfp = raw.get("volume_fp")
        if vfp is not None:
            try:
                return int(float(vfp))
            except (ValueError, TypeError):
                pass
        return int(raw.get("volume", 0))

    def _parse_dollar_price(self, raw: dict, field: str, legacy_field: str = "") -> float:
        """Parse dollar price field (string) with fallback to legacy cents field."""
        val = raw.get(field)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
        if legacy_field:
            val = raw.get(legacy_field)
            if val is not None:
                try:
                    v = float(val)
                    if v >= 1:
                        return v / 100.0
                    return v
                except (ValueError, TypeError):
                    pass
        return 0.0

    # ------------------------------------------------------------------
    # Temperature market helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_temp_range(title: str) -> tuple[Optional[int], Optional[int]]:
        """Extract temp range from market title like 'Between 50°F and 59°F'."""
        import re
        m = re.search(r"(\d+)\s*°?\s*F?\s*(?:and|to|-)\s*(\d+)\s*°?\s*F?", title)
        if m:
            return int(m.group(1)), int(m.group(2))
        m = re.search(r"(\d+)\s*°?\s*F?\s*or\s*(higher|lower|above|below)", title, re.IGNORECASE)
        if m:
            temp = int(m.group(1))
            direction = m.group(2).lower()
            if direction in ("higher", "above"):
                return temp, temp + 20
            else:
                return temp - 20, temp
        return None, None

    # ------------------------------------------------------------------
    # Market discovery
    # ------------------------------------------------------------------
    async def get_active_temp_series(self) -> list[str]:
        """Find all active temperature-related event series."""
        try:
            data = await self._get("/events", params={
                "status": "open",
                "series_ticker": self.TEMP_SERIES_PREFIX,
                "limit": 200,
            })
            events = data.get("events", [])
            series = set()
            for ev in events:
                st = ev.get("series_ticker", "")
                if st.startswith(self.TEMP_SERIES_PREFIX):
                    series.add(st)
            return sorted(series)
        except Exception as e:
            logger.error("Failed to fetch temp series: %s", e)
            return []

    async def get_events_for_series(self, series_ticker: str) -> list[dict]:
        """Fetch all open events for a given series ticker."""
        try:
            data = await self._get("/events", params={
                "status": "open",
                "series_ticker": series_ticker,
                "limit": 100,
            })
            return data.get("events", [])
        except Exception as e:
            logger.error("Failed to fetch events for %s: %s", series_ticker, e)
            return []

    async def get_markets_for_event(self, event_ticker: str) -> list[KalshiMarket]:
        """Fetch all markets (bins) for a given event."""
        try:
            data = await self._get("/markets", params={
                "event_ticker": event_ticker,
                "limit": 100,
            })
            markets = []
            for m in data.get("markets", []):
                if m.get("status") != "open":
                    continue
                yes_bid = self._parse_dollar_price(m, "yes_bid_dollars", "yes_bid")
                yes_ask = self._parse_dollar_price(m, "yes_ask_dollars", "yes_ask")
                no_bid = self._parse_dollar_price(m, "no_bid_dollars", "no_bid")
                no_ask = self._parse_dollar_price(m, "no_ask_dollars", "no_ask")
                yes_price = (yes_bid + yes_ask) / 2 if yes_bid and yes_ask else yes_bid or yes_ask
                no_price = (no_bid + no_ask) / 2 if no_bid and no_ask else no_bid or no_ask
                spread = abs(yes_ask - yes_bid) if yes_bid and yes_ask else 1.0
                temp_low, temp_high = self._parse_temp_range(
                    m.get("title", "") or m.get("subtitle", "")
                )
                markets.append(KalshiMarket(
                    ticker=m["ticker"],
                    event_ticker=event_ticker,
                    question=m.get("title", "") or m.get("subtitle", ""),
                    yes_price=yes_price,
                    no_price=no_price,
                    yes_bid=yes_bid,
                    yes_ask=yes_ask,
                    spread=spread,
                    volume=self._parse_volume(m),
                    temp_low=temp_low,
                    temp_high=temp_high,
                    close_time=m.get("close_time", ""),
                ))
            return sorted(markets, key=lambda x: (x.temp_low or 0))
        except Exception as e:
            logger.error("Failed to fetch markets for event %s: %s", event_ticker, e)
            return []

    async def get_markets_for_series_date(self, series_ticker: str,
                                           date_str: str) -> list[KalshiMarket]:
        """Fetch markets for a series+date combo (e.g., KXTEMPMIA, 2026-03-31)."""
        events = await self.get_events_for_series(series_ticker)
        target_events = []
        for ev in events:
            et = ev.get("event_ticker", "")
            if date_str.replace("-", "") in et or date_str in et:
                target_events.append(et)

        all_markets = []
        for et in target_events:
            markets = await self.get_markets_for_event(et)
            all_markets.extend(markets)
        return all_markets

    # ------------------------------------------------------------------
    # Orderbook
    # ------------------------------------------------------------------
    async def get_orderbook(self, ticker: str) -> Optional[Orderbook]:
        """Fetch orderbook for a single market."""
        try:
            data = await self._get(f"/orderbook/{ticker}")
            ob = data.get("orderbook", data)

            yes_bids = []
            yes_asks = []

            for entry in ob.get("yes", []):
                price = float(entry.get("price_dollars", entry.get("price", 0)))
                if price >= 1:
                    price = price / 100.0
                qty = int(float(entry.get("quantity_fp", entry.get("quantity", 0))))
                if entry.get("side") == "bid" or "bid" in str(entry):
                    yes_bids.append((price, qty))
                else:
                    yes_asks.append((price, qty))

            for entry in ob.get("no", []):
                price = float(entry.get("price_dollars", entry.get("price", 0)))
                if price >= 1:
                    price = price / 100.0
                qty = int(float(entry.get("quantity_fp", entry.get("quantity", 0))))
                no_price = price
                yes_equiv = 1.0 - no_price
                if entry.get("side") == "bid" or "bid" in str(entry):
                    yes_asks.append((yes_equiv, qty))
                else:
                    yes_bids.append((yes_equiv, qty))

            yes_bids.sort(key=lambda x: -x[0])
            yes_asks.sort(key=lambda x: x[0])

            return Orderbook(yes_bids=yes_bids, yes_asks=yes_asks, ticker=ticker)
        except Exception as e:
            logger.error("Failed to fetch orderbook for %s: %s", ticker, e)
            return None

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------
    async def get_balance(self) -> Optional[float]:
        try:
            data = await self._get("/portfolio/balance")
            bal = data.get("balance")
            if bal is not None:
                return float(bal) / 100.0
            bal_fp = data.get("balance_fp")
            if bal_fp is not None:
                return float(bal_fp)
            return None
        except Exception as e:
            logger.error("Failed to fetch balance: %s", e)
            return None

    async def get_positions(self) -> list[dict]:
        try:
            data = await self._get("/portfolio/positions", params={"limit": 200})
            positions = data.get("market_positions", [])
            return positions
        except Exception as e:
            logger.error("Failed to fetch positions: %s", e)
            return []

    async def get_settlements(self, ticker: str) -> Optional[dict]:
        try:
            data = await self._get(f"/markets/{ticker}")
            market = data.get("market", data)
            if market.get("result"):
                return {"result": market["result"], "status": market.get("status")}
            return None
        except Exception as e:
            logger.error("Failed to fetch settlement for %s: %s", ticker, e)
            return None

    # ------------------------------------------------------------------
    # Order status
    # ------------------------------------------------------------------
    async def get_order_status(self, order_id: str) -> Optional[dict]:
        try:
            data = await self._get(f"/portfolio/orders/{order_id}")
            return data.get("order", data)
        except Exception as e:
            logger.error("Failed to fetch order status %s: %s", order_id, e)
            return None

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    @staticmethod
    def parse_order_response(result: dict) -> dict:
        """Extract standardized fill info from a Kalshi order response.

        Returns dict with:
          order_id, status, fill_count, remaining_count,
          taker_fill_cost, maker_fill_cost, taker_fees, maker_fees,
          no_price_dollars, yes_price_dollars
        """
        order = result.get("order", {})

        def _fp(val) -> float:
            if val is None:
                return 0.0
            try:
                return float(val)
            except (ValueError, TypeError):
                return 0.0

        return {
            "order_id": order.get("order_id", ""),
            "status": (order.get("status", "") or "").lower(),
            "fill_count": int(_fp(order.get("fill_count_fp", 0))),
            "remaining_count": int(_fp(order.get("remaining_count_fp", 0))),
            "initial_count": int(_fp(order.get("initial_count_fp", 0))),
            "taker_fill_cost": _fp(order.get("taker_fill_cost_dollars")),
            "maker_fill_cost": _fp(order.get("maker_fill_cost_dollars")),
            "taker_fees": _fp(order.get("taker_fees_dollars")),
            "maker_fees": _fp(order.get("maker_fees_dollars")),
            "no_price_dollars": _fp(order.get("no_price_dollars")),
            "yes_price_dollars": _fp(order.get("yes_price_dollars")),
        }

    async def place_order(
        self,
        ticker: str,
        side: str,
        action: str,
        count: int,
        no_price_cents: int | None = None,
        yes_price_cents: int | None = None,
        time_in_force: str | None = None,
        client_order_id: str | None = None,
    ) -> Optional[dict]:
        """Place an order on Kalshi.

        Accepts EITHER no_price_cents or yes_price_cents (one must be provided).
        Returns raw API response dict.
        """
        if client_order_id is None:
            client_order_id = str(uuid.uuid4())

        order_body: dict = {
            "ticker": ticker,
            "action": action,
            "side": side,
            "count": count,
            "type": "limit",
            "client_order_id": client_order_id,
        }

        # Price: prefer no_price for NO orders, yes_price for YES orders
        if no_price_cents is not None:
            if no_price_cents < 1 or no_price_cents > 99:
                logger.error("no_price_cents %d out of range [1,99] for %s", no_price_cents, ticker)
                return None
            order_body["no_price"] = no_price_cents
        elif yes_price_cents is not None:
            if yes_price_cents < 1 or yes_price_cents > 99:
                logger.error("yes_price_cents %d out of range [1,99] for %s", yes_price_cents, ticker)
                return None
            order_body["yes_price"] = yes_price_cents
        else:
            logger.error("No price provided for order on %s", ticker)
            return None

        if time_in_force:
            order_body["time_in_force"] = time_in_force

        if self._private_key is None:
            logger.error("Cannot place order: no private key configured")
            return None

        try:
            result = await self._post("/portfolio/orders", order_body)
            parsed = self.parse_order_response(result)
            price_str = f"no@{no_price_cents}c" if no_price_cents else f"yes@{yes_price_cents}c"
            logger.info(
                "Order placed: %s | %s %s x%d @ %s | filled=%d | id=%s | status=%s",
                ticker, action, side, count, price_str,
                parsed["fill_count"], parsed["order_id"], parsed["status"],
            )
            return result
        except httpx.HTTPStatusError as e:
            logger.error("Order placement failed for %s: %s | body=%s", ticker, e, order_body)
            return None

    async def cancel_order(self, order_id: str) -> dict:
        if self._private_key is None:
            logger.error("Cannot cancel order: no private key configured")
            return {}
        try:
            result = await self._delete(f"/portfolio/orders/{order_id}")
            logger.info("Canceled order: %s", order_id)
            return result
        except httpx.HTTPStatusError as e:
            logger.error("Failed to cancel order %s: %s", order_id, e)
            return {}

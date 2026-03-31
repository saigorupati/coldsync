"""
Async Kalshi API client with RSA-PSS authentication.

Handles market discovery, orderbook fetching, order placement, and portfolio queries.
Ported from kalshi-edge-trader's synchronous client to async httpx.
"""

import re
import time
import uuid
import base64
import asyncio
import logging
import datetime
from zoneinfo import ZoneInfo
from dataclasses import dataclass, field
from typing import Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger("coldsync.kalshi")

DEMO_BASE_URL = "https://demo-api.kalshi.co/trade-api/v2"
PROD_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
REQUEST_TIMEOUT = 20
MIN_REQUEST_INTERVAL = 0.12  # ~8 req/s, comfortably under 10 req/s prod limit
KALSHI_MARKET_TZ = ZoneInfo("America/New_York")


@dataclass
class KalshiMarket:
    ticker: str
    event_ticker: str
    yes_ask: float
    yes_bid: float
    yes_sub_title: str
    temp_low: Optional[float]
    temp_high: Optional[float]
    is_open_low: bool
    is_open_high: bool
    status: str
    volume: int = 0


@dataclass
class KalshiOrderbook:
    ticker: str
    yes_bids: list[dict] = field(default_factory=list)
    yes_asks: list[dict] = field(default_factory=list)

    def best_ask(self) -> Optional[float]:
        if not self.yes_asks:
            return None
        return min(entry["price"] for entry in self.yes_asks)

    def best_bid(self) -> Optional[float]:
        if not self.yes_bids:
            return None
        return max(entry["price"] for entry in self.yes_bids)

    def spread(self) -> Optional[float]:
        ask = self.best_ask()
        bid = self.best_bid()
        if ask is not None and bid is not None:
            return ask - bid
        return None


class KalshiClient:
    def __init__(self, key_id: str, private_key_pem: str, env: str = "demo"):
        self.base_url = DEMO_BASE_URL if env == "demo" else PROD_BASE_URL
        self.key_id = key_id
        self._private_key = self._load_private_key(private_key_pem)
        self._last_request_time = 0.0
        self._http = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
        self._semaphore = asyncio.Semaphore(2)  # max 2 concurrent requests to stay under 10/s

    def _load_private_key(self, pem_or_path: str):
        if not pem_or_path or pem_or_path == "PLACEHOLDER_PEM":
            logger.warning("No Kalshi private key configured — running in read-only mode")
            return None

        # If it looks like a file path, read from disk
        import os
        if os.path.isfile(pem_or_path):
            try:
                with open(pem_or_path, "r") as f:
                    pem = f.read()
                logger.info("Loaded private key from file: %s", pem_or_path)
            except Exception as e:
                logger.error("Failed to read key file %s: %s", pem_or_path, e)
                return None
        else:
            pem = pem_or_path

        pem = pem.replace("\\n", "\n")
        if not pem.strip().startswith("-----"):
            logger.warning("Invalid PEM format for private key")
            return None
        try:
            return serialization.load_pem_private_key(pem.encode(), password=None)
        except Exception as e:
            logger.error("Failed to load private key: %s", e)
            return None

    def _sign_request(self, method: str, path: str) -> dict:
        timestamp_ms = str(int(time.time() * 1000))
        path_no_query = path.split("?")[0]
        # Kalshi requires the FULL path (including /trade-api/v2) in the signature
        full_path = "/trade-api/v2" + path_no_query
        message = f"{timestamp_ms}{method.upper()}{full_path}".encode()

        if self._private_key is None:
            return {}

        signature = self._private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        sig_b64 = base64.b64encode(signature).decode()
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": sig_b64,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        }

    async def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            await asyncio.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        async with self._semaphore:
            url = self.base_url + path
            headers = {"Content-Type": "application/json"}
            headers.update(self._sign_request("GET", path))

            for attempt in range(3):
                await self._rate_limit()
                resp = await self._http.get(url, headers=headers, params=params)
                if resp.status_code != 429:
                    resp.raise_for_status()
                    return resp.json()

                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else (1.0 * (2 ** attempt))
                logger.warning("Rate limit on %s; retrying in %.1fs", path, delay)
                await asyncio.sleep(delay)

            resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, body: dict) -> dict:
        async with self._semaphore:
            await self._rate_limit()
            url = self.base_url + path
            headers = {"Content-Type": "application/json"}
            headers.update(self._sign_request("POST", path))
            resp = await self._http.post(url, headers=headers, json=body)
            resp.raise_for_status()
            return resp.json()

    async def _delete(self, path: str) -> dict:
        async with self._semaphore:
            await self._rate_limit()
            url = self.base_url + path
            headers = {"Content-Type": "application/json"}
            headers.update(self._sign_request("DELETE", path))
            resp = await self._http.delete(url, headers=headers)
            resp.raise_for_status()
            return resp.json() if resp.content else {}

    # ------------------------------------------------------------------
    # Market discovery
    # ------------------------------------------------------------------

    async def get_events_for_series(self, series_ticker: str) -> list[dict]:
        try:
            data = await self._get("/events", params={"series_ticker": series_ticker, "status": "open"})
            return data.get("events", [])
        except Exception as e:
            logger.error("Failed to get events for series %s: %s", series_ticker, e)
            return []

    def _format_event_ticker_for_date(self, series_ticker: str, date_value: datetime.date) -> str:
        return f"{series_ticker}-{date_value.strftime('%y%b%d').upper()}"

    async def get_event_for_date(self, series_ticker: str, target_date: datetime.date) -> Optional[str]:
        """Find the event ticker for a specific date.

        Kalshi close_time for a daily temperature market is ~midnight UTC at the end
        of the measurement day. So event_date == close_time_ET.date() - 1 day.
        """
        expected_close_date = target_date + datetime.timedelta(days=1)

        events = await self.get_events_for_series(series_ticker)
        for event in events:
            close_time = event.get("close_time", "")
            if not close_time:
                continue
            try:
                close_dt = datetime.datetime.fromisoformat(close_time.replace("Z", "+00:00"))
                if close_dt.tzinfo is None:
                    close_dt = close_dt.replace(tzinfo=datetime.timezone.utc)
                close_date_et = close_dt.astimezone(KALSHI_MARKET_TZ).date()
                if close_date_et == expected_close_date:
                    return event["event_ticker"]
            except (ValueError, KeyError):
                continue

        fallback = self._format_event_ticker_for_date(series_ticker, target_date)
        logger.warning("No event found for %s on %s; falling back to %s",
                        series_ticker, target_date, fallback)
        return fallback

    async def get_markets_for_event(self, event_ticker: str) -> list[KalshiMarket]:
        markets_raw: list[dict] = []
        try:
            data = await self._get("/markets", params={"event_ticker": event_ticker, "status": "open"})
            markets_raw = data.get("markets", [])
        except Exception as e:
            logger.error("Failed to get markets for event %s: %s", event_ticker, e)
            return []

        result = []
        for m in markets_raw:
            try:
                yes_ask = self._parse_price(m.get("yes_ask") or m.get("yes_ask_price") or 0)
                yes_bid = self._parse_price(m.get("yes_bid") or m.get("yes_bid_price") or 0)
                subtitle = m.get("yes_sub_title") or m.get("subtitle") or ""
                temp_low, temp_high, is_open_low, is_open_high = self._parse_bounds_from_market(m)

                market_status = (m.get("status", "").lower() or "open")
                if market_status not in {"open", "active"}:
                    continue

                result.append(KalshiMarket(
                    ticker=m["ticker"],
                    event_ticker=event_ticker,
                    yes_ask=yes_ask,
                    yes_bid=yes_bid,
                    yes_sub_title=subtitle,
                    temp_low=temp_low,
                    temp_high=temp_high,
                    is_open_low=is_open_low,
                    is_open_high=is_open_high,
                    status=market_status,
                    volume=int(m.get("volume", 0)),
                ))
            except Exception as e:
                logger.debug("Skipping market %s: %s", m.get("ticker", "?"), e)
                continue

        return result

    async def get_markets_for_series_date(self, series_ticker: str,
                                           target_date: datetime.date) -> list[KalshiMarket]:
        """Get all markets for a series filtered to a specific date."""
        expected_close_date = target_date + datetime.timedelta(days=1)

        markets_raw: list[dict] = []
        try:
            data = await self._get("/markets", params={"series_ticker": series_ticker, "status": "open"})
            markets_raw = data.get("markets", [])
        except Exception as e:
            logger.error("Failed to get markets for series %s: %s", series_ticker, e)
            return []

        filtered = []
        for m in markets_raw:
            close_time = m.get("close_time", "")
            if not close_time:
                continue
            try:
                close_dt = datetime.datetime.fromisoformat(close_time.replace("Z", "+00:00"))
                if close_dt.tzinfo is None:
                    close_dt = close_dt.replace(tzinfo=datetime.timezone.utc)
                if close_dt.astimezone(KALSHI_MARKET_TZ).date() != expected_close_date:
                    continue
            except ValueError:
                continue

            market_status = (m.get("status", "").lower() or "open")
            if market_status not in {"open", "active"}:
                continue
            filtered.append(m)

        result = []
        for m in filtered:
            try:
                yes_ask = self._parse_price(m.get("yes_ask") or m.get("yes_ask_price") or 0)
                yes_bid = self._parse_price(m.get("yes_bid") or m.get("yes_bid_price") or 0)
                subtitle = m.get("yes_sub_title") or m.get("subtitle") or ""
                temp_low, temp_high, is_open_low, is_open_high = self._parse_bounds_from_market(m)

                result.append(KalshiMarket(
                    ticker=m["ticker"],
                    event_ticker=str(m.get("event_ticker", "")),
                    yes_ask=yes_ask,
                    yes_bid=yes_bid,
                    yes_sub_title=subtitle,
                    temp_low=temp_low,
                    temp_high=temp_high,
                    is_open_low=is_open_low,
                    is_open_high=is_open_high,
                    status=market_status,
                    volume=int(m.get("volume", 0)),
                ))
            except Exception as e:
                logger.debug("Skipping market %s: %s", m.get("ticker", "?"), e)
                continue

        return result

    def _parse_price(self, raw) -> float:
        if raw is None:
            return 0.0
        if isinstance(raw, str):
            raw = float(raw)
        if isinstance(raw, (int, float)) and raw > 1:
            return raw / 100.0
        return float(raw)

    def _parse_temp_range(self, subtitle: str) -> tuple[Optional[float], Optional[float], bool, bool]:
        s = subtitle.strip().replace("\u00b0", "°").replace("\u02da", "°")
        DEG = r"[°]?\s*"
        NUM = r"(\d+(?:\.\d+)?)"

        m = re.match(rf"{NUM}{DEG}(?:to|-)\s*{NUM}{DEG}$", s, re.IGNORECASE)
        if m:
            return float(m.group(1)), float(m.group(2)), False, False

        m = re.match(rf"{NUM}{DEG}or\s+(?:below|lower)\s*$", s, re.IGNORECASE)
        if m:
            return None, float(m.group(1)), True, False

        m = re.match(rf"{NUM}{DEG}or\s+(?:above|higher)\s*$", s, re.IGNORECASE)
        if m:
            return float(m.group(1)), None, False, True

        m = re.match(rf"(?:below|under)\s+{NUM}{DEG}$", s, re.IGNORECASE)
        if m:
            return None, float(m.group(1)), True, False

        m = re.match(rf"(?:above|over)\s+{NUM}{DEG}$", s, re.IGNORECASE)
        if m:
            return float(m.group(1)), None, False, True

        m = re.match(rf"{NUM}{DEG}$", s)
        if m:
            val = float(m.group(1))
            return val - 0.5, val + 0.5, False, False

        return None, None, False, False

    def _parse_bounds_from_market(self, raw: dict) -> tuple[Optional[float], Optional[float], bool, bool]:
        strike = raw.get("floor_strike")
        strike_type = (raw.get("strike_type") or "").lower()

        if strike is not None and strike_type:
            s = float(strike)
            if strike_type == "greater":
                return s + 1.0, None, False, True
            if strike_type == "between":
                ceil_strike = raw.get("ceil_strike")
                if ceil_strike is not None:
                    return s, float(ceil_strike), False, False
                subtitle = raw.get("yes_sub_title") or raw.get("subtitle") or ""
                _, temp_high, _, _ = self._parse_temp_range(subtitle)
                return s, temp_high, False, False
            if strike_type == "less":
                return None, s - 1.0, True, False

        subtitle = raw.get("yes_sub_title") or raw.get("subtitle") or ""
        return self._parse_temp_range(subtitle)

    # ------------------------------------------------------------------
    # Orderbook
    # ------------------------------------------------------------------

    async def get_market(self, ticker: str) -> Optional[dict]:
        try:
            data = await self._get(f"/markets/{ticker}")
            return data.get("market", data)
        except Exception as e:
            logger.error("Failed to get market %s: %s", ticker, e)
            return None

    async def get_orderbook(self, ticker: str, depth: int = 10) -> Optional[KalshiOrderbook]:
        try:
            data = await self._get(f"/markets/{ticker}/orderbook", params={"depth": depth})
            ob = data.get("orderbook", data)

            logger.debug("Orderbook raw for %s: yes=%s no=%s",
                         ticker,
                         str(ob.get("yes", []))[:200],
                         str(ob.get("no", []))[:200])

            yes_bids = [
                {"price": self._parse_price(entry[0]), "quantity": entry[1]}
                for entry in (ob.get("yes", []) or [])
            ]
            no_bids = ob.get("no", []) or []
            yes_asks = [
                {"price": 1.0 - self._parse_price(entry[0]), "quantity": entry[1]}
                for entry in no_bids
            ]

            return KalshiOrderbook(ticker=ticker, yes_bids=yes_bids, yes_asks=yes_asks)
        except Exception as e:
            logger.error("Failed to get orderbook for %s: %s", ticker, e)
            return None

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------

    async def get_balance(self) -> float:
        if self._private_key is None:
            return 0.0
        try:
            data = await self._get("/portfolio/balance")
            balance_cents = data.get("balance", 0)
            return balance_cents / 100.0
        except Exception as e:
            logger.error("Failed to get balance: %s", e)
            return 0.0

    async def get_positions(self) -> list[dict]:
        if self._private_key is None:
            return []
        try:
            data = await self._get("/portfolio/positions")
            return data.get("market_positions", [])
        except Exception as e:
            logger.error("Failed to fetch positions: %s", e)
            return []

    async def get_open_orders(self) -> list[dict]:
        if self._private_key is None:
            return []
        try:
            data = await self._get("/portfolio/orders", params={"status": "resting"})
            return data.get("orders", [])
        except Exception as e:
            logger.error("Failed to fetch open orders: %s", e)
            return []

    async def get_order_status(self, order_id: str) -> Optional[dict]:
        if self._private_key is None:
            return None
        try:
            data = await self._get(f"/portfolio/orders/{order_id}")
            return data.get("order", data)
        except Exception as e:
            logger.error("Failed to fetch order status %s: %s", order_id, e)
            return None

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    async def place_order(
        self,
        ticker: str,
        side: str,
        action: str,
        count: int,
        yes_price_cents: int,
        client_order_id: str | None = None,
    ) -> Optional[dict]:
        if client_order_id is None:
            client_order_id = str(uuid.uuid4())

        order_body = {
            "ticker": ticker,
            "action": action,
            "side": side,
            "count": count,
            "type": "limit",
            "yes_price": yes_price_cents,
            "client_order_id": client_order_id,
        }

        if self._private_key is None:
            logger.error("Cannot place order: no private key configured")
            return None

        try:
            result = await self._post("/portfolio/orders", order_body)
            logger.info(
                "Order placed: %s | %s x%d @ %d¢ | id=%s",
                ticker, f"{action} {side}", count, yes_price_cents,
                result.get("order", {}).get("order_id", "?"),
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

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    async def get_city_markets(self, series_ticker: str,
                                target_date: datetime.date) -> list[KalshiMarket]:
        """End-to-end market discovery for a specific date."""
        markets = await self.get_markets_for_series_date(series_ticker, target_date)
        if markets:
            return markets

        event_ticker = await self.get_event_for_date(series_ticker, target_date)
        if event_ticker is None:
            return []
        return await self.get_markets_for_event(event_ticker)

    async def close(self):
        await self._http.aclose()

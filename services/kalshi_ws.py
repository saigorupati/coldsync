"""
Kalshi WebSocket client for real-time orderbook and fill monitoring.

Subscribes to:
- orderbook_delta: price updates for exit trigger detection
- fill: fill notifications for position tracking

Auto-reconnects with exponential backoff.
"""

import asyncio
import json
import time
import base64
import logging

import websockets
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger("coldsync.ws")

DEMO_WS_URL = "wss://demo-api.kalshi.co/trade-api/ws/v2"
PROD_WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"


class KalshiWebSocket:
    def __init__(self, key_id: str, private_key_pem: str, env: str = "demo",
                 price_queue: asyncio.Queue | None = None,
                 fill_queue: asyncio.Queue | None = None):
        self.ws_url = DEMO_WS_URL if env == "demo" else PROD_WS_URL
        self.key_id = key_id
        self._private_key = self._load_private_key(private_key_pem)
        self.price_queue = price_queue or asyncio.Queue()
        self.fill_queue = fill_queue or asyncio.Queue()
        self._subscribed_tickers: set[str] = set()
        self._ws = None
        self._cmd_id = 0
        self._connected = False
        self._reconnect_delay = 5.0
        self._max_reconnect_delay = 60.0

    def _load_private_key(self, pem_or_path: str):
        if not pem_or_path or pem_or_path == "PLACEHOLDER_PEM":
            return None
        import os
        if os.path.isfile(pem_or_path):
            try:
                with open(pem_or_path, "r") as f:
                    pem = f.read()
            except Exception:
                return None
        else:
            pem = pem_or_path
        pem = pem.replace("\\n", "\n")
        if not pem.strip().startswith("-----"):
            return None
        try:
            return serialization.load_pem_private_key(pem.encode(), password=None)
        except Exception:
            return None

    def _get_auth_headers(self) -> dict:
        if self._private_key is None:
            return {}
        timestamp_ms = str(int(time.time() * 1000))
        # For WebSocket, sign GET /trade-api/ws/v2
        path = "/trade-api/ws/v2"
        message = f"{timestamp_ms}GET{path}".encode()
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

    def _next_cmd_id(self) -> int:
        self._cmd_id += 1
        return self._cmd_id

    async def subscribe_orderbook(self, tickers: list[str]):
        new_tickers = [t for t in tickers if t not in self._subscribed_tickers]
        if not new_tickers or not self._ws:
            return
        msg = {
            "id": self._next_cmd_id(),
            "cmd": "subscribe",
            "params": {
                "channels": ["orderbook_delta"],
                "market_tickers": new_tickers,
            },
        }
        try:
            await self._ws.send(json.dumps(msg))
            self._subscribed_tickers.update(new_tickers)
            logger.info("WS subscribed to orderbook for %d tickers", len(new_tickers))
        except Exception as e:
            logger.warning("WS subscribe failed: %s", e)

    async def unsubscribe_orderbook(self, tickers: list[str]):
        to_unsub = [t for t in tickers if t in self._subscribed_tickers]
        if not to_unsub or not self._ws:
            return
        # Kalshi WS doesn't have a direct unsubscribe for specific tickers
        # within a channel — we just stop tracking them locally
        for t in to_unsub:
            self._subscribed_tickers.discard(t)

    async def subscribe_fills(self):
        if not self._ws:
            return
        msg = {
            "id": self._next_cmd_id(),
            "cmd": "subscribe",
            "params": {"channels": ["fill"]},
        }
        try:
            await self._ws.send(json.dumps(msg))
            logger.info("WS subscribed to fill channel")
        except Exception as e:
            logger.warning("WS fill subscribe failed: %s", e)

    async def run(self):
        delay = self._reconnect_delay
        while True:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                logger.info("WS task cancelled")
                break
            except Exception as e:
                logger.warning("WS connection error: %s. Reconnecting in %.0fs", e, delay)

            self._connected = False
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, self._max_reconnect_delay)

    async def _connect_and_listen(self):
        headers = self._get_auth_headers()
        async with websockets.connect(self.ws_url, additional_headers=headers) as ws:
            self._ws = ws
            self._connected = True
            logger.info("WS connected to %s", self.ws_url)

            # Re-subscribe after reconnect
            await self.subscribe_fills()
            if self._subscribed_tickers:
                tickers = list(self._subscribed_tickers)
                self._subscribed_tickers.clear()
                await self.subscribe_orderbook(tickers)

            async for raw_msg in ws:
                try:
                    msg = json.loads(raw_msg)
                    await self._handle_message(msg)
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    logger.warning("WS message handling error: %s", e)

    async def _handle_message(self, msg: dict):
        msg_type = msg.get("type", "")

        if msg_type == "orderbook_snapshot":
            ticker = msg.get("msg", {}).get("market_ticker", "")
            if ticker and ticker in self._subscribed_tickers:
                yes_data = msg.get("msg", {}).get("yes", [])
                no_data = msg.get("msg", {}).get("no", [])
                price_info = self._extract_prices_from_snapshot(yes_data, no_data)
                if price_info:
                    await self.price_queue.put((ticker, price_info["yes_bid"], price_info["yes_ask"]))

        elif msg_type == "orderbook_delta":
            ticker = msg.get("msg", {}).get("market_ticker", "")
            if ticker and ticker in self._subscribed_tickers:
                # Delta updates are incremental — for simplicity, just signal
                # that this ticker has changed. Exit manager will check if needed.
                await self.price_queue.put((ticker, None, None))

        elif msg_type == "fill":
            fill = msg.get("msg", {})
            await self.fill_queue.put(fill)

    def _extract_prices_from_snapshot(self, yes_data: list, no_data: list) -> dict | None:
        yes_bid = None
        yes_ask = None

        if yes_data:
            # yes_data contains [price, quantity] pairs for YES bids
            yes_bid = max(entry[0] / 100.0 for entry in yes_data) if yes_data else None

        if no_data:
            # no_data contains [price, quantity] pairs for NO bids
            # NO bid price implies YES ask: yes_ask = 1 - no_bid
            best_no_bid = max(entry[0] / 100.0 for entry in no_data) if no_data else None
            if best_no_bid is not None:
                yes_ask = 1.0 - best_no_bid

        if yes_bid is not None or yes_ask is not None:
            return {"yes_bid": yes_bid, "yes_ask": yes_ask}
        return None

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def close(self):
        self._connected = False
        if self._ws:
            await self._ws.close()

"""
Kalshi WebSocket client for real-time market data.

Subscribes to:
- ticker: real-time yes_bid, yes_ask, volume for all monitored markets
- orderbook_delta: full orderbook snapshots + incremental updates
- fill: fill notifications for position tracking

Maintains local orderbook state from snapshots + deltas.
Auto-reconnects with exponential backoff.
"""

import asyncio
import json
import time
import base64
import logging
from collections import defaultdict

import websockets
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger("coldsync.ws")

# Kalshi WS endpoint (NOT /trade-api/ws/v2 — that's the old URL)
DEMO_WS_URL = "wss://demo-api.kalshi.co/trade-api/ws/v2"
PROD_WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"


class LocalOrderbook:
    """Maintains a local orderbook from WS snapshots + deltas."""

    def __init__(self):
        # {price_str: quantity_float} for YES and NO sides
        self.yes_levels: dict[str, float] = {}
        self.no_levels: dict[str, float] = {}
        self.seq: int = 0

    def apply_snapshot(self, yes_dollars_fp: list, no_dollars_fp: list, seq: int):
        """Replace entire book from snapshot."""
        self.yes_levels.clear()
        self.no_levels.clear()
        for entry in (yes_dollars_fp or []):
            price, qty = str(entry[0]), float(entry[1])
            if qty > 0:
                self.yes_levels[price] = qty
        for entry in (no_dollars_fp or []):
            price, qty = str(entry[0]), float(entry[1])
            if qty > 0:
                self.no_levels[price] = qty
        self.seq = seq

    def apply_delta(self, side: str, price_dollars: str, delta_fp: str):
        """Apply incremental delta to one side."""
        levels = self.yes_levels if side == "yes" else self.no_levels
        delta = float(delta_fp)
        current = levels.get(price_dollars, 0.0)
        new_qty = current + delta
        if new_qty <= 0:
            levels.pop(price_dollars, None)
        else:
            levels[price_dollars] = new_qty

    def best_yes_bid(self) -> float | None:
        if not self.yes_levels:
            return None
        return max(float(p) for p in self.yes_levels)

    def best_yes_ask(self) -> float | None:
        """Derive YES ask from NO bids: yes_ask = 1.0 - best_no_bid."""
        if not self.no_levels:
            return None
        best_no_bid = max(float(p) for p in self.no_levels)
        return 1.0 - best_no_bid

    def to_enrichment_data(self) -> dict | None:
        """Convert to the format scanner._enrich_market expects."""
        if not self.yes_levels and not self.no_levels:
            return None

        yes_bids = [
            {"price": float(p), "quantity": q}
            for p, q in self.yes_levels.items()
        ]
        yes_asks = [
            {"price": 1.0 - float(p), "quantity": q}
            for p, q in self.no_levels.items()
        ]
        return {"yes_bids": yes_bids, "yes_asks": yes_asks}


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
        self._orderbook_tickers: set[str] = set()
        self._ticker_tickers: set[str] = set()
        self._ws = None
        self._cmd_id = 0
        self._connected = False
        self._reconnect_delay = 5.0
        self._max_reconnect_delay = 60.0

        # Local orderbook state per ticker
        self.orderbooks: dict[str, LocalOrderbook] = defaultdict(LocalOrderbook)

        # Latest ticker data per market (from ticker channel)
        self.ticker_data: dict[str, dict] = {}

        # Latest position data per market (from market_positions channel)
        self.position_data: dict[str, dict] = {}

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
        # Sign the WS path for handshake auth
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

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    async def subscribe_ticker(self, tickers: list[str]):
        """Subscribe to ticker channel for real-time price/volume updates."""
        new_tickers = [t for t in tickers if t not in self._ticker_tickers]
        if not new_tickers or not self._ws:
            return
        msg = {
            "id": self._next_cmd_id(),
            "cmd": "subscribe",
            "params": {
                "channels": ["ticker"],
                "market_tickers": new_tickers,
            },
        }
        try:
            await self._ws.send(json.dumps(msg))
            self._ticker_tickers.update(new_tickers)
            logger.info("WS subscribed ticker for %d tickers (%d total)",
                        len(new_tickers), len(self._ticker_tickers))
        except Exception as e:
            logger.warning("WS ticker subscribe failed: %s", e)

    async def subscribe_orderbook(self, tickers: list[str]):
        """Subscribe to orderbook_delta channel for full book state."""
        new_tickers = [t for t in tickers if t not in self._orderbook_tickers]
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
            self._orderbook_tickers.update(new_tickers)
            self._subscribed_tickers.update(new_tickers)
            logger.info("WS subscribed orderbook for %d tickers (%d total)",
                        len(new_tickers), len(self._orderbook_tickers))
        except Exception as e:
            logger.warning("WS orderbook subscribe failed: %s", e)

    async def unsubscribe_orderbook(self, tickers: list[str]):
        """Stop tracking orderbook for tickers."""
        for t in tickers:
            self._orderbook_tickers.discard(t)
            self._subscribed_tickers.discard(t)
            self.orderbooks.pop(t, None)

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

    async def subscribe_positions(self):
        """Subscribe to real-time position updates."""
        if not self._ws:
            return
        msg = {
            "id": self._next_cmd_id(),
            "cmd": "subscribe",
            "params": {"channels": ["market_positions"]},
        }
        try:
            await self._ws.send(json.dumps(msg))
            logger.info("WS subscribed to market_positions channel")
        except Exception as e:
            logger.warning("WS market_positions subscribe failed: %s", e)

    # ------------------------------------------------------------------
    # Connection loop
    # ------------------------------------------------------------------

    async def run(self):
        delay = self._reconnect_delay
        while True:
            try:
                await self._connect_and_listen()
                delay = self._reconnect_delay  # reset on clean disconnect
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
            await self.subscribe_positions()

            # Re-subscribe orderbook tickers
            if self._orderbook_tickers:
                tickers = list(self._orderbook_tickers)
                self._orderbook_tickers.clear()
                await self.subscribe_orderbook(tickers)

            # Re-subscribe ticker channel
            if self._ticker_tickers:
                tickers = list(self._ticker_tickers)
                self._ticker_tickers.clear()
                await self.subscribe_ticker(tickers)

            async for raw_msg in ws:
                try:
                    msg = json.loads(raw_msg)
                    await self._handle_message(msg)
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    logger.warning("WS message handling error: %s", e)

    # ------------------------------------------------------------------
    # Message dispatch
    # ------------------------------------------------------------------

    async def _handle_message(self, msg: dict):
        msg_type = msg.get("type", "")

        if msg_type == "orderbook_snapshot":
            await self._handle_orderbook_snapshot(msg)

        elif msg_type == "orderbook_delta":
            await self._handle_orderbook_delta(msg)

        elif msg_type == "ticker":
            await self._handle_ticker(msg)

        elif msg_type == "fill":
            fill = msg.get("msg", {})
            await self.fill_queue.put(fill)

        elif msg_type == "market_position":
            inner = msg.get("msg", {})
            ticker = inner.get("market_ticker", "")
            position = float(inner.get("position_fp", "0"))
            cost = float(inner.get("position_cost_dollars", "0"))
            rpnl = float(inner.get("realized_pnl_dollars", "0"))
            logger.info("Position update %s: pos=%.0f cost=$%.2f rpnl=$%.2f",
                        ticker, position, cost, rpnl)
            # Store for position manager to access
            self.position_data[ticker] = {
                "position": position,
                "cost_dollars": cost,
                "realized_pnl_dollars": rpnl,
                "fees_dollars": float(inner.get("fees_paid_dollars", "0")),
                "volume": float(inner.get("volume_fp", "0")),
            }

        elif msg_type in ("subscribed", "unsubscribed", "ok"):
            pass  # ack messages

        elif msg_type == "error":
            logger.warning("WS error: %s", msg)

    async def _handle_orderbook_snapshot(self, msg: dict):
        inner = msg.get("msg", {})
        ticker = inner.get("market_ticker", "")
        seq = msg.get("seq", 0)
        if not ticker:
            return

        yes_fp = inner.get("yes_dollars_fp", [])
        no_fp = inner.get("no_dollars_fp", [])

        ob = self.orderbooks[ticker]
        ob.apply_snapshot(yes_fp, no_fp, seq)

        logger.debug("OB snapshot %s: %d yes, %d no levels (seq=%d)",
                      ticker, len(ob.yes_levels), len(ob.no_levels), seq)

        # Push price update to exit manager queue
        yes_bid = ob.best_yes_bid()
        yes_ask = ob.best_yes_ask()
        if yes_bid is not None or yes_ask is not None:
            await self.price_queue.put((ticker, yes_bid, yes_ask))

    async def _handle_orderbook_delta(self, msg: dict):
        inner = msg.get("msg", {})
        ticker = inner.get("market_ticker", "")
        if not ticker or ticker not in self.orderbooks:
            return

        side = inner.get("side", "")
        price_dollars = inner.get("price_dollars", "")
        delta_fp = inner.get("delta_fp", "0")

        if not side or not price_dollars:
            return

        ob = self.orderbooks[ticker]
        ob.apply_delta(side, price_dollars, delta_fp)

        # Push updated price to exit manager
        yes_bid = ob.best_yes_bid()
        yes_ask = ob.best_yes_ask()
        if yes_bid is not None or yes_ask is not None:
            await self.price_queue.put((ticker, yes_bid, yes_ask))

    async def _handle_ticker(self, msg: dict):
        """Handle ticker channel updates — price, volume, open interest."""
        inner = msg.get("msg", {})
        ticker = inner.get("market_ticker", "")
        if not ticker:
            return

        self.ticker_data[ticker] = {
            "yes_bid": float(inner["yes_bid_dollars"]) if inner.get("yes_bid_dollars") else None,
            "yes_ask": float(inner["yes_ask_dollars"]) if inner.get("yes_ask_dollars") else None,
            "volume": int(float(inner["volume_fp"])) if inner.get("volume_fp") else None,
            "open_interest": int(float(inner["open_interest_fp"])) if inner.get("open_interest_fp") else None,
            "last_price": float(inner["price_dollars"]) if inner.get("price_dollars") else None,
            "ts": inner.get("ts"),
        }

        # Also push to price queue for exit manager
        td = self.ticker_data[ticker]
        if td["yes_bid"] is not None or td["yes_ask"] is not None:
            await self.price_queue.put((ticker, td["yes_bid"], td["yes_ask"]))

    # ------------------------------------------------------------------
    # Accessors for scanner/enrichment
    # ------------------------------------------------------------------

    def get_orderbook_data(self, ticker: str) -> dict | None:
        """Get local orderbook in the format scanner expects (yes_bids, yes_asks)."""
        if ticker not in self.orderbooks:
            return None
        return self.orderbooks[ticker].to_enrichment_data()

    def get_ticker_data(self, ticker: str) -> dict | None:
        """Get latest ticker data (prices, volume)."""
        return self.ticker_data.get(ticker)

    def has_orderbook(self, ticker: str) -> bool:
        ob = self.orderbooks.get(ticker)
        return ob is not None and (bool(ob.yes_levels) or bool(ob.no_levels))

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def close(self):
        self._connected = False
        if self._ws:
            await self._ws.close()

import logging
import time
import uuid

from services.kalshi_rest import KalshiClient

logger = logging.getLogger("coldsync.executor")


class OrderExecutor:
    NO_LIQUIDITY_COOLDOWN = 600  # 10 minutes

    def __init__(self, config, kalshi: KalshiClient, db, discord):
        self.config = config
        self.kalshi = kalshi
        self.db = db
        self.tg = discord
        self._no_liquidity_cache: dict[str, float] = {}

    async def execute_no_buy(self, market: dict, size_usd: float, tier: str) -> dict:
        ticker = market["ticker"]

        # Skip markets that recently failed due to no liquidity
        cached_fail = self._no_liquidity_cache.get(ticker, 0)
        if cached_fail > 0 and (time.time() - cached_fail) < self.NO_LIQUIDITY_COOLDOWN:
            return {"status": "skipped", "reason": "no liquidity cooldown"}

        no_price = market["no_price"]
        no_ask = market.get("no_ask", no_price)

        # If ask exceeds max, place resting limit order at mid
        if no_ask > self.config.no_price_max:
            if no_price <= self.config.no_price_max:
                return await self._place_no_limit_order(market, size_usd, tier, no_price)
            logger.info("No buy rejected: ask %.1fc & mid %.1fc both > max %.1fc — %s",
                        no_ask * 100, no_price * 100, self.config.no_price_max * 100,
                        market["question"][:50])
            return {"status": "skipped", "reason": f"no_ask {no_ask:.3f} > no_price_max"}

        if market["spread"] > self.config.max_spread:
            return {"status": "skipped", "reason": "spread too wide"}

        # Calculate order: buying NO means yes_price_cents is low
        # NO price = 1 - yes_price, so yes_price_cents = 100 - no_price_cents
        no_price_cents = int(no_ask * 100)
        yes_price_cents = 100 - no_price_cents
        count = max(1, int(size_usd / no_ask))

        if self.config.dry_run:
            logger.info("[DRY RUN] No buy tier %s: %s @ %.1fc, %d contracts, $%.2f",
                        tier, market["question"][:60], no_ask * 100, count, size_usd)
            return {"status": "dry_run", "intended_price": no_ask, "count": count, "cost_usd": size_usd}

        client_order_id = str(uuid.uuid4())
        try:
            result = await self.kalshi.place_order(
                ticker=ticker,
                side="no",
                action="buy",
                count=count,
                yes_price_cents=yes_price_cents,
                client_order_id=client_order_id,
            )
        except Exception as e:
            logger.error("No buy exception for %s: %s", ticker, e)
            self._no_liquidity_cache[ticker] = time.time()
            return {"status": "error", "reason": str(e)}

        if result is None:
            self._no_liquidity_cache[ticker] = time.time()
            return {"status": "error", "reason": "place_order returned None"}

        order = result.get("order", {})
        order_id = order.get("order_id", "")
        status = order.get("status", "unknown")

        # Kalshi returns fill info in the order response
        filled_count = int(order.get("count", 0)) if status == "executed" else 0
        if status == "resting":
            filled_count = 0  # resting means not yet filled
        elif status in ("executed", "filled"):
            filled_count = count  # fully filled

        fill_cost = filled_count * no_ask
        final_status = "matched" if filled_count > 0 else status

        trade = {
            "ticker": ticker,
            "type": f"no_buy_tier_{tier}",
            "side": "no",
            "action": "buy",
            "intended_price": no_ask,
            "fill_price": no_ask,
            "count": filled_count,
            "cost_usd": fill_cost,
            "status": final_status,
            "question": market.get("question", ""),
            "close_time": market.get("close_time"),
            "city_date": market.get("city_date", ""),
            "order_id": order_id,
        }
        await self.db.log_trade(trade)

        if filled_count > 0:
            await self.db.upsert_position({
                "ticker": ticker,
                "event_ticker": market.get("event_ticker", ""),
                "question": market.get("question", ""),
                "no_contracts": filled_count,
                "no_cost": fill_cost,
                "entry_price_no": no_ask,
                "city_date": market.get("city_date", ""),
                "close_time": market.get("close_time"),
            })
            await self.tg.send_trade_alert(trade)
        elif final_status == "resting":
            # Track as open order
            await self.db.insert_open_order({
                "order_id": order_id,
                "ticker": ticker,
                "side": "no",
                "order_type": f"no_buy_tier_{tier}",
                "price": no_ask,
                "count": count,
                "question": market.get("question", ""),
                "city_date": market.get("city_date", ""),
                "close_time": market.get("close_time"),
            })
            await self.tg.send_trade_alert({**trade, "note": f"Resting @ {no_ask*100:.0f}c"})
        else:
            self._no_liquidity_cache[ticker] = time.time()

        return trade

    async def _place_no_limit_order(self, market: dict, size_usd: float,
                                     tier: str, bid_price: float) -> dict:
        ticker = market["ticker"]

        existing = await self.db.get_open_order_for_market(ticker, "no")
        if existing:
            return {"status": "skipped", "reason": "No limit order already resting"}

        no_price_cents = int(bid_price * 100)
        yes_price_cents = 100 - no_price_cents
        if yes_price_cents < 1 or yes_price_cents > 99:
            return {"status": "skipped", "reason": f"price out of range"}

        count = max(1, int(size_usd / bid_price))

        if self.config.dry_run:
            logger.info("[DRY RUN] No limit tier %s: %s @ %.1fc, %d contracts",
                        tier, market["question"][:60], bid_price * 100, count)
            return {"status": "dry_run", "intended_price": bid_price, "count": count}

        client_order_id = str(uuid.uuid4())
        try:
            result = await self.kalshi.place_order(
                ticker=ticker,
                side="no",
                action="buy",
                count=count,
                yes_price_cents=yes_price_cents,
                client_order_id=client_order_id,
            )
        except Exception as e:
            logger.error("No limit order failed for %s: %s", ticker, e)
            return {"status": "error", "reason": str(e)}

        if result is None:
            return {"status": "error", "reason": "place_order returned None"}

        order = result.get("order", {})
        order_id = order.get("order_id", "")

        await self.db.insert_open_order({
            "order_id": order_id,
            "ticker": ticker,
            "side": "no",
            "order_type": f"no_limit_tier_{tier}",
            "price": bid_price,
            "count": count,
            "question": market.get("question", ""),
            "city_date": market.get("city_date", ""),
            "close_time": market.get("close_time"),
        })

        trade = {
            "ticker": ticker,
            "type": f"no_limit_tier_{tier}",
            "side": "no",
            "action": "buy",
            "intended_price": bid_price,
            "count": 0,
            "cost_usd": 0,
            "status": "resting",
            "question": market.get("question", ""),
            "close_time": market.get("close_time"),
            "city_date": market.get("city_date", ""),
            "order_id": order_id,
        }
        await self.db.log_trade(trade)
        await self.tg.send_trade_alert({**trade, "note": f"No limit resting @ {bid_price*100:.0f}c"})
        return trade

    async def poll_open_orders(self) -> list[dict]:
        open_orders = await self.db.get_open_orders()
        if not open_orders:
            return []

        fills = []
        for oo in open_orders:
            order_id = oo["order_id"]
            try:
                result = await self.kalshi.get_order_status(order_id)
            except Exception as e:
                logger.warning("Failed to poll order %s: %s", order_id, e)
                continue

            if result is None:
                continue

            api_status = (result.get("status", "") or "").lower()
            filled_count = int(result.get("count", 0)) if api_status in ("executed", "filled") else 0

            if api_status in ("executed", "filled") or filled_count > 0:
                fill_cost = filled_count * float(oo["price"])
                await self.db.update_open_order(order_id, "filled", filled_count)

                await self.db.upsert_position({
                    "ticker": oo["ticker"],
                    "event_ticker": "",
                    "question": oo.get("question"),
                    "no_contracts": filled_count,
                    "no_cost": fill_cost,
                    "entry_price_no": float(oo["price"]),
                    "city_date": oo.get("city_date", ""),
                    "close_time": oo.get("close_time"),
                })

                trade = {
                    "ticker": oo["ticker"],
                    "type": oo["order_type"],
                    "side": "no",
                    "action": "buy",
                    "intended_price": float(oo["price"]),
                    "count": filled_count,
                    "cost_usd": fill_cost,
                    "status": "matched",
                    "question": oo.get("question"),
                    "close_time": oo.get("close_time"),
                    "city_date": oo.get("city_date", ""),
                    "order_id": order_id,
                }
                await self.db.log_trade(trade)
                await self.tg.send_trade_alert({**trade, "note": f"Limit FILLED @ {float(oo['price'])*100:.0f}c"})
                fills.append({"order_id": order_id, "count": filled_count, "cost": fill_cost})

            elif api_status in ("cancelled", "expired", "canceled"):
                await self.db.update_open_order(order_id, api_status, 0)

        return fills

    async def cancel_market_orders(self, ticker: str):
        open_orders = await self.db.get_open_orders()
        for oo in open_orders:
            if oo["ticker"] == ticker:
                try:
                    await self.kalshi.cancel_order(oo["order_id"])
                except Exception as e:
                    logger.warning("Failed to cancel order %s: %s", oo["order_id"], e)
                await self.db.update_open_order(oo["order_id"], "cancelled")
        await self.db.cancel_orders_for_market(ticker)

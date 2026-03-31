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

        # Calculate order: buying NO at no_ask price
        no_price_cents = int(no_ask * 100)
        if no_price_cents < 1 or no_price_cents > 99:
            return {"status": "skipped", "reason": f"no_price_cents {no_price_cents} out of range"}
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
                no_price_cents=no_price_cents,
                time_in_force="immediate_or_cancel",
                client_order_id=client_order_id,
            )
        except Exception as e:
            logger.error("No buy exception for %s: %s", ticker, e)
            self._no_liquidity_cache[ticker] = time.time()
            return {"status": "error", "reason": str(e)}

        if result is None:
            self._no_liquidity_cache[ticker] = time.time()
            return {"status": "error", "reason": "place_order returned None"}

        # Parse response using proper API fields
        parsed = KalshiClient.parse_order_response(result)
        order_id = parsed["order_id"]
        status = parsed["status"]
        filled_count = parsed["fill_count"]

        # Actual fill cost from API (taker + maker costs)
        fill_cost = parsed["taker_fill_cost"] + parsed["maker_fill_cost"]
        total_fees = parsed["taker_fees"] + parsed["maker_fees"]

        # Fallback: estimate cost if API didn't return it
        if fill_cost == 0 and filled_count > 0:
            fill_cost = filled_count * no_ask

        final_status = "matched" if filled_count > 0 else status
        actual_fill_price = fill_cost / filled_count if filled_count > 0 else no_ask

        trade = {
            "ticker": ticker,
            "type": f"no_buy_tier_{tier}",
            "side": "no",
            "action": "buy",
            "intended_price": no_ask,
            "fill_price": actual_fill_price,
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
                "entry_price_no": actual_fill_price,
                "city_date": market.get("city_date", ""),
                "close_time": market.get("close_time"),
            })
            await self.tg.send_trade_alert(trade)
            if total_fees > 0:
                logger.info("Fees on %s: $%.4f", ticker, total_fees)
        else:
            # IOC order got no fill
            self._no_liquidity_cache[ticker] = time.time()
            logger.info("IOC no fill for %s (status=%s)", ticker, status)

        return trade

    async def _place_no_limit_order(self, market: dict, size_usd: float,
                                     tier: str, bid_price: float) -> dict:
        """Place a resting NO limit order (GTC) below the ask."""
        ticker = market["ticker"]

        existing = await self.db.get_open_order_for_market(ticker, "no")
        if existing:
            return {"status": "skipped", "reason": "No limit order already resting"}

        no_price_cents = int(bid_price * 100)
        if no_price_cents < 1 or no_price_cents > 99:
            return {"status": "skipped", "reason": f"no_price_cents {no_price_cents} out of range"}

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
                no_price_cents=no_price_cents,
                # No time_in_force → defaults to GTC for resting limit orders
                client_order_id=client_order_id,
            )
        except Exception as e:
            logger.error("No limit order failed for %s: %s", ticker, e)
            return {"status": "error", "reason": str(e)}

        if result is None:
            return {"status": "error", "reason": "place_order returned None"}

        parsed = KalshiClient.parse_order_response(result)
        order_id = parsed["order_id"]
        status = parsed["status"]

        # Even a limit order might partially fill immediately
        filled_count = parsed["fill_count"]
        fill_cost = parsed["taker_fill_cost"] + parsed["maker_fill_cost"]
        remaining = parsed["remaining_count"]

        if filled_count > 0:
            actual_fill_price = fill_cost / filled_count if fill_cost > 0 else bid_price
            await self.db.upsert_position({
                "ticker": ticker,
                "event_ticker": market.get("event_ticker", ""),
                "question": market.get("question", ""),
                "no_contracts": filled_count,
                "no_cost": fill_cost if fill_cost > 0 else filled_count * bid_price,
                "entry_price_no": actual_fill_price,
                "city_date": market.get("city_date", ""),
                "close_time": market.get("close_time"),
            })

        # If there's a remaining resting portion, track it
        if remaining > 0 and status == "resting":
            await self.db.insert_open_order({
                "order_id": order_id,
                "ticker": ticker,
                "side": "no",
                "order_type": f"no_limit_tier_{tier}",
                "price": bid_price,
                "count": remaining,
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
            "fill_price": (fill_cost / filled_count) if filled_count > 0 and fill_cost > 0 else None,
            "count": filled_count,
            "cost_usd": fill_cost,
            "status": "matched" if filled_count > 0 and remaining == 0 else
                      "partial" if filled_count > 0 and remaining > 0 else "resting",
            "question": market.get("question", ""),
            "close_time": market.get("close_time"),
            "city_date": market.get("city_date", ""),
            "order_id": order_id,
        }
        await self.db.log_trade(trade)

        note = f"Filled {filled_count}, resting {remaining}" if filled_count > 0 else f"Resting {remaining} @ {bid_price*100:.0f}c"
        await self.tg.send_trade_alert({**trade, "note": note})
        return trade

    # ------------------------------------------------------------------
    # WS fill processing (real-time)
    # ------------------------------------------------------------------

    async def process_ws_fill(self, fill: dict) -> dict | None:
        """Process a fill notification from the WS fill channel.

        On receiving a fill, we fetch the full order status via REST
        to get accurate totals (handles partial fills correctly).
        Returns fill info dict or None if not our tracked order.
        """
        order_id = fill.get("order_id", "")
        ticker = fill.get("market_ticker", "")
        if not order_id:
            return None

        # Check if this is one of our tracked resting orders
        open_orders = await self.db.get_open_orders()
        matching_order = None
        for oo in open_orders:
            if oo["order_id"] == order_id:
                matching_order = oo
                break

        if not matching_order:
            # Not a tracked limit order — could be an IOC fill (already handled inline)
            logger.debug("WS fill for untracked order %s on %s", order_id[:8], ticker)
            return None

        # Fetch full order status for accurate fill totals
        try:
            result = await self.kalshi.get_order_status(order_id)
        except Exception as e:
            logger.warning("Failed to fetch order after WS fill %s: %s", order_id, e)
            return None

        if result is None:
            return None

        parsed = KalshiClient.parse_order_response({"order": result})
        api_status = parsed["status"]
        filled_count = parsed["fill_count"]
        fill_cost = parsed["taker_fill_cost"] + parsed["maker_fill_cost"]
        remaining = parsed["remaining_count"]

        if filled_count == 0:
            return None

        oo = matching_order
        actual_price = fill_cost / filled_count if fill_cost > 0 else float(oo["price"])

        # Mark order as filled/partial
        if api_status == "executed" or remaining == 0:
            await self.db.update_open_order(order_id, "filled", filled_count)
        else:
            # Partial fill — order still resting
            await self.db.update_open_order(order_id, "partial", filled_count)

        await self.db.upsert_position({
            "ticker": oo["ticker"],
            "event_ticker": "",
            "question": oo.get("question"),
            "no_contracts": filled_count,
            "no_cost": fill_cost if fill_cost > 0 else filled_count * float(oo["price"]),
            "entry_price_no": actual_price,
            "city_date": oo.get("city_date", ""),
            "close_time": oo.get("close_time"),
        })

        trade = {
            "ticker": oo["ticker"],
            "type": oo["order_type"],
            "side": "no",
            "action": "buy",
            "intended_price": float(oo["price"]),
            "fill_price": actual_price,
            "count": filled_count,
            "cost_usd": fill_cost if fill_cost > 0 else filled_count * float(oo["price"]),
            "status": "matched" if remaining == 0 else "partial",
            "question": oo.get("question"),
            "close_time": oo.get("close_time"),
            "city_date": oo.get("city_date", ""),
            "order_id": order_id,
        }
        await self.db.log_trade(trade)

        status_str = "FILLED" if remaining == 0 else f"PARTIAL ({filled_count} filled, {remaining} left)"
        await self.tg.send_trade_alert({**trade, "note": f"WS: Limit {status_str} @ {actual_price*100:.1f}c"})

        logger.info("WS fill processed: %s %s %dx @ %.1fc (%s)",
                     oo["ticker"], status_str, filled_count, actual_price * 100, order_id[:8])

        return {"order_id": order_id, "ticker": oo["ticker"],
                "count": filled_count, "cost": fill_cost}

    # ------------------------------------------------------------------
    # REST polling fallback (less frequent)
    # ------------------------------------------------------------------

    async def poll_open_orders(self) -> list[dict]:
        """Fallback: poll resting orders via REST for fills.
        Only needed when WS is down or as periodic safety check."""
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

            parsed = KalshiClient.parse_order_response({"order": result})
            api_status = parsed["status"]
            filled_count = parsed["fill_count"]
            fill_cost = parsed["taker_fill_cost"] + parsed["maker_fill_cost"]

            if filled_count > 0 and api_status == "executed":
                actual_price = fill_cost / filled_count if fill_cost > 0 else float(oo["price"])

                await self.db.update_open_order(order_id, "filled", filled_count)

                await self.db.upsert_position({
                    "ticker": oo["ticker"],
                    "event_ticker": "",
                    "question": oo.get("question"),
                    "no_contracts": filled_count,
                    "no_cost": fill_cost if fill_cost > 0 else filled_count * float(oo["price"]),
                    "entry_price_no": actual_price,
                    "city_date": oo.get("city_date", ""),
                    "close_time": oo.get("close_time"),
                })

                trade = {
                    "ticker": oo["ticker"],
                    "type": oo["order_type"],
                    "side": "no",
                    "action": "buy",
                    "intended_price": float(oo["price"]),
                    "fill_price": actual_price,
                    "count": filled_count,
                    "cost_usd": fill_cost if fill_cost > 0 else filled_count * float(oo["price"]),
                    "status": "matched",
                    "question": oo.get("question"),
                    "close_time": oo.get("close_time"),
                    "city_date": oo.get("city_date", ""),
                    "order_id": order_id,
                }
                await self.db.log_trade(trade)
                await self.tg.send_trade_alert({**trade, "note": f"REST poll: FILLED {filled_count}x @ {actual_price*100:.1f}c"})
                fills.append({"order_id": order_id, "ticker": oo["ticker"],
                              "count": filled_count, "cost": fill_cost})

            elif api_status == "canceled":
                await self.db.update_open_order(order_id, "cancelled", 0)

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

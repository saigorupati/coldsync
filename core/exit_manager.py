"""
Exit Manager — monitors open positions and executes staged exits
based on price change from entry.

Replaces heatsync's hedge mechanism with simpler scale-out rules:
  Stage 1 (loss >= 10%): sell 33% of NO position
  Stage 2 (loss >= 20%): sell 66% of remaining
  Stage 3 (loss >= 30%): sell 100% (full exit)
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from services.kalshi_rest import KalshiClient

logger = logging.getLogger("coldsync.exit_mgr")


@dataclass
class MonitoredPosition:
    ticker: str
    entry_price_no: float      # price we paid per NO contract (e.g., 0.95)
    no_contracts: int           # current count of NO contracts held
    original_contracts: int     # original count (for tracking partial exits)
    city_date: str
    exit_stage: int = 0        # 0=none, 1=cut_some, 2=cut_heavy, 3=full_exit


class ExitManager:
    def __init__(self, config, kalshi: KalshiClient, ws, db, discord,
                 price_queue: asyncio.Queue):
        self.config = config
        self.kalshi = kalshi
        self.ws = ws
        self.db = db
        self.tg = discord
        self.price_queue = price_queue
        self._positions: dict[str, MonitoredPosition] = {}
        self._last_poll_prices: dict[str, float] = {}  # fallback cache

    async def register_position(self, ticker: str, entry_price: float,
                                 count: int, city_date: str, exit_stage: int = 0):
        self._positions[ticker] = MonitoredPosition(
            ticker=ticker,
            entry_price_no=entry_price,
            no_contracts=count,
            original_contracts=count,
            city_date=city_date,
            exit_stage=exit_stage,
        )
        # Subscribe to WS orderbook updates and mark for price_queue monitoring
        await self.ws.subscribe_orderbook([ticker])
        self.ws.monitor_ticker(ticker)
        logger.info("Exit monitor: registered %s (%d contracts @ %.1fc, stage=%d)",
                     ticker, count, entry_price * 100, exit_stage)

    async def unregister_position(self, ticker: str):
        if ticker in self._positions:
            del self._positions[ticker]
            self.ws.unmonitor_ticker(ticker)
            await self.ws.unsubscribe_orderbook([ticker])
            logger.info("Exit monitor: unregistered %s", ticker)

    async def run(self):
        """Main loop: read from price_queue and evaluate exits.
        Falls back to REST polling when WS is down."""
        while True:
            try:
                # Try to get WS price updates with timeout
                try:
                    ticker, yes_bid, yes_ask = await asyncio.wait_for(
                        self.price_queue.get(),
                        timeout=self.config.exit_check_interval_seconds,
                    )
                    if ticker in self._positions:
                        if yes_ask is not None:
                            current_no_price = 1.0 - yes_ask
                            await self._evaluate_exit(self._positions[ticker], current_no_price)
                        elif yes_bid is None and yes_ask is None:
                            # Delta update without prices — fetch from REST
                            await self._poll_single(ticker)
                except asyncio.TimeoutError:
                    # Fallback: poll all monitored positions via REST
                    if not self.ws.is_connected and self._positions:
                        await self._poll_all()

            except asyncio.CancelledError:
                logger.info("Exit manager task cancelled")
                break
            except Exception as e:
                logger.error("Exit manager error: %s", e, exc_info=True)
                await asyncio.sleep(5)

    async def _poll_all(self):
        for ticker in list(self._positions.keys()):
            await self._poll_single(ticker)

    async def _poll_single(self, ticker: str):
        if ticker not in self._positions:
            return
        ob = await self.kalshi.get_orderbook(ticker)
        if ob is None:
            return
        yes_ask = ob.best_ask()
        if yes_ask is not None:
            current_no_price = 1.0 - yes_ask
            await self._evaluate_exit(self._positions[ticker], current_no_price)

    async def _evaluate_exit(self, pos: MonitoredPosition, current_no_price: float):
        """Evaluate whether to exit based on loss from entry.

        entry_no_price: 0.95 (paid 95c per NO contract)
        current_no_price: 0.85 (we'd get 85c selling now)
        loss_pct: (0.95 - 0.85) / 0.95 = 10.5%
        """
        if pos.no_contracts <= 0:
            return

        loss_pct = (pos.entry_price_no - current_no_price) / pos.entry_price_no

        if loss_pct >= 0.30 and pos.exit_stage < 3 and self.config.exit_down_30_full_exit:
            await self._execute_exit(pos, 1.0, 3, "full_exit_30pct", current_no_price)
        elif loss_pct >= 0.20 and pos.exit_stage < 2:
            await self._execute_exit(pos, self.config.exit_down_20_cut_pct, 2, "cut_heavy_20pct", current_no_price)
        elif loss_pct >= 0.10 and pos.exit_stage < 1:
            await self._execute_exit(pos, self.config.exit_down_10_cut_pct, 1, "cut_some_10pct", current_no_price)

    async def _execute_exit(self, pos: MonitoredPosition, cut_fraction: float,
                             stage: int, reason: str, current_no_price: float):
        sell_count = max(1, int(pos.no_contracts * cut_fraction))
        if sell_count > pos.no_contracts:
            sell_count = pos.no_contracts

        ticker = pos.ticker
        logger.info("Exit %s stage %d: selling %d/%d contracts (reason: %s, current_no=%.1fc)",
                     ticker, stage, sell_count, pos.no_contracts, reason, current_no_price * 100)

        if self.config.dry_run:
            logger.info("[DRY RUN] Would sell %d NO contracts of %s", sell_count, ticker)
            pos.exit_stage = stage
            return

        # To sell NO contracts: action="sell", side="no"
        # We want our NO sell to execute, so we set a slightly aggressive NO price.
        # For urgent exits (stage 3), accept a worse price.
        # no_price is what the buyer pays for NO — we need to set it LOW enough
        # to match existing bids.
        if stage == 3:
            # Full exit: sell at a steep discount to guarantee fill
            sell_no_price_cents = max(1, int(current_no_price * 100) - 5)
        elif stage == 2:
            # Heavy cut: sell slightly below current
            sell_no_price_cents = max(1, int(current_no_price * 100) - 3)
        else:
            # Stage 1: sell near current price
            sell_no_price_cents = max(1, int(current_no_price * 100) - 2)

        try:
            result = await self.kalshi.place_order(
                ticker=ticker,
                side="no",
                action="sell",
                count=sell_count,
                no_price_cents=sell_no_price_cents,
                time_in_force="immediate_or_cancel",
                client_order_id=str(uuid.uuid4()),
            )
        except Exception as e:
            logger.error("Exit order failed for %s: %s", ticker, e)
            return

        if result is None:
            logger.error("Exit order returned None for %s", ticker)
            return

        parsed = KalshiClient.parse_order_response(result)
        filled_count = parsed["fill_count"]
        fill_cost = parsed["taker_fill_cost"] + parsed["maker_fill_cost"]
        total_fees = parsed["taker_fees"] + parsed["maker_fees"]

        if filled_count == 0:
            logger.warning("Exit order got no fills for %s (stage %d, no_price=%dc)",
                          ticker, stage, sell_no_price_cents)
            # Don't advance stage if we couldn't sell — will retry next evaluation
            return

        # IMPORTANT: For SELL NO orders, taker_fill_cost reports the YES-side cost
        # (what the counterparty paid for YES), NOT our NO proceeds.
        # Our NO proceeds = filled_count * $1.00 - yes_side_cost = $1.00 - fill_cost
        # Then subtract fees.
        no_proceeds = filled_count * 1.0 - fill_cost  # $1 per contract minus YES cost
        sell_proceeds_after_fees = no_proceeds - total_fees
        actual_sell_price = sell_proceeds_after_fees / filled_count if filled_count > 0 else current_no_price
        realized_pnl = (actual_sell_price - pos.entry_price_no) * filled_count

        logger.info("Exit fill %s: %d contracts, yes_cost=$%.4f, no_proceeds=$%.4f, fees=$%.4f, sell_price=%.1fc",
                     ticker, filled_count, fill_cost, no_proceeds, total_fees, actual_sell_price * 100)
        cost_removed = pos.entry_price_no * filled_count

        # Update position
        pos.no_contracts -= filled_count
        pos.exit_stage = stage

        # Log to database
        await self.db.log_exit(
            ticker=ticker,
            stage=stage,
            contracts_sold=filled_count,
            sell_price=actual_sell_price,
            entry_price=pos.entry_price_no,
            pnl=realized_pnl,
            reason=reason,
        )
        await self.db.update_position_after_exit(ticker, filled_count, cost_removed)

        # Log trade
        trade = {
            "ticker": ticker,
            "type": f"exit_{reason}",
            "side": "no",
            "action": "sell",
            "intended_price": current_no_price,
            "fill_price": actual_sell_price,
            "count": filled_count,
            "cost_usd": abs(realized_pnl),
            "status": "matched",
            "question": "",
            "city_date": pos.city_date,
            "order_id": parsed["order_id"],
        }
        await self.db.log_trade(trade)

        # Discord alert
        await self.tg.send_exit_alert(
            ticker=ticker,
            stage=stage,
            contracts_sold=filled_count,
            sell_price=actual_sell_price,
            entry_price=pos.entry_price_no,
            pnl=realized_pnl,
            reason=reason,
        )

        # If fully exited, unregister
        if pos.no_contracts <= 0:
            await self.unregister_position(ticker)

        logger.info("Exit %s stage %d complete: sold %d @ %.1fc, remaining %d, pnl=$%.2f",
                     ticker, stage, filled_count, actual_sell_price * 100,
                     pos.no_contracts, realized_pnl)

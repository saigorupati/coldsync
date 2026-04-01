"""
Exit Manager — monitors open positions and executes staged exits
based on price change from entry.

Replaces heatsync's hedge mechanism with simpler scale-out rules:
  Stage 1 (loss >= 20%): sell 33% of NO position
  Stage 2 (loss >= 30%): sell 66% of remaining
  Stage 3 (loss >= 40%): sell 100% (full exit)
  Stage 4 (loss >= 50%): YES flip — buy YES contracts to try to recoup
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
    exit_stage: int = 0        # 0=none, 1=cut_some, 2=cut_heavy, 3=full_exit, 4=yes_flip
    _exiting: bool = field(default=False, repr=False)  # lock to prevent double exits


@dataclass
class YesFlipPosition:
    """Lightweight tracker for YES flip positions — only needs stop-loss."""
    ticker: str
    entry_price_yes: float
    yes_contracts: int
    city_date: str
    no_loss_amount: float      # the NO loss that triggered this flip
    _exiting: bool = field(default=False, repr=False)


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
        self._yes_positions: dict[str, YesFlipPosition] = {}
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

    async def register_yes_position(self, ticker: str, entry_price: float,
                                     count: int, city_date: str, no_loss: float):
        self._yes_positions[ticker] = YesFlipPosition(
            ticker=ticker,
            entry_price_yes=entry_price,
            yes_contracts=count,
            city_date=city_date,
            no_loss_amount=no_loss,
        )
        # Ensure we're subscribed to orderbook for this ticker
        if ticker not in self._positions:
            await self.ws.subscribe_orderbook([ticker])
            self.ws.monitor_ticker(ticker)
        logger.info("YES flip monitor: registered %s (%d YES contracts @ %.1fc, no_loss=$%.2f)",
                     ticker, count, entry_price * 100, no_loss)

    async def unregister_position(self, ticker: str):
        if ticker in self._positions:
            del self._positions[ticker]
            # Only unsub if no YES position also watching this ticker
            if ticker not in self._yes_positions:
                self.ws.unmonitor_ticker(ticker)
                await self.ws.unsubscribe_orderbook([ticker])
            logger.info("Exit monitor: unregistered %s", ticker)

    async def unregister_yes_position(self, ticker: str):
        if ticker in self._yes_positions:
            del self._yes_positions[ticker]
            # Only unsub if no NO position also watching this ticker
            if ticker not in self._positions:
                self.ws.unmonitor_ticker(ticker)
                await self.ws.unsubscribe_orderbook([ticker])
            logger.info("YES flip monitor: unregistered %s", ticker)

    async def run(self):
        """Main loop: read from price_queue and evaluate exits.
        Falls back to REST polling when WS is down."""
        # Immediate check on startup — catch positions that moved while bot was down
        if self._positions or self._yes_positions:
            logger.info("Exit manager: initial poll of %d NO + %d YES positions",
                        len(self._positions), len(self._yes_positions))
            await self._poll_all()

        poll_counter = 0
        while True:
            try:
                # Try to get WS price updates with timeout
                try:
                    ticker, yes_bid, yes_ask = await asyncio.wait_for(
                        self.price_queue.get(),
                        timeout=self.config.exit_check_interval_seconds,
                    )
                    if yes_ask is not None:
                        current_no_price = 1.0 - yes_ask
                        current_yes_price = yes_ask

                        if ticker in self._positions:
                            await self._evaluate_exit(self._positions[ticker], current_no_price)

                        if ticker in self._yes_positions:
                            await self._evaluate_yes_exit(self._yes_positions[ticker], current_yes_price)

                    elif yes_bid is None and yes_ask is None:
                        # Delta update without prices — fetch from REST
                        await self._poll_single(ticker)

                except asyncio.TimeoutError:
                    pass

                # Periodic REST poll every 60s as safety net
                # (catches illiquid markets with no WS updates)
                poll_counter += 1
                if poll_counter >= (60 / max(1, self.config.exit_check_interval_seconds)):
                    poll_counter = 0
                    if self._positions or self._yes_positions:
                        await self._poll_all()

            except asyncio.CancelledError:
                logger.info("Exit manager task cancelled")
                break
            except Exception as e:
                logger.error("Exit manager error: %s", e, exc_info=True)
                await asyncio.sleep(5)

    async def _poll_all(self):
        all_tickers = set(self._positions.keys()) | set(self._yes_positions.keys())
        for ticker in list(all_tickers):
            await self._poll_single(ticker)

    async def _poll_single(self, ticker: str):
        ob = await self.kalshi.get_orderbook(ticker)
        if ob is None:
            return
        yes_ask = ob.best_ask()
        if yes_ask is not None:
            current_no_price = 1.0 - yes_ask
            current_yes_price = yes_ask

            if ticker in self._positions:
                await self._evaluate_exit(self._positions[ticker], current_no_price)
            if ticker in self._yes_positions:
                await self._evaluate_yes_exit(self._yes_positions[ticker], current_yes_price)

    # ------------------------------------------------------------------
    # NO position exit evaluation (stages 1-3)
    # ------------------------------------------------------------------

    async def _evaluate_exit(self, pos: MonitoredPosition, current_no_price: float):
        """Evaluate whether to exit based on loss from entry.

        entry_no_price: 0.95 (paid 95c per NO contract)
        current_no_price: 0.85 (we'd get 85c selling now)
        loss_pct: (0.95 - 0.85) / 0.95 = 10.5%
        """
        if pos.no_contracts <= 0 or pos._exiting:
            return

        loss_pct = (pos.entry_price_no - current_no_price) / pos.entry_price_no

        if loss_pct >= 0.40 and pos.exit_stage < 3 and self.config.exit_down_30_full_exit:
            await self._execute_exit(pos, 1.0, 3, "full_exit_40pct", current_no_price)
        elif loss_pct >= 0.30 and pos.exit_stage < 2:
            await self._execute_exit(pos, self.config.exit_down_20_cut_pct, 2, "cut_heavy_30pct", current_no_price)
        elif loss_pct >= 0.20 and pos.exit_stage < 1:
            await self._execute_exit(pos, self.config.exit_down_10_cut_pct, 1, "cut_some_20pct", current_no_price)

    async def _execute_exit(self, pos: MonitoredPosition, cut_fraction: float,
                             stage: int, reason: str, current_no_price: float):
        pos._exiting = True
        try:
            await self.__do_exit(pos, cut_fraction, stage, reason, current_no_price)
        finally:
            pos._exiting = False

    async def __do_exit(self, pos: MonitoredPosition, cut_fraction: float,
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

        # If fully exited, mark as resolved and check YES flip
        if pos.no_contracts <= 0:
            # Sum up all exit P&L for this ticker (all stages)
            total_exit_pnl = await self.db.get_total_exit_pnl(ticker)
            await self.db.resolve_position(ticker, "Exited", 0.0, total_exit_pnl)
            logger.info("Position %s fully exited and resolved: total_exit_pnl=$%.2f",
                         ticker, total_exit_pnl)

            # Stage 4: YES flip — buy YES to try to recoup if loss is severe enough
            loss_pct = (pos.entry_price_no - current_no_price) / pos.entry_price_no
            if (self.config.yes_flip_enabled
                    and loss_pct >= self.config.yes_flip_trigger_loss_pct
                    and ticker not in self._yes_positions):
                await self._execute_yes_flip(pos, total_exit_pnl, current_no_price)

            await self.unregister_position(ticker)

        logger.info("Exit %s stage %d complete: sold %d @ %.1fc, remaining %d, pnl=$%.2f",
                     ticker, stage, filled_count, actual_sell_price * 100,
                     pos.no_contracts, realized_pnl)

    # ------------------------------------------------------------------
    # Stage 4: YES Flip — buy YES after full NO exit
    # ------------------------------------------------------------------

    async def _execute_yes_flip(self, pos: MonitoredPosition,
                                 no_loss: float, current_no_price: float):
        """Buy YES contracts to try to recoup losses after full NO exit.

        Sizing: spend up to yes_flip_loss_fraction of the NO loss, capped at yes_flip_max_usd.
        Only buy if YES ask is below yes_flip_max_yes_price.
        """
        ticker = pos.ticker
        loss_amount = abs(no_loss)  # no_loss is negative

        if loss_amount < 0.01:
            logger.info("YES flip: skipping %s, loss too small ($%.2f)", ticker, loss_amount)
            return

        # Check existing YES flip
        existing = await self.db.get_yes_position(ticker)
        if existing and not existing["resolved"]:
            logger.info("YES flip: already have active YES position for %s", ticker)
            return

        # Check global YES exposure cap
        yes_exposure = await self.db.total_yes_exposure()
        if yes_exposure >= self.config.yes_flip_max_total_usd:
            logger.info("YES flip: global cap reached ($%.2f >= $%.2f), skipping %s",
                        yes_exposure, self.config.yes_flip_max_total_usd, ticker)
            return

        # Calculate spend
        spend = min(
            loss_amount * self.config.yes_flip_loss_fraction,
            self.config.yes_flip_max_usd,
            self.config.yes_flip_max_total_usd - yes_exposure,  # respect global cap
        )

        if spend < 0.05:
            logger.info("YES flip: spend too small ($%.2f) for %s", spend, ticker)
            return

        # Get current YES ask price from orderbook
        ob = await self.kalshi.get_orderbook(ticker)
        if ob is None:
            logger.warning("YES flip: no orderbook for %s", ticker)
            return

        yes_ask = ob.best_ask()
        if yes_ask is None:
            logger.info("YES flip: no YES ask available for %s", ticker)
            return

        if yes_ask > self.config.yes_flip_max_yes_price:
            logger.info("YES flip: skipping %s, yes_ask=%.1fc > max %.1fc",
                        ticker, yes_ask * 100, self.config.yes_flip_max_yes_price * 100)
            return

        yes_price_cents = int(yes_ask * 100)
        count = max(1, int(spend / yes_ask))

        logger.info("YES flip %s: buying %d YES @ %dc (spend=$%.2f, no_loss=$%.2f)",
                     ticker, count, yes_price_cents, spend, no_loss)

        if self.config.dry_run:
            logger.info("[DRY RUN] Would buy %d YES contracts of %s @ %dc",
                        count, ticker, yes_price_cents)
            return

        try:
            result = await self.kalshi.place_order(
                ticker=ticker,
                side="yes",
                action="buy",
                count=count,
                yes_price_cents=yes_price_cents,
                time_in_force="immediate_or_cancel",
                client_order_id=str(uuid.uuid4()),
            )
        except Exception as e:
            logger.error("YES flip order failed for %s: %s", ticker, e)
            return

        if result is None:
            logger.error("YES flip order returned None for %s", ticker)
            return

        parsed = KalshiClient.parse_order_response(result)
        filled_count = parsed["fill_count"]
        fill_cost = parsed["taker_fill_cost"] + parsed["maker_fill_cost"]
        total_fees = parsed["taker_fees"] + parsed["maker_fees"]

        if filled_count == 0:
            logger.warning("YES flip: no fills for %s (yes_price=%dc)", ticker, yes_price_cents)
            return

        fill_cost_with_fees = fill_cost + total_fees
        actual_fill_price = fill_cost_with_fees / filled_count if filled_count > 0 else yes_ask

        logger.info("YES flip filled %s: %d contracts @ %.1fc, cost=$%.4f, fees=$%.4f",
                     ticker, filled_count, actual_fill_price * 100, fill_cost, total_fees)

        # Record YES position in DB
        await self.db.upsert_yes_position({
            "ticker": ticker,
            "origin_ticker": ticker,
            "event_ticker": "",
            "question": "",
            "yes_contracts": filled_count,
            "yes_cost": fill_cost_with_fees,
            "entry_price_yes": actual_fill_price,
            "city_date": pos.city_date,
            "close_time": None,
            "no_loss_amount": no_loss,
        })

        # Log trade
        trade = {
            "ticker": ticker,
            "type": "yes_flip",
            "side": "yes",
            "action": "buy",
            "intended_price": yes_ask,
            "fill_price": actual_fill_price,
            "count": filled_count,
            "cost_usd": fill_cost_with_fees,
            "status": "matched",
            "question": "",
            "city_date": pos.city_date,
            "order_id": parsed["order_id"],
        }
        await self.db.log_trade(trade)

        # Register for monitoring (stop-loss)
        await self.register_yes_position(
            ticker, actual_fill_price, filled_count,
            pos.city_date, no_loss,
        )

        # Discord alert
        await self.tg.send_yes_flip_alert(
            ticker=ticker,
            yes_contracts=filled_count,
            yes_price=actual_fill_price,
            no_loss=no_loss,
            spend=fill_cost_with_fees,
            city_date=pos.city_date,
        )

    # ------------------------------------------------------------------
    # YES position exit evaluation (stop-loss only)
    # ------------------------------------------------------------------

    async def _evaluate_yes_exit(self, ypos: YesFlipPosition, current_yes_price: float):
        """Simple stop-loss for YES flip positions.
        If YES price drops 60% from entry, sell to cut losses."""
        if ypos.yes_contracts <= 0 or ypos._exiting:
            return

        loss_pct = (ypos.entry_price_yes - current_yes_price) / ypos.entry_price_yes

        if loss_pct >= self.config.yes_flip_stop_loss_pct:
            await self._execute_yes_stop_loss(ypos, current_yes_price)

    async def _execute_yes_stop_loss(self, ypos: YesFlipPosition, current_yes_price: float):
        """Sell all YES contracts as stop-loss."""
        ypos._exiting = True
        try:
            await self.__do_yes_stop_loss(ypos, current_yes_price)
        finally:
            ypos._exiting = False

    async def __do_yes_stop_loss(self, ypos: YesFlipPosition, current_yes_price: float):
        ticker = ypos.ticker
        sell_count = ypos.yes_contracts

        logger.info("YES stop-loss %s: selling %d YES contracts (current_yes=%.1fc, entry=%.1fc)",
                     ticker, sell_count, current_yes_price * 100, ypos.entry_price_yes * 100)

        if self.config.dry_run:
            logger.info("[DRY RUN] Would sell %d YES contracts of %s", sell_count, ticker)
            return

        # Sell YES: action="sell", side="yes"
        # Set aggressive (low) price to guarantee fill
        sell_yes_price_cents = max(1, int(current_yes_price * 100) - 3)

        try:
            result = await self.kalshi.place_order(
                ticker=ticker,
                side="yes",
                action="sell",
                count=sell_count,
                yes_price_cents=sell_yes_price_cents,
                time_in_force="immediate_or_cancel",
                client_order_id=str(uuid.uuid4()),
            )
        except Exception as e:
            logger.error("YES stop-loss order failed for %s: %s", ticker, e)
            return

        if result is None:
            logger.error("YES stop-loss order returned None for %s", ticker)
            return

        parsed = KalshiClient.parse_order_response(result)
        filled_count = parsed["fill_count"]
        fill_cost = parsed["taker_fill_cost"] + parsed["maker_fill_cost"]
        total_fees = parsed["taker_fees"] + parsed["maker_fees"]

        if filled_count == 0:
            logger.warning("YES stop-loss: no fills for %s", ticker)
            return

        # For SELL YES: taker_fill_cost is the YES cost (what buyer pays for YES)
        # Our YES proceeds = fill_cost (the buyer's YES cost = our proceeds)
        # Wait — same pattern as SELL NO: for SELL YES, taker_fill_cost is the
        # NO-side cost. Our YES proceeds = filled_count * $1.00 - fill_cost
        yes_proceeds = filled_count * 1.0 - fill_cost
        sell_proceeds_after_fees = yes_proceeds - total_fees
        actual_sell_price = sell_proceeds_after_fees / filled_count if filled_count > 0 else current_yes_price
        realized_pnl = (actual_sell_price - ypos.entry_price_yes) * filled_count

        cost_removed = ypos.entry_price_yes * filled_count

        logger.info("YES stop-loss filled %s: %d @ %.1fc, pnl=$%.2f",
                     ticker, filled_count, actual_sell_price * 100, realized_pnl)

        # Update DB
        await self.db.update_yes_position_after_exit(ticker, filled_count, cost_removed)

        # Log exit
        await self.db.log_exit(
            ticker=ticker,
            stage=4,
            contracts_sold=filled_count,
            sell_price=actual_sell_price,
            entry_price=ypos.entry_price_yes,
            pnl=realized_pnl,
            reason="yes_flip_stop_loss",
        )

        # Log trade
        trade = {
            "ticker": ticker,
            "type": "exit_yes_flip_stop_loss",
            "side": "yes",
            "action": "sell",
            "intended_price": current_yes_price,
            "fill_price": actual_sell_price,
            "count": filled_count,
            "cost_usd": abs(realized_pnl),
            "status": "matched",
            "question": "",
            "city_date": ypos.city_date,
            "order_id": parsed["order_id"],
        }
        await self.db.log_trade(trade)

        # Discord alert
        await self.tg.send_exit_alert(
            ticker=ticker,
            stage=4,
            contracts_sold=filled_count,
            sell_price=actual_sell_price,
            entry_price=ypos.entry_price_yes,
            pnl=realized_pnl,
            reason="yes_flip_stop_loss",
        )

        # Update in-memory and resolve if fully sold
        ypos.yes_contracts -= filled_count
        if ypos.yes_contracts <= 0:
            await self.db.resolve_yes_position(ticker, "Stopped", 0.0, realized_pnl)
            await self.unregister_yes_position(ticker)
            logger.info("YES flip %s fully stopped out: pnl=$%.2f", ticker, realized_pnl)

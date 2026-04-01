import logging

from services.kalshi_rest import KalshiClient

logger = logging.getLogger("coldsync.positions")


class PositionManager:
    def __init__(self, config, kalshi: KalshiClient, db, discord, ws=None):
        self.config = config
        self.kalshi = kalshi
        self.db = db
        self.tg = discord
        self.ws = ws

    async def wallet_balance(self) -> float:
        free = await self.free_cash()
        unresolved = await self.db.total_unresolved_exposure()
        bal = free + unresolved
        if bal == 0 and self.config.dry_run:
            state = await self.db.get_risk_state()
            bal = float(state.get("starting_balance", 0)) if state else 0
        return bal

    async def free_cash(self) -> float:
        bal = await self.kalshi.get_balance()
        if bal == 0 and self.config.dry_run:
            state = await self.db.get_risk_state()
            bal = float(state.get("starting_balance", 0)) if state else 0
        return bal

    async def total_unresolved(self) -> float:
        no_exposure = await self.db.total_unresolved_exposure()
        yes_exposure = await self.db.total_yes_exposure()
        return no_exposure + yes_exposure

    async def market_exposure(self, ticker: str) -> float:
        return await self.db.get_market_exposure(ticker)

    async def city_date_exposure(self, city_date: str) -> float:
        return await self.db.get_city_date_exposure(city_date)

    async def check_resolutions(self) -> list[dict]:
        """Check Kalshi positions for settled markets.

        Uses WS position_data for instant detection when available,
        falls back to REST market status polling.
        Kalshi settles automatically — no redemption needed.
        """
        resolved = []
        open_positions = await self.db.get_open_positions()

        # Skip positions with 0 contracts — these are fully exited
        # and should already be resolved by exit_manager
        open_positions = [p for p in open_positions if int(p.get("no_contracts", 0)) > 0]

        # Batch check: first try WS position data (instant, no API calls)
        ws_checked = set()
        if self.ws and hasattr(self.ws, 'position_data'):
            for pos in open_positions:
                ticker = pos["ticker"]
                ws_pos = self.ws.position_data.get(ticker)
                if ws_pos and ws_pos["position"] == 0:
                    # Position went to 0 = settled by Kalshi
                    ws_checked.add(ticker)
                    no_contracts = int(pos.get("no_contracts", 0))
                    cost = float(pos.get("no_cost", 0))

                    # Use Kalshi's realized P&L if available
                    kalshi_rpnl = ws_pos.get("realized_pnl_dollars", 0)

                    # Determine outcome from P&L: if we profited, NO won
                    # (we hold NO, so profit = No outcome, loss = Yes outcome)
                    if kalshi_rpnl > 0 or (kalshi_rpnl == 0 and cost < no_contracts):
                        outcome = "No"
                        payout = float(no_contracts)
                    else:
                        outcome = "Yes"
                        payout = 0.0

                    # Use our tracked cost for P&L (includes fees)
                    # Also include P&L from any partial exits
                    resolution_pnl = payout - cost
                    exit_pnl = await self.db.get_total_exit_pnl(ticker)
                    pnl = resolution_pnl + exit_pnl

                    logger.info("WS settlement detected: %s → %s, resolution_pnl=$%.2f, exit_pnl=$%.2f, total_pnl=$%.2f (kalshi_rpnl=$%.2f)",
                                ticker, outcome, resolution_pnl, exit_pnl, pnl, kalshi_rpnl)

                    await self.db.resolve_position(ticker, outcome, payout, pnl)
                    resolved.append({
                        "ticker": ticker,
                        "question": pos.get("question", ""),
                        "outcome": outcome,
                        "payout": payout,
                        "cost": cost,
                        "pnl": pnl,
                        "city_date": pos.get("city_date", ""),
                    })
                    await self.tg.send_resolution_alert(pos, outcome, payout, pnl)

                    # Clean up WS data
                    self.ws.position_data.pop(ticker, None)

        # REST fallback for positions not detected via WS
        for pos in open_positions:
            ticker = pos["ticker"]
            if ticker in ws_checked:
                continue

            market = await self.kalshi.get_market(ticker)
            if market is None:
                continue

            status = (market.get("status", "") or "").lower()
            if status not in ("closed", "settled"):
                continue

            result = market.get("result", "")
            if result not in ("yes", "no"):
                logger.info("Market %s closed but no result yet: %s", ticker, status)
                continue

            outcome = result.capitalize()  # "Yes" or "No"
            no_contracts = int(pos.get("no_contracts", 0))
            cost = float(pos.get("no_cost", 0))

            # If outcome is "No", our NO contracts pay out $1 each
            payout = float(no_contracts) if outcome == "No" else 0.0
            # Include P&L from any partial exits
            resolution_pnl = payout - cost
            exit_pnl = await self.db.get_total_exit_pnl(ticker)
            pnl = resolution_pnl + exit_pnl

            logger.info("REST settlement: %s → %s, resolution_pnl=$%.2f, exit_pnl=$%.2f, total_pnl=$%.2f",
                        ticker, outcome, resolution_pnl, exit_pnl, pnl)

            await self.db.resolve_position(ticker, outcome, payout, pnl)

            resolved.append({
                "ticker": ticker,
                "question": pos.get("question", ""),
                "outcome": outcome,
                "payout": payout,
                "cost": cost,
                "pnl": pnl,
                "city_date": pos.get("city_date", ""),
            })

            await self.tg.send_resolution_alert(pos, outcome, payout, pnl)

        # --- YES flip position resolutions ---
        yes_positions = await self.db.get_open_yes_positions()
        yes_positions = [p for p in yes_positions if int(p.get("yes_contracts", 0)) > 0]

        for ypos in yes_positions:
            ticker = ypos["ticker"]

            # Check WS first
            if self.ws and hasattr(self.ws, 'position_data'):
                ws_pos = self.ws.position_data.get(ticker)
                if ws_pos and ws_pos["position"] == 0:
                    yes_contracts = int(ypos.get("yes_contracts", 0))
                    cost = float(ypos.get("yes_cost", 0))
                    kalshi_rpnl = ws_pos.get("realized_pnl_dollars", 0)

                    if kalshi_rpnl > 0:
                        outcome = "Yes"
                        payout = float(yes_contracts)  # $1 each
                    else:
                        outcome = "No"
                        payout = 0.0

                    pnl = payout - cost
                    logger.info("WS YES settlement: %s → %s, pnl=$%.2f", ticker, outcome, pnl)

                    await self.db.resolve_yes_position(ticker, outcome, payout, pnl)
                    resolved.append({
                        "ticker": ticker,
                        "question": ypos.get("question", ""),
                        "outcome": f"YES Flip: {outcome}",
                        "payout": payout,
                        "cost": cost,
                        "pnl": pnl,
                        "city_date": ypos.get("city_date", ""),
                    })
                    await self.tg.send_yes_resolution_alert(ypos, outcome, payout, pnl)
                    self.ws.position_data.pop(ticker, None)
                    continue

            # REST fallback
            market = await self.kalshi.get_market(ticker)
            if market is None:
                continue

            status = (market.get("status", "") or "").lower()
            if status not in ("closed", "settled"):
                continue

            result = market.get("result", "")
            if result not in ("yes", "no"):
                continue

            outcome = result.capitalize()
            yes_contracts = int(ypos.get("yes_contracts", 0))
            cost = float(ypos.get("yes_cost", 0))

            # YES contracts pay $1 if outcome is Yes, $0 if No
            payout = float(yes_contracts) if outcome == "Yes" else 0.0
            pnl = payout - cost

            logger.info("REST YES settlement: %s → %s, pnl=$%.2f", ticker, outcome, pnl)

            await self.db.resolve_yes_position(ticker, outcome, payout, pnl)
            resolved.append({
                "ticker": ticker,
                "question": ypos.get("question", ""),
                "outcome": f"YES Flip: {outcome}",
                "payout": payout,
                "cost": cost,
                "pnl": pnl,
                "city_date": ypos.get("city_date", ""),
            })
            await self.tg.send_yes_resolution_alert(ypos, outcome, payout, pnl)

        return resolved

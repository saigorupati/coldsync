import asyncpg
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("coldsync.database")


def _to_dt(val) -> datetime | None:
    """Convert a string timestamp to datetime, or pass through if already datetime/None."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        # Handle 'Z' suffix for Python 3.11+ fromisoformat
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    return val


class Database:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(self.dsn, min_size=2, max_size=10)

    async def close(self):
        if self.pool:
            await self.pool.close()

    # --- Trade logging ---
    async def log_trade(self, trade: dict):
        await self.pool.execute("""
            INSERT INTO trades (ticker, type, side, action, intended_price,
                                fill_price, count, cost_usd, status, question,
                                close_time, city_date, order_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
        """, trade["ticker"], trade["type"], trade["side"], trade.get("action"),
            trade["intended_price"], trade.get("fill_price"), trade.get("count", 0),
            trade.get("cost_usd", 0), trade["status"], trade.get("question"),
            _to_dt(trade.get("close_time")), trade.get("city_date"), trade.get("order_id"))

    # --- Position tracking ---
    async def upsert_position(self, pos: dict):
        await self.pool.execute("""
            INSERT INTO positions (ticker, event_ticker, question,
                                   no_contracts, no_cost, entry_price_no,
                                   city_date, close_time)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            ON CONFLICT (ticker) DO UPDATE SET
                no_contracts = positions.no_contracts + EXCLUDED.no_contracts,
                no_cost = positions.no_cost + EXCLUDED.no_cost,
                entry_price_no = (positions.no_cost + EXCLUDED.no_cost)
                    / NULLIF(positions.no_contracts + EXCLUDED.no_contracts, 0)
        """, pos["ticker"], pos.get("event_ticker"), pos.get("question"),
            pos.get("no_contracts", 0), pos.get("no_cost", 0),
            pos.get("entry_price_no", 0),
            pos.get("city_date"), _to_dt(pos.get("close_time")))

    async def get_open_positions(self) -> list[dict]:
        rows = await self.pool.fetch(
            "SELECT * FROM positions WHERE resolved = FALSE"
        )
        return [dict(r) for r in rows]

    async def resolve_position(self, ticker: str, outcome: str, payout: float, pnl: float):
        await self.pool.execute("""
            UPDATE positions SET resolved = TRUE, resolved_outcome = $2,
                                 payout = $3, pnl = $4, resolved_at = NOW()
            WHERE ticker = $1
        """, ticker, outcome, payout, pnl)

    async def get_total_exit_pnl(self, ticker: str) -> float:
        """Get sum of realized P&L from all exits for a ticker."""
        val = await self.pool.fetchval(
            "SELECT COALESCE(SUM(realized_pnl), 0) FROM exits WHERE ticker = $1",
            ticker
        )
        return float(val)

    async def get_positions_needing_monitoring(self) -> list[dict]:
        rows = await self.pool.fetch("""
            SELECT * FROM positions
            WHERE resolved = FALSE AND no_contracts > 0
        """)
        return [dict(r) for r in rows]

    # --- Exit tracking ---
    async def log_exit(self, ticker: str, stage: int, contracts_sold: int,
                       sell_price: float, entry_price: float, pnl: float, reason: str):
        await self.pool.execute("""
            INSERT INTO exits (ticker, stage, contracts_sold, sell_price,
                               entry_price, realized_pnl, reason)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
        """, ticker, stage, contracts_sold, sell_price, entry_price, pnl, reason)

    async def update_position_after_exit(self, ticker: str, contracts_removed: int, cost_removed: float):
        await self.pool.execute("""
            UPDATE positions
            SET no_contracts = no_contracts - $2,
                no_cost = no_cost - $3,
                exit_stage = (SELECT COALESCE(MAX(stage), 0) FROM exits WHERE exits.ticker = $1)
            WHERE ticker = $1
        """, ticker, contracts_removed, cost_removed)

    # --- Exposure queries ---
    async def total_unresolved_exposure(self) -> float:
        val = await self.pool.fetchval(
            "SELECT COALESCE(SUM(no_cost), 0) FROM positions WHERE resolved = FALSE"
        )
        return float(val)

    async def get_market_exposure(self, ticker: str) -> float:
        val = await self.pool.fetchval(
            "SELECT COALESCE(no_cost, 0) FROM positions WHERE ticker = $1",
            ticker
        )
        return float(val or 0)

    async def get_city_date_exposure(self, city_date: str) -> float:
        val = await self.pool.fetchval(
            "SELECT COALESCE(SUM(no_cost), 0) FROM positions WHERE city_date = $1 AND resolved = FALSE",
            city_date
        )
        return float(val)

    # --- Risk state ---
    async def count_resolution_losses_since(self, since: datetime) -> int:
        val = await self.pool.fetchval(
            """SELECT COUNT(*) FROM positions
               WHERE resolved = TRUE AND resolved_at >= $1
               AND no_contracts > 0 AND resolved_outcome = 'Yes'""",
            since
        )
        return int(val)

    async def sum_resolution_losses_since(self, since: datetime) -> float:
        val = await self.pool.fetchval(
            """SELECT COALESCE(SUM(pnl), 0) FROM positions
               WHERE resolved = TRUE AND resolved_at >= $1
               AND no_contracts > 0 AND resolved_outcome = 'Yes'""",
            since
        )
        return float(val)

    async def count_city_losses_today(self, city_date: str) -> int:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        val = await self.pool.fetchval(
            """SELECT COUNT(*) FROM positions
               WHERE city_date = $1 AND resolved = TRUE AND resolved_at >= $2
               AND no_contracts > 0 AND resolved_outcome = 'Yes'""",
            city_date, today
        )
        return int(val)

    async def days_since_start(self) -> int:
        val = await self.pool.fetchval(
            "SELECT EXTRACT(DAY FROM NOW() - started_at)::int FROM risk_state WHERE id = 1"
        )
        return int(val or 0)

    async def no_bet_win_rate(self) -> float:
        row = await self.pool.fetchrow("""
            SELECT COUNT(*) FILTER (WHERE resolved_outcome = 'No') AS wins,
                   COUNT(*) AS total
            FROM positions
            WHERE resolved = TRUE AND resolved_outcome IN ('No', 'Yes')
        """)
        if row and row["total"] > 0:
            return row["wins"] / row["total"]
        return 0.0

    async def total_pnl(self) -> float:
        # positions.pnl already includes exit P&L for resolved positions
        resolution_pnl = await self.pool.fetchval(
            "SELECT COALESCE(SUM(pnl), 0) FROM positions WHERE resolved = TRUE"
        )
        # Only add exit P&L for positions still open (partial exits not yet resolved)
        open_exit_pnl = await self.pool.fetchval("""
            SELECT COALESCE(SUM(e.realized_pnl), 0)
            FROM exits e
            JOIN positions p ON e.ticker = p.ticker
            WHERE p.resolved = FALSE
        """)
        return float(resolution_pnl) + float(open_exit_pnl)

    async def starting_balance(self) -> float:
        val = await self.pool.fetchval(
            "SELECT starting_balance FROM risk_state WHERE id = 1"
        )
        return float(val or 500)

    async def consecutive_profitable_days(self) -> int:
        rows = await self.pool.fetch(
            "SELECT date, daily_pnl FROM daily_pnl ORDER BY date DESC LIMIT 30"
        )
        streak = 0
        for r in rows:
            if r["daily_pnl"] and r["daily_pnl"] > 0:
                streak += 1
            else:
                break
        return streak

    # --- Frozen cities ---
    async def freeze_city(self, city_date: str, until: datetime):
        await self.pool.execute("""
            INSERT INTO frozen_cities (city_date, frozen_until) VALUES ($1, $2)
            ON CONFLICT (city_date) DO UPDATE SET frozen_until = $2
        """, city_date, until)

    async def get_frozen_cities(self) -> dict[str, datetime]:
        rows = await self.pool.fetch(
            "SELECT city_date, frozen_until FROM frozen_cities WHERE frozen_until > NOW()"
        )
        return {r["city_date"]: r["frozen_until"] for r in rows}

    # --- Daily summary ---
    async def compile_daily_summary(self, wallet_balance: float, free_cash: float,
                                     unresolved: float, phase: int,
                                     scale_factor: float) -> dict:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        trades_count = await self.pool.fetchval(
            "SELECT COUNT(*) FROM trades WHERE timestamp >= $1", today
        )
        exits_count = await self.pool.fetchval(
            "SELECT COUNT(*) FROM exits WHERE timestamp >= $1", today
        )

        resolution_row = await self.pool.fetchrow("""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE pnl >= 0) AS wins,
                   COUNT(*) FILTER (WHERE pnl < 0) AS losses,
                   COALESCE(SUM(pnl), 0) AS daily_pnl
            FROM positions
            WHERE resolved = TRUE AND resolved_at >= $1
        """, today)

        total_pnl = await self.total_pnl()
        no_win_rate = await self.no_bet_win_rate()

        wins = int(resolution_row["wins"]) if resolution_row else 0
        losses = int(resolution_row["losses"]) if resolution_row else 0
        daily_pnl = float(resolution_row["daily_pnl"]) if resolution_row else 0.0
        resolutions_count = int(resolution_row["total"]) if resolution_row else 0

        unresolved_pct = unresolved / wallet_balance if wallet_balance > 0 else 0

        return {
            "date": today.date(),
            "phase": phase,
            "scale_factor": scale_factor,
            "wallet_balance": wallet_balance,
            "free_cash": free_cash,
            "unresolved": unresolved,
            "unresolved_pct": unresolved_pct,
            "trades_today": int(trades_count),
            "exits_today": int(exits_count),
            "resolutions_today": resolutions_count,
            "wins": wins,
            "losses": losses,
            "daily_pnl": daily_pnl,
            "total_pnl": total_pnl,
            "no_win_rate": no_win_rate,
            "trades_count": int(trades_count),
            "exits_count": int(exits_count),
            "resolutions_count": resolutions_count,
            "cumulative_pnl": total_pnl,
        }

    async def save_daily_pnl(self, data: dict):
        await self.pool.execute("""
            INSERT INTO daily_pnl (date, wallet_balance, free_cash, unresolved,
                                   trades_count, exits_count, resolutions_count,
                                   wins, losses, daily_pnl, cumulative_pnl, no_win_rate, phase)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            ON CONFLICT (date) DO UPDATE SET
                wallet_balance = EXCLUDED.wallet_balance, free_cash = EXCLUDED.free_cash,
                unresolved = EXCLUDED.unresolved, trades_count = EXCLUDED.trades_count,
                exits_count = EXCLUDED.exits_count, resolutions_count = EXCLUDED.resolutions_count,
                wins = EXCLUDED.wins, losses = EXCLUDED.losses, daily_pnl = EXCLUDED.daily_pnl,
                cumulative_pnl = EXCLUDED.cumulative_pnl, no_win_rate = EXCLUDED.no_win_rate,
                phase = EXCLUDED.phase
        """, data["date"], data["wallet_balance"], data["free_cash"], data["unresolved"],
            data["trades_count"], data["exits_count"], data["resolutions_count"],
            data["wins"], data["losses"], data["daily_pnl"], data["cumulative_pnl"],
            data["no_win_rate"], data["phase"])

    # --- Scan result logging (upsert — one row per ticker) ---
    async def log_scan_result(self, row: dict):
        await self.pool.execute("""
            INSERT INTO scan_results (ticker, city_date, question, yes_price, no_price,
                                      prob_sum, excess, neighbor_ratio, com_distance, score,
                                      tier, order_size, spread, volume, skip_reason, scanned_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15, NOW())
            ON CONFLICT (ticker) DO UPDATE SET
                city_date = EXCLUDED.city_date,
                question = EXCLUDED.question,
                yes_price = EXCLUDED.yes_price,
                no_price = EXCLUDED.no_price,
                prob_sum = EXCLUDED.prob_sum,
                excess = EXCLUDED.excess,
                neighbor_ratio = EXCLUDED.neighbor_ratio,
                com_distance = EXCLUDED.com_distance,
                score = EXCLUDED.score,
                tier = EXCLUDED.tier,
                order_size = EXCLUDED.order_size,
                spread = EXCLUDED.spread,
                volume = EXCLUDED.volume,
                skip_reason = EXCLUDED.skip_reason,
                scanned_at = NOW()
        """, row["ticker"], row["city_date"], row.get("question"),
            row.get("yes_price"), row.get("no_price"),
            row.get("prob_sum"), row.get("excess"),
            row.get("neighbor_ratio"), row.get("com_distance"), row.get("score"),
            row.get("tier"), row.get("order_size"),
            row.get("spread"), row.get("volume"), row.get("skip_reason", ""))

    async def cleanup_old_scans(self, keep_hours: int = 24, active_cities: list[str] | None = None):
        """Remove stale tickers (resolved markets, yesterday's data, non-active cities)."""
        await self.pool.execute(
            "DELETE FROM scan_results WHERE scanned_at < NOW() - make_interval(hours => $1)",
            keep_hours
        )
        # Also remove rows for cities no longer in the whitelist
        if active_cities:
            city_prefixes = [f"{c}|" for c in active_cities]
            await self.pool.execute("""
                DELETE FROM scan_results
                WHERE NOT EXISTS (
                    SELECT 1 FROM unnest($1::text[]) AS prefix
                    WHERE city_date LIKE prefix || '%'
                )
            """, city_prefixes)

    async def get_risk_state(self) -> dict | None:
        row = await self.pool.fetchrow("SELECT * FROM risk_state WHERE id = 1")
        return dict(row) if row else None

    async def update_balances(self, wallet_balance: float, free_cash: float):
        await self.pool.execute(
            "UPDATE risk_state SET wallet_balance = $1, free_cash = $2, balance_updated_at = NOW() WHERE id = 1",
            wallet_balance, free_cash,
        )

    # --- Open orders ---
    async def insert_open_order(self, order: dict):
        await self.pool.execute("""
            INSERT INTO open_orders (order_id, ticker, side, order_type,
                                     price, count, status, question, city_date, close_time)
            VALUES ($1,$2,$3,$4,$5,$6,'open',$7,$8,$9)
            ON CONFLICT (order_id) DO NOTHING
        """, order["order_id"], order["ticker"],
            order["side"], order["order_type"], order["price"], order["count"],
            order.get("question"), order.get("city_date"), order.get("close_time"))

    async def get_open_orders(self) -> list[dict]:
        rows = await self.pool.fetch(
            "SELECT * FROM open_orders WHERE status = 'open' ORDER BY created_at"
        )
        return [dict(r) for r in rows]

    async def get_open_order_for_market(self, ticker: str, side: str) -> dict | None:
        row = await self.pool.fetchrow(
            "SELECT * FROM open_orders WHERE ticker = $1 AND side = $2 AND status = 'open'",
            ticker, side
        )
        return dict(row) if row else None

    async def update_open_order(self, order_id: str, status: str, filled_count: int = 0):
        await self.pool.execute("""
            UPDATE open_orders SET status = $2, filled_count = $3, updated_at = NOW()
            WHERE order_id = $1
        """, order_id, status, filled_count)

    async def cancel_orders_for_market(self, ticker: str):
        await self.pool.execute("""
            UPDATE open_orders SET status = 'cancelled', updated_at = NOW()
            WHERE ticker = $1 AND status = 'open'
        """, ticker)

    # --- YES flip positions ---
    async def upsert_yes_position(self, pos: dict):
        await self.pool.execute("""
            INSERT INTO yes_positions (ticker, origin_ticker, event_ticker, question,
                                       yes_contracts, yes_cost, entry_price_yes,
                                       city_date, close_time, no_loss_amount)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (ticker) DO UPDATE SET
                yes_contracts = yes_positions.yes_contracts + EXCLUDED.yes_contracts,
                yes_cost = yes_positions.yes_cost + EXCLUDED.yes_cost,
                entry_price_yes = (yes_positions.yes_cost + EXCLUDED.yes_cost)
                    / NULLIF(yes_positions.yes_contracts + EXCLUDED.yes_contracts, 0)
        """, pos["ticker"], pos["origin_ticker"], pos.get("event_ticker"),
            pos.get("question"), pos.get("yes_contracts", 0),
            pos.get("yes_cost", 0), pos.get("entry_price_yes", 0),
            pos.get("city_date"), _to_dt(pos.get("close_time")),
            pos.get("no_loss_amount", 0))

    async def get_open_yes_positions(self) -> list[dict]:
        rows = await self.pool.fetch(
            "SELECT * FROM yes_positions WHERE resolved = FALSE"
        )
        return [dict(r) for r in rows]

    async def get_yes_position(self, ticker: str) -> dict | None:
        row = await self.pool.fetchrow(
            "SELECT * FROM yes_positions WHERE ticker = $1", ticker
        )
        return dict(row) if row else None

    async def resolve_yes_position(self, ticker: str, outcome: str, payout: float, pnl: float):
        await self.pool.execute("""
            UPDATE yes_positions SET resolved = TRUE, resolved_outcome = $2,
                                     payout = $3, pnl = $4, resolved_at = NOW()
            WHERE ticker = $1
        """, ticker, outcome, payout, pnl)

    async def update_yes_position_after_exit(self, ticker: str, contracts_removed: int, cost_removed: float):
        await self.pool.execute("""
            UPDATE yes_positions
            SET yes_contracts = yes_contracts - $2,
                yes_cost = yes_cost - $3
            WHERE ticker = $1
        """, ticker, contracts_removed, cost_removed)

    async def total_yes_exposure(self) -> float:
        val = await self.pool.fetchval(
            "SELECT COALESCE(SUM(yes_cost), 0) FROM yes_positions WHERE resolved = FALSE"
        )
        return float(val)

    # --- Cleanup ---
    async def fix_orphaned_exits(self):
        """Fix positions that were fully exited but have incorrect data.
        Handles two cases:
        1. Positions with no_contracts=0 and resolved=FALSE (never marked resolved)
        2. Positions with no_contracts=0 and resolved=TRUE but pnl=0 when exits exist
           (resolved by check_resolutions before exit P&L was included)
        """
        # Case 1: Unresolved but fully exited
        unresolved = await self.pool.fetch("""
            SELECT ticker FROM positions
            WHERE resolved = FALSE AND no_contracts <= 0
        """)
        for row in unresolved:
            ticker = row["ticker"]
            exit_pnl = await self.get_total_exit_pnl(ticker)
            await self.resolve_position(ticker, "Exited", 0.0, exit_pnl)
            logger.info("Fixed unresolved fully-exited position: %s (exit_pnl=$%.2f)", ticker, exit_pnl)

        # Case 2: Resolved with 0 contracts but P&L doesn't include exit P&L
        # These were resolved by check_resolutions() before the fix,
        # so pnl only reflects (payout - remaining_cost) = $0 for fully-exited positions
        mismatched = await self.pool.fetch("""
            SELECT p.ticker, p.pnl, p.resolved_outcome,
                   COALESCE(SUM(e.realized_pnl), 0) AS exit_pnl
            FROM positions p
            LEFT JOIN exits e ON e.ticker = p.ticker
            WHERE p.resolved = TRUE AND p.no_contracts <= 0
            GROUP BY p.ticker, p.pnl, p.resolved_outcome
            HAVING COALESCE(SUM(e.realized_pnl), 0) != 0
               AND (p.pnl IS NULL OR ABS(p.pnl - COALESCE(SUM(e.realized_pnl), 0)) > 0.001)
        """)
        for row in mismatched:
            ticker = row["ticker"]
            exit_pnl = float(row["exit_pnl"])
            old_pnl = float(row["pnl"] or 0)
            # For fully-exited positions, total P&L = exit P&L (payout was 0 since we sold everything)
            await self.pool.execute("""
                UPDATE positions SET pnl = $2, resolved_outcome = 'Exited'
                WHERE ticker = $1
            """, ticker, exit_pnl)
            logger.info("Fixed resolved fully-exited position: %s (old_pnl=$%.2f → exit_pnl=$%.2f)",
                        ticker, old_pnl, exit_pnl)

        total = len(unresolved) + len(mismatched)
        if total:
            logger.info("Fixed %d orphaned/mismatched fully-exited positions", total)

    # --- Init risk state ---
    async def init_risk_state(self, starting_balance: float):
        await self.pool.execute("""
            INSERT INTO risk_state (id, phase, scale_factor, starting_balance)
            VALUES (1, 1, 1.0, $1)
            ON CONFLICT (id) DO NOTHING
        """, starting_balance)

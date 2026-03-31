import asyncio
import logging
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

from config.settings import StrategyConfig
from services.database import Database
from services.kalshi_rest import KalshiClient
from services.kalshi_ws import KalshiWebSocket
from services.discord_bot import DiscordService
from core.scanner import LadderScanner
from core.distortion import DistortionScorer
from core.tier import Tier, TierClassifier
from core.sizer import PositionSizer
from core.executor import OrderExecutor
from core.positions import PositionManager
from core.risk import RiskController
from core.exit_manager import ExitManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("coldsync.kalshi").setLevel(logging.DEBUG)
logging.getLogger("coldsync.scanner").setLevel(logging.DEBUG)
logger = logging.getLogger("coldsync")


async def fill_monitor(fill_queue: asyncio.Queue, executor: OrderExecutor,
                       exit_mgr: ExitManager):
    """Background task: process WS fill notifications in real-time."""
    while True:
        try:
            fill = await fill_queue.get()
            result = await executor.process_ws_fill(fill)
            if result:
                ticker = result.get("ticker", "")
                # Register newly filled limit orders with exit manager
                if ticker:
                    # Check if already monitored (avoid duplicates)
                    pos = await executor.db.get_open_positions()
                    for p in pos:
                        if p["ticker"] == ticker and ticker not in exit_mgr._positions:
                            await exit_mgr.register_position(
                                ticker=ticker,
                                entry_price=float(p["entry_price_no"]),
                                count=int(p["no_contracts"]),
                                city_date=p.get("city_date", ""),
                                exit_stage=int(p.get("exit_stage", 0)),
                            )
                            break
        except asyncio.CancelledError:
            logger.info("Fill monitor task cancelled")
            break
        except Exception as e:
            logger.error("Fill monitor error: %s", e, exc_info=True)
            await asyncio.sleep(1)


async def main():
    load_dotenv("config/.env")

    config = StrategyConfig(
        dry_run=os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes"),
        kalshi_env=os.environ.get("KALSHI_ENV", "demo"),
    )

    # Init database
    db = Database(os.environ["DATABASE_URL"])
    await db.connect()
    await db.init_risk_state(float(os.environ.get("STARTING_BALANCE", "500")))

    # Init Kalshi client
    kalshi = KalshiClient(
        key_id=os.environ.get("KALSHI_KEY_ID", ""),
        private_key_pem=os.environ.get("KALSHI_PRIVATE_KEY_PEM", ""),
        env=config.kalshi_env,
    )

    discord = DiscordService(webhook_url=os.environ.get("DISCORD_WEBHOOK_URL", ""))

    # Init WebSocket + queues
    price_queue: asyncio.Queue = asyncio.Queue()
    fill_queue: asyncio.Queue = asyncio.Queue()
    ws = KalshiWebSocket(
        key_id=os.environ.get("KALSHI_KEY_ID", ""),
        private_key_pem=os.environ.get("KALSHI_PRIVATE_KEY_PEM", ""),
        env=config.kalshi_env,
        price_queue=price_queue,
        fill_queue=fill_queue,
    )

    # Init core components
    scanner = LadderScanner(config, kalshi, ws=ws)
    distortion = DistortionScorer(config)
    tier_classifier = TierClassifier(config)
    sizer = PositionSizer(config)
    executor = OrderExecutor(config, kalshi, db, discord)
    positions = PositionManager(config, kalshi, db, discord)
    risk = RiskController(config, db)
    exit_mgr = ExitManager(config, kalshi, ws, db, discord, price_queue)

    # Load persisted state
    await risk.load_frozen_cities()

    # Reconcile DB with Kalshi portfolio on startup (prevents duplicate orders)
    kalshi_positions = await kalshi.get_positions()
    db_positions = await db.get_open_positions()
    db_tickers = {p["ticker"]: p for p in db_positions}

    for kp in kalshi_positions:
        ticker = kp.get("ticker", "")
        kalshi_count = abs(int(float(kp.get("position_fp", "0"))))
        kalshi_cost = float(kp.get("total_traded_dollars", "0"))
        if kalshi_count == 0:
            continue

        db_pos = db_tickers.get(ticker)
        if db_pos is None:
            # Position exists on Kalshi but not in DB — insert it
            entry_price = kalshi_cost / kalshi_count if kalshi_count > 0 else 0
            logger.warning("Reconcile: adding missing position %s (%d contracts, $%.2f)",
                           ticker, kalshi_count, kalshi_cost)
            await db.upsert_position({
                "ticker": ticker,
                "no_contracts": kalshi_count,
                "no_cost": kalshi_cost,
                "entry_price_no": entry_price,
            })
        elif int(db_pos["no_contracts"]) != kalshi_count:
            # Count mismatch — update DB to match Kalshi (source of truth)
            logger.warning("Reconcile: %s DB has %d contracts, Kalshi has %d — fixing",
                           ticker, int(db_pos["no_contracts"]), kalshi_count)
            await db.pool.execute(
                "UPDATE positions SET no_contracts = $1, no_cost = $2, entry_price_no = $3 WHERE ticker = $4",
                kalshi_count, kalshi_cost,
                kalshi_cost / kalshi_count if kalshi_count > 0 else 0,
                ticker,
            )

    # Reload monitored positions for exit manager (survive restarts)
    open_pos = await db.get_positions_needing_monitoring()
    for p in open_pos:
        await exit_mgr.register_position(
            p["ticker"], float(p["entry_price_no"]),
            int(p["no_contracts"]), p.get("city_date", ""),
            int(p.get("exit_stage", 0)),
        )

    start_bal = await positions.wallet_balance()
    logger.info("Bot started. Phase %d. Balance: $%.2f. Dry run: %s. Env: %s",
                config.phase, start_bal, config.dry_run, config.kalshi_env)
    await discord.send_bot_started(start_bal, config.phase, config.dry_run)

    # Spawn background tasks
    ws_task = asyncio.create_task(ws.run())
    exit_task = asyncio.create_task(exit_mgr.run())
    fill_task = asyncio.create_task(fill_monitor(fill_queue, executor, exit_mgr))

    last_daily_summary = None
    last_resolution_hour = None
    scan_count = 0

    try:
        while True:
            try:
                if risk.is_paused:
                    logger.info("Risk pause active. Waiting.")
                    await asyncio.sleep(config.scan_interval_seconds)
                    continue

                scan_count += 1

                # 0. REST poll for fills as safety fallback (every 5 scans ≈ 5 min)
                #    Primary fill detection is via WS fill_monitor task above
                if scan_count % 5 == 0:
                    order_fills = await executor.poll_open_orders()
                    if order_fills:
                        logger.info("REST fallback detected %d fill(s)", len(order_fills))
                        for fill in order_fills:
                            ticker = fill.get("ticker", "")
                            if ticker and ticker not in exit_mgr._positions:
                                pos_list = await db.get_open_positions()
                                for p in pos_list:
                                    if p["ticker"] == ticker:
                                        await exit_mgr.register_position(
                                            ticker=ticker,
                                            entry_price=float(p["entry_price_no"]),
                                            count=int(p["no_contracts"]),
                                            city_date=p.get("city_date", ""),
                                        )
                                        break

                # 1. Check resolutions (once per hour)
                current_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
                resolved = []
                if last_resolution_hour != current_hour:
                    resolved = await positions.check_resolutions()
                    wallet_bal = await positions.wallet_balance()
                    for r in resolved:
                        await risk.on_resolution(r["pnl"], r.get("city_date", ""), wallet_bal)
                        await executor.cancel_market_orders(r["ticker"])
                        await exit_mgr.unregister_position(r["ticker"])
                    last_resolution_hour = current_hour

                # 2. Check phase advancement
                old_phase = config.phase
                if await risk.check_phase_advancement():
                    await discord.send_phase_change(old_phase, config.phase)

                # 3. Scan ladders
                ladders = await scanner.scan()
                total_bins = sum(len(bins) for bins in ladders.values())
                logger.info("Scan #%d: %d ladders, %d bins", scan_count, len(ladders), total_bins)

                # 4. Score, classify, size, execute
                wallet_bal = await positions.wallet_balance()
                free = await positions.free_cash()
                total_unresolved = await positions.total_unresolved()

                await db.update_balances(wallet_bal, free)

                trades_this_scan = 0
                scan_market_exposure = {}

                for city_date, ladder in ladders.items():
                    if risk.is_city_frozen(city_date):
                        continue

                    city_exposure = await positions.city_date_exposure(city_date)
                    ladder_result = distortion.score_ladder(ladder)

                    for scored_bin in ladder_result["bins"]:
                        m = scored_bin["market"]
                        tier, skip_reason = tier_classifier.classify(
                            scored_bin, ladder_result, city_exposure, wallet_bal
                        )

                        ticker = m["ticker"]
                        market_exp = await positions.market_exposure(ticker) + scan_market_exposure.get(ticker, 0)
                        order_size = 0.0
                        if tier != Tier.SKIP:
                            is_limit = m.get("no_ask", m["no_price"]) > config.no_price_max
                            order_size = sizer.calculate(
                                tier, wallet_bal, free, market_exp,
                                city_exposure, total_unresolved,
                                m.get("depth_2c_usd", 0), risk.scale_factor,
                                limit_order=is_limit,
                            )

                        await db.log_scan_result({
                            "city_date": city_date,
                            "ticker": ticker,
                            "question": m.get("question", ""),
                            "yes_price": m.get("yes_price", 0),
                            "no_price": m.get("no_price", 0),
                            "prob_sum": ladder_result["prob_sum"],
                            "excess": ladder_result["excess"],
                            "neighbor_ratio": scored_bin["neighbor_ratio"],
                            "com_distance": scored_bin["com_distance"],
                            "score": scored_bin["score"],
                            "tier": tier.value if tier != Tier.SKIP else "SKIP",
                            "order_size": order_size,
                            "spread": m.get("spread", 0),
                            "volume": m.get("volume", 0),
                            "skip_reason": skip_reason,
                        })

                        if tier == Tier.SKIP or order_size <= 0:
                            continue

                        # Execute No buy
                        m["city_date"] = city_date
                        result = await executor.execute_no_buy(m, order_size, tier.value)

                        if result.get("status") == "matched":
                            trades_this_scan += 1
                            filled_cost = result.get("cost_usd", order_size)
                            free -= filled_cost
                            total_unresolved += filled_cost
                            city_exposure += filled_cost
                            scan_market_exposure[ticker] = scan_market_exposure.get(ticker, 0) + filled_cost

                            # Register with exit manager for price monitoring
                            await exit_mgr.register_position(
                                ticker=ticker,
                                entry_price=result.get("fill_price", result.get("intended_price", 0.95)),
                                count=result.get("count", 0),
                                city_date=city_date,
                            )

                # 5. Check scale-up
                await risk.check_scale_up()

                # 6. Daily summary
                now = datetime.now(timezone.utc)
                if now.hour == 0 and (last_daily_summary is None or last_daily_summary.date() < now.date()):
                    data = await db.compile_daily_summary(
                        wallet_balance=wallet_bal,
                        free_cash=free,
                        unresolved=total_unresolved,
                        phase=config.phase,
                        scale_factor=risk.scale_factor,
                    )
                    await discord.send_daily_summary(data)
                    await db.save_daily_pnl(data)
                    await db.cleanup_old_scans(keep_hours=48, active_cities=config.whitelisted_cities)
                    last_daily_summary = now

                # 7. Periodic scan_results cleanup (every 10 scans ≈ 10 min)
                if scan_count % 10 == 0:
                    await db.cleanup_old_scans(keep_hours=6, active_cities=config.whitelisted_cities)

                if trades_this_scan > 0:
                    logger.info("Scan #%d: %d trades, %d resolutions",
                                scan_count, trades_this_scan, len(resolved))

                await asyncio.sleep(config.scan_interval_seconds)

            except KeyboardInterrupt:
                logger.info("Shutting down")
                break
            except Exception as e:
                logger.error("Scan error: %s", e, exc_info=True)
                await discord.send_error(str(e))
                await asyncio.sleep(30)

    finally:
        logger.info("Cleaning up...")
        ws_task.cancel()
        exit_task.cancel()
        fill_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass
        try:
            await exit_task
        except asyncio.CancelledError:
            pass
        try:
            await fill_task
        except asyncio.CancelledError:
            pass
        await kalshi.close()
        await db.close()
        await discord.close()


if __name__ == "__main__":
    asyncio.run(main())

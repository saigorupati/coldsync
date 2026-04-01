"""Initialize the ColdSync PostgreSQL schema."""

import asyncio
import os
import asyncpg
from dotenv import load_dotenv

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    ticker TEXT PRIMARY KEY,
    event_ticker TEXT,
    question TEXT,
    no_contracts INTEGER DEFAULT 0,
    no_cost NUMERIC(12,4) DEFAULT 0,
    entry_price_no NUMERIC(8,4) DEFAULT 0,
    exit_stage INTEGER DEFAULT 0,
    city_date TEXT,
    close_time TIMESTAMPTZ,
    resolved BOOLEAN DEFAULT FALSE,
    resolved_outcome TEXT,
    payout NUMERIC(12,4),
    pnl NUMERIC(12,4),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    type TEXT,
    side TEXT,
    action TEXT,
    intended_price NUMERIC(8,4),
    fill_price NUMERIC(8,4),
    count INTEGER,
    cost_usd NUMERIC(12,4),
    status TEXT,
    question TEXT,
    close_time TIMESTAMPTZ,
    city_date TEXT,
    order_id TEXT,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS open_orders (
    order_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    side TEXT,
    order_type TEXT,
    price NUMERIC(8,4),
    count INTEGER,
    status TEXT DEFAULT 'open',
    question TEXT,
    city_date TEXT,
    close_time TIMESTAMPTZ,
    filled_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS risk_state (
    id INTEGER PRIMARY KEY DEFAULT 1,
    phase INTEGER DEFAULT 1,
    scale_factor NUMERIC(6,4) DEFAULT 1.0,
    scale_expires TIMESTAMPTZ,
    paused_until TIMESTAMPTZ,
    starting_balance NUMERIC(12,4),
    wallet_balance NUMERIC(12,4),
    free_cash NUMERIC(12,4),
    balance_updated_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS frozen_cities (
    city_date TEXT PRIMARY KEY,
    frozen_until TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS scan_results (
    ticker TEXT PRIMARY KEY,
    city_date TEXT,
    question TEXT,
    yes_price NUMERIC(8,4),
    no_price NUMERIC(8,4),
    prob_sum NUMERIC(8,4),
    excess NUMERIC(8,4),
    neighbor_ratio NUMERIC(8,4),
    com_distance NUMERIC(8,4),
    score NUMERIC(8,4),
    tier TEXT,
    order_size NUMERIC(12,4),
    spread NUMERIC(8,4),
    volume NUMERIC(12,2),
    skip_reason TEXT,
    scanned_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS daily_pnl (
    date DATE PRIMARY KEY,
    wallet_balance NUMERIC(12,4),
    free_cash NUMERIC(12,4),
    unresolved NUMERIC(12,4),
    trades_count INTEGER,
    exits_count INTEGER DEFAULT 0,
    resolutions_count INTEGER,
    wins INTEGER,
    losses INTEGER,
    daily_pnl NUMERIC(12,4),
    cumulative_pnl NUMERIC(12,4),
    no_win_rate NUMERIC(6,4),
    phase INTEGER
);

CREATE TABLE IF NOT EXISTS exits (
    id SERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    stage INTEGER,
    contracts_sold INTEGER,
    sell_price NUMERIC(8,4),
    entry_price NUMERIC(8,4),
    realized_pnl NUMERIC(12,4),
    reason TEXT,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS yes_positions (
    ticker TEXT PRIMARY KEY,
    origin_ticker TEXT NOT NULL,
    event_ticker TEXT,
    question TEXT,
    yes_contracts INTEGER DEFAULT 0,
    yes_cost NUMERIC(12,4) DEFAULT 0,
    entry_price_yes NUMERIC(8,4) DEFAULT 0,
    city_date TEXT,
    close_time TIMESTAMPTZ,
    no_loss_amount NUMERIC(12,4),
    resolved BOOLEAN DEFAULT FALSE,
    resolved_outcome TEXT,
    payout NUMERIC(12,4),
    pnl NUMERIC(12,4),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);
"""


async def main():
    load_dotenv("config/.env")
    dsn = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn)
    await conn.execute(SCHEMA)
    print("Schema created successfully.")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

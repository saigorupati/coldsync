import { pool } from './db'
import type { RiskState, Position, Trade, DailyPnl, TodayStats } from './types'

function num(val: unknown): number {
  if (val === null || val === undefined) return 0
  return parseFloat(String(val))
}

export async function getRiskState(): Promise<RiskState | null> {
  const { rows } = await pool.query('SELECT * FROM risk_state WHERE id = 1')
  if (rows.length === 0) return null
  const r = rows[0]
  return {
    ...r,
    scale_factor: num(r.scale_factor),
    starting_balance: num(r.starting_balance),
    wallet_balance: num(r.wallet_balance),
    free_cash: num(r.free_cash),
  }
}

export async function getOpenPositions(): Promise<Position[]> {
  const { rows } = await pool.query(
    'SELECT * FROM positions WHERE resolved = FALSE ORDER BY created_at DESC'
  )
  return rows.map((r) => ({
    ...r,
    no_contracts: parseInt(r.no_contracts),
    no_cost: num(r.no_cost),
    entry_price_no: num(r.entry_price_no),
    exit_stage: parseInt(r.exit_stage || '0'),
    payout: r.payout ? num(r.payout) : null,
    pnl: r.pnl ? num(r.pnl) : null,
  }))
}

export async function getOpenPositionsCount(): Promise<number> {
  const { rows } = await pool.query(
    'SELECT COUNT(*) as count FROM positions WHERE resolved = FALSE'
  )
  return parseInt(rows[0].count)
}

export async function getTodayStats(): Promise<TodayStats> {
  const todayUtc = new Date()
  todayUtc.setUTCHours(0, 0, 0, 0)

  const [tradesRes, exitsRes, resolRes] = await Promise.all([
    pool.query('SELECT COUNT(*) as count FROM trades WHERE timestamp >= $1', [todayUtc]),
    pool.query('SELECT COUNT(*) as count FROM exits WHERE timestamp >= $1', [todayUtc]),
    pool.query(
      `SELECT COUNT(*) as total,
              COUNT(*) FILTER (WHERE pnl >= 0) AS wins,
              COUNT(*) FILTER (WHERE pnl < 0) AS losses,
              COALESCE(SUM(pnl), 0) AS daily_pnl
       FROM positions
       WHERE resolved = TRUE AND resolved_at >= $1`,
      [todayUtc]
    ),
  ])

  return {
    trades_count: parseInt(tradesRes.rows[0].count),
    exits_count: parseInt(exitsRes.rows[0].count),
    resolutions: parseInt(resolRes.rows[0].total),
    wins: parseInt(resolRes.rows[0].wins),
    losses: parseInt(resolRes.rows[0].losses),
    daily_pnl: num(resolRes.rows[0].daily_pnl),
  }
}

export async function getTotalPnl(): Promise<number> {
  const [resolRes, exitRes] = await Promise.all([
    pool.query('SELECT COALESCE(SUM(pnl), 0) AS total FROM positions WHERE resolved = TRUE'),
    pool.query('SELECT COALESCE(SUM(realized_pnl), 0) AS total FROM exits'),
  ])
  return num(resolRes.rows[0].total) + num(exitRes.rows[0].total)
}

export async function getRecentTrades(limit: number = 50): Promise<Trade[]> {
  const { rows } = await pool.query(
    'SELECT * FROM trades ORDER BY timestamp DESC LIMIT $1',
    [limit]
  )
  return rows.map((r) => ({
    ...r,
    intended_price: num(r.intended_price),
    fill_price: r.fill_price ? num(r.fill_price) : null,
    count: parseInt(r.count || '0'),
    cost_usd: num(r.cost_usd),
  }))
}

export async function getDailyPnl(): Promise<DailyPnl[]> {
  const { rows } = await pool.query(
    'SELECT * FROM daily_pnl ORDER BY date ASC'
  )
  return rows.map((r) => ({
    ...r,
    wallet_balance: num(r.wallet_balance),
    free_cash: num(r.free_cash),
    unresolved: num(r.unresolved),
    daily_pnl: num(r.daily_pnl),
    cumulative_pnl: num(r.cumulative_pnl),
    no_win_rate: num(r.no_win_rate),
    trades_count: parseInt(r.trades_count || '0'),
    exits_count: parseInt(r.exits_count || '0'),
    resolutions_count: parseInt(r.resolutions_count || '0'),
    wins: parseInt(r.wins || '0'),
    losses: parseInt(r.losses || '0'),
    phase: parseInt(r.phase || '1'),
  }))
}

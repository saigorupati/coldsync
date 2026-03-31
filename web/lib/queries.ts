import { pool } from './db'
import type { RiskState, Position, Trade, DailyPnl, TodayStats, ScanResult, FrozenCity, PerformanceStats } from './types'

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

export async function getLatestScanResults(): Promise<ScanResult[]> {
  // Table is now one row per ticker (upsert), just read all current rows
  const { rows } = await pool.query(
    `SELECT * FROM scan_results ORDER BY city_date, score DESC`
  )

  return rows.map((r) => ({
    ...r,
    yes_price: num(r.yes_price),
    no_price: num(r.no_price),
    prob_sum: num(r.prob_sum),
    excess: num(r.excess),
    neighbor_ratio: num(r.neighbor_ratio),
    com_distance: num(r.com_distance),
    score: num(r.score),
    order_size: num(r.order_size),
    spread: num(r.spread),
    volume: num(r.volume),
  }))
}

export async function getLatestScanTime(): Promise<string | null> {
  const { rows } = await pool.query('SELECT MAX(scanned_at) AS latest FROM scan_results')
  return rows[0]?.latest || null
}

export async function getFrozenCities(): Promise<FrozenCity[]> {
  const { rows } = await pool.query(
    'SELECT city_date, frozen_until FROM frozen_cities WHERE frozen_until > NOW() ORDER BY frozen_until DESC'
  )
  return rows
}

export async function getPerformanceStats(): Promise<PerformanceStats> {
  const [pnlRes, winRateRes, daysRes, streakRes] = await Promise.all([
    pool.query(`
      SELECT COALESCE(SUM(pnl), 0) AS resolution_pnl FROM positions WHERE resolved = TRUE
    `),
    pool.query(`
      SELECT COUNT(*) AS total,
             COUNT(*) FILTER (WHERE pnl >= 0) AS wins,
             COUNT(*) FILTER (WHERE pnl < 0) AS losses
      FROM positions WHERE resolved = TRUE AND no_contracts > 0
    `),
    pool.query(`
      SELECT EXTRACT(DAY FROM NOW() - started_at)::int AS days
      FROM risk_state WHERE id = 1
    `),
    pool.query(`
      SELECT date, daily_pnl FROM daily_pnl ORDER BY date DESC LIMIT 30
    `),
  ])

  const exitPnlRes = await pool.query(
    'SELECT COALESCE(SUM(realized_pnl), 0) AS total FROM exits'
  )

  const totalPnl = num(pnlRes.rows[0].resolution_pnl) + num(exitPnlRes.rows[0].total)
  const total = parseInt(winRateRes.rows[0].total)
  const wins = parseInt(winRateRes.rows[0].wins)
  const losses = parseInt(winRateRes.rows[0].losses)
  const noWinRate = total > 0 ? wins / total : 0

  let streak = 0
  for (const r of streakRes.rows) {
    if (r.daily_pnl && num(r.daily_pnl) > 0) {
      streak++
    } else {
      break
    }
  }

  return {
    total_pnl: totalPnl,
    no_win_rate: noWinRate,
    total_resolved: total,
    total_wins: wins,
    total_losses: losses,
    days_active: parseInt(daysRes.rows[0]?.days || '0'),
    consecutive_profitable_days: streak,
  }
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

export async function getResolvedPositions(limit: number = 50): Promise<Position[]> {
  const { rows } = await pool.query(
    'SELECT * FROM positions WHERE resolved = TRUE ORDER BY resolved_at DESC LIMIT $1',
    [limit]
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

export async function getFilteredTrades(
  filters: { type?: string; status?: string; city?: string },
  limit: number = 100
): Promise<Trade[]> {
  const conditions: string[] = []
  const params: unknown[] = []
  let idx = 1

  if (filters.type) {
    conditions.push(`type LIKE $${idx}`)
    params.push(`%${filters.type}%`)
    idx++
  }
  if (filters.status) {
    conditions.push(`status = $${idx}`)
    params.push(filters.status)
    idx++
  }
  if (filters.city) {
    conditions.push(`city_date LIKE $${idx}`)
    params.push(`${filters.city}|%`)
    idx++
  }

  const where = conditions.length > 0 ? `WHERE ${conditions.join(' AND ')}` : ''
  params.push(limit)

  const { rows } = await pool.query(
    `SELECT * FROM trades ${where} ORDER BY timestamp DESC LIMIT $${idx}`,
    params
  )
  return rows.map((r) => ({
    ...r,
    intended_price: num(r.intended_price),
    fill_price: r.fill_price ? num(r.fill_price) : null,
    count: parseInt(r.count || '0'),
    cost_usd: num(r.cost_usd),
  }))
}

export async function getTradeFilterOptions(): Promise<{
  types: string[]
  statuses: string[]
  cities: string[]
}> {
  const [typesRes, statusesRes, citiesRes] = await Promise.all([
    pool.query('SELECT DISTINCT type FROM trades ORDER BY type'),
    pool.query('SELECT DISTINCT status FROM trades ORDER BY status'),
    pool.query("SELECT DISTINCT split_part(city_date, '|', 1) AS city FROM trades WHERE city_date IS NOT NULL AND city_date != '' ORDER BY city"),
  ])
  return {
    types: typesRes.rows.map((r) => r.type),
    statuses: statusesRes.rows.map((r) => r.status),
    cities: citiesRes.rows.map((r) => r.city),
  }
}

export async function getResolvedStats(): Promise<{
  total: number
  wins: number
  losses: number
  totalPnl: number
  winRate: number
}> {
  const { rows } = await pool.query(`
    SELECT COUNT(*) AS total,
           COUNT(*) FILTER (WHERE pnl >= 0) AS wins,
           COUNT(*) FILTER (WHERE pnl < 0) AS losses,
           COALESCE(SUM(pnl), 0) AS total_pnl
    FROM positions WHERE resolved = TRUE
  `)
  const r = rows[0]
  const total = parseInt(r.total)
  return {
    total,
    wins: parseInt(r.wins),
    losses: parseInt(r.losses),
    totalPnl: num(r.total_pnl),
    winRate: total > 0 ? parseInt(r.wins) / total : 0,
  }
}

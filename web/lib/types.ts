export interface RiskState {
  id: number
  phase: number
  scale_factor: number
  scale_expires: string | null
  paused_until: string | null
  starting_balance: number
  wallet_balance: number
  free_cash: number
  balance_updated_at: string | null
  started_at: string
}

export interface Position {
  ticker: string
  event_ticker: string
  question: string
  no_contracts: number
  no_cost: number
  entry_price_no: number
  exit_stage: number
  city_date: string
  close_time: string
  resolved: boolean
  resolved_outcome: string | null
  payout: number | null
  pnl: number | null
  created_at: string
  resolved_at: string | null
}

export interface Trade {
  id: number
  ticker: string
  type: string
  side: string
  action: string
  intended_price: number
  fill_price: number | null
  count: number
  cost_usd: number
  status: string
  question: string
  close_time: string | null
  city_date: string
  order_id: string
  timestamp: string
}

export interface DailyPnl {
  date: string
  wallet_balance: number
  free_cash: number
  unresolved: number
  trades_count: number
  exits_count: number
  resolutions_count: number
  wins: number
  losses: number
  daily_pnl: number
  cumulative_pnl: number
  no_win_rate: number
  phase: number
}

export interface TodayStats {
  trades_count: number
  exits_count: number
  resolutions: number
  wins: number
  losses: number
  daily_pnl: number
}

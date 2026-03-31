import { getRiskState, getOpenPositionsCount, getTodayStats, getTotalPnl } from '@/lib/queries'
import { formatUsd, formatPnl, pnlColor, phaseLabel } from '@/lib/format'
import StatCard from './components/stat-card'

export const dynamic = 'force-dynamic'

export default async function OverviewPage() {
  const [risk, openCount, today, totalPnl] = await Promise.all([
    getRiskState(),
    getOpenPositionsCount(),
    getTodayStats(),
    getTotalPnl(),
  ])

  const walletBal = risk?.wallet_balance ?? 0
  const freeCash = risk?.free_cash ?? 0
  const phase = risk?.phase ?? 1
  const scaleFactor = risk?.scale_factor ?? 1

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Overview</h2>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Wallet Balance" value={formatUsd(walletBal)} />
        <StatCard label="Free Cash" value={formatUsd(freeCash)} />
        <StatCard
          label="Phase"
          value={`${phaseLabel(phase)} (${(scaleFactor * 100).toFixed(0)}%)`}
        />
        <StatCard label="Open Positions" value={String(openCount)} />
        <StatCard
          label="Total P&L"
          value={formatPnl(totalPnl)}
          colorClass={pnlColor(totalPnl)}
        />
        <StatCard
          label="Today's P&L"
          value={formatPnl(today.daily_pnl)}
          colorClass={pnlColor(today.daily_pnl)}
        />
        <StatCard label="Today's Trades" value={String(today.trades_count)} />
        <StatCard
          label="Resolutions"
          value={`W${today.wins} / L${today.losses}`}
          colorClass={today.wins > today.losses ? 'text-green-400' : today.losses > 0 ? 'text-red-400' : 'text-white'}
        />
      </div>

      {risk?.paused_until && new Date(risk.paused_until) > new Date() && (
        <div className="mt-6 p-4 bg-red-900/30 border border-red-800 rounded-lg">
          <p className="text-red-400 font-medium">Risk pause active until {new Date(risk.paused_until).toLocaleString()}</p>
        </div>
      )}

      {risk?.balance_updated_at && (
        <p className="mt-4 text-xs text-zinc-600">
          Last updated: {new Date(risk.balance_updated_at).toLocaleString()}
        </p>
      )}
    </div>
  )
}

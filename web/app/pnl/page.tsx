import { getDailyPnl, getTotalPnl } from '@/lib/queries'
import { formatPnl, pnlColor } from '@/lib/format'
import PnlChart from './pnl-chart'

export const dynamic = 'force-dynamic'

export default async function PnlPage() {
  const [dailyData, totalPnl] = await Promise.all([
    getDailyPnl(),
    getTotalPnl(),
  ])

  const chartData = dailyData.map((d) => ({
    date: new Date(d.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
    dailyPnl: d.daily_pnl,
    cumulativePnl: d.cumulative_pnl,
    balance: d.wallet_balance,
  }))

  const bestDay = dailyData.reduce((max, d) => d.daily_pnl > max ? d.daily_pnl : max, -Infinity)
  const worstDay = dailyData.reduce((min, d) => d.daily_pnl < min ? d.daily_pnl : min, Infinity)

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Profit & Loss</h2>

      <div className="grid grid-cols-3 gap-4 mb-8">
        <div className="bg-zinc-900 rounded-lg p-4 border border-zinc-800">
          <p className="text-zinc-400 text-sm mb-1">Cumulative P&L</p>
          <p className={`text-2xl font-bold ${pnlColor(totalPnl)}`}>{formatPnl(totalPnl)}</p>
        </div>
        <div className="bg-zinc-900 rounded-lg p-4 border border-zinc-800">
          <p className="text-zinc-400 text-sm mb-1">Best Day</p>
          <p className={`text-2xl font-bold ${pnlColor(bestDay === -Infinity ? 0 : bestDay)}`}>
            {bestDay === -Infinity ? '-' : formatPnl(bestDay)}
          </p>
        </div>
        <div className="bg-zinc-900 rounded-lg p-4 border border-zinc-800">
          <p className="text-zinc-400 text-sm mb-1">Worst Day</p>
          <p className={`text-2xl font-bold ${pnlColor(worstDay === Infinity ? 0 : worstDay)}`}>
            {worstDay === Infinity ? '-' : formatPnl(worstDay)}
          </p>
        </div>
      </div>

      {chartData.length === 0 ? (
        <p className="text-zinc-500">No P&L data yet. Check back after the first day of trading.</p>
      ) : (
        <div className="bg-zinc-900 rounded-lg p-4 border border-zinc-800">
          <PnlChart data={chartData} />
        </div>
      )}

      <p className="mt-4 text-xs text-zinc-600">{dailyData.length} day(s) of data</p>
    </div>
  )
}

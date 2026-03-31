import { getRecentTrades } from '@/lib/queries'
import { formatUsd, formatCents, cityFromCityDate } from '@/lib/format'
import LocalTime from '../components/local-time'

export const dynamic = 'force-dynamic'

export default async function TradesPage() {
  const trades = await getRecentTrades(100)

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Recent Trades</h2>

      {trades.length === 0 ? (
        <p className="text-zinc-500">No trades yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-zinc-400 border-b border-zinc-800">
                <th className="pb-3 pr-4">Time</th>
                <th className="pb-3 pr-4">Type</th>
                <th className="pb-3 pr-4">Ticker</th>
                <th className="pb-3 pr-4">City</th>
                <th className="pb-3 pr-4 text-right">Price</th>
                <th className="pb-3 pr-4 text-right">Count</th>
                <th className="pb-3 pr-4 text-right">Cost</th>
                <th className="pb-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((trade) => (
                <tr key={trade.id} className="border-b border-zinc-800/50 hover:bg-zinc-900/50">
                  <td className="py-3 pr-4 text-zinc-500 text-xs whitespace-nowrap">
                    <LocalTime date={trade.timestamp} format="relative" />
                  </td>
                  <td className="py-3 pr-4">
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      trade.type.includes('exit') ? 'bg-yellow-900/50 text-yellow-400' :
                      trade.type.includes('no_buy') ? 'bg-blue-900/50 text-blue-400' :
                      trade.type.includes('no_limit') ? 'bg-purple-900/50 text-purple-400' :
                      'bg-zinc-800 text-zinc-400'
                    }`}>
                      {trade.type}
                    </span>
                  </td>
                  <td className="py-3 pr-4">
                    <code className="text-xs text-zinc-300">{trade.ticker}</code>
                  </td>
                  <td className="py-3 pr-4 text-zinc-300">{cityFromCityDate(trade.city_date)}</td>
                  <td className="py-3 pr-4 text-right font-mono">
                    {formatCents(trade.intended_price)}
                  </td>
                  <td className="py-3 pr-4 text-right font-mono">{trade.count}</td>
                  <td className="py-3 pr-4 text-right font-mono">{formatUsd(trade.cost_usd)}</td>
                  <td className="py-3">
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      trade.status === 'matched' ? 'bg-green-900/50 text-green-400' :
                      trade.status === 'resting' ? 'bg-blue-900/50 text-blue-400' :
                      trade.status === 'dry_run' ? 'bg-zinc-800 text-zinc-400' :
                      trade.status === 'error' ? 'bg-red-900/50 text-red-400' :
                      'bg-zinc-800 text-zinc-400'
                    }`}>
                      {trade.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-4 text-xs text-zinc-600">Showing last {trades.length} trade(s)</p>
    </div>
  )
}

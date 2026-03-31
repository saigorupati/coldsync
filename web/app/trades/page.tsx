import { getFilteredTrades, getTradeFilterOptions } from '@/lib/queries'
import { formatUsd, formatCents, cityFromCityDate, kalshiMarketUrl, typeColor, statusColor } from '@/lib/format'
import LocalTime from '../components/local-time'
import TradeFilters from '../components/trade-filters'

export const dynamic = 'force-dynamic'

interface Props {
  searchParams: Promise<{ [key: string]: string | undefined }>
}

export default async function TradesPage({ searchParams }: Props) {
  const params = await searchParams
  const filters = {
    type: params.type || undefined,
    status: params.status || undefined,
    city: params.city || undefined,
  }

  const [trades, filterOptions] = await Promise.all([
    getFilteredTrades(filters, 200),
    getTradeFilterOptions(),
  ])

  const totalSpent = trades.reduce((sum, t) => sum + t.cost_usd, 0)
  const filledCount = trades.filter((t) => t.status === 'matched').length

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold">Trades</h2>
        <div className="flex gap-4 text-sm">
          <div className="text-center">
            <div className="text-lg font-bold text-white">{trades.length}</div>
            <div className="text-zinc-500">Total</div>
          </div>
          <div className="text-center">
            <div className="text-lg font-bold text-green-400">{filledCount}</div>
            <div className="text-zinc-500">Filled</div>
          </div>
          <div className="text-center">
            <div className="text-lg font-bold text-white">{formatUsd(totalSpent)}</div>
            <div className="text-zinc-500">Spent</div>
          </div>
        </div>
      </div>

      <TradeFilters
        types={filterOptions.types}
        statuses={filterOptions.statuses}
        cities={filterOptions.cities}
      />

      {trades.length === 0 ? (
        <p className="text-zinc-500">No trades match your filters.</p>
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
              {trades.map((trade) => {
                const tc = typeColor(trade.type)
                const sc = statusColor(trade.status)
                return (
                  <tr key={trade.id} className="border-b border-zinc-800/50 hover:bg-zinc-900/50">
                    <td className="py-3 pr-4 text-zinc-500 text-xs whitespace-nowrap">
                      <LocalTime date={trade.timestamp} format="relative" />
                    </td>
                    <td className="py-3 pr-4">
                      <span className={`text-xs px-2 py-0.5 rounded ${tc.bg} ${tc.text}`}>
                        {trade.type}
                      </span>
                    </td>
                    <td className="py-3 pr-4">
                      <a
                        href={kalshiMarketUrl(trade.ticker)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-blue-400 hover:text-blue-300 hover:underline font-mono"
                      >
                        {trade.ticker}
                      </a>
                    </td>
                    <td className="py-3 pr-4 text-zinc-300">{cityFromCityDate(trade.city_date)}</td>
                    <td className="py-3 pr-4 text-right font-mono">
                      {formatCents(trade.intended_price)}
                    </td>
                    <td className="py-3 pr-4 text-right font-mono">{trade.count}</td>
                    <td className="py-3 pr-4 text-right font-mono">{formatUsd(trade.cost_usd)}</td>
                    <td className="py-3">
                      <span className={`text-xs px-2 py-0.5 rounded ${sc.bg} ${sc.text}`}>
                        {trade.status}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-4 text-xs text-zinc-600">Showing {trades.length} trade(s)</p>
    </div>
  )
}

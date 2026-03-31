import { getOpenPositions } from '@/lib/queries'
import { formatUsd, formatCents, cityFromCityDate, dateFromCityDate, exitStageLabel } from '@/lib/format'

export const dynamic = 'force-dynamic'

export default async function PositionsPage() {
  const positions = await getOpenPositions()

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Open Positions</h2>

      {positions.length === 0 ? (
        <p className="text-zinc-500">No open positions.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-zinc-400 border-b border-zinc-800">
                <th className="pb-3 pr-4">Ticker</th>
                <th className="pb-3 pr-4">Market</th>
                <th className="pb-3 pr-4">City</th>
                <th className="pb-3 pr-4 text-right">Contracts</th>
                <th className="pb-3 pr-4 text-right">Entry</th>
                <th className="pb-3 pr-4 text-right">Cost</th>
                <th className="pb-3 pr-4">Exit Stage</th>
                <th className="pb-3">Date</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos) => (
                <tr key={pos.ticker} className="border-b border-zinc-800/50 hover:bg-zinc-900/50">
                  <td className="py-3 pr-4">
                    <code className="text-xs text-zinc-300">{pos.ticker}</code>
                  </td>
                  <td className="py-3 pr-4 max-w-[200px] truncate text-zinc-300">
                    {pos.question || '-'}
                  </td>
                  <td className="py-3 pr-4 text-zinc-300">{cityFromCityDate(pos.city_date)}</td>
                  <td className="py-3 pr-4 text-right font-mono">{pos.no_contracts}</td>
                  <td className="py-3 pr-4 text-right font-mono">{formatCents(pos.entry_price_no)}</td>
                  <td className="py-3 pr-4 text-right font-mono">{formatUsd(pos.no_cost)}</td>
                  <td className="py-3 pr-4">
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      pos.exit_stage === 0 ? 'bg-zinc-800 text-zinc-400' :
                      pos.exit_stage === 3 ? 'bg-red-900/50 text-red-400' :
                      'bg-yellow-900/50 text-yellow-400'
                    }`}>
                      {exitStageLabel(pos.exit_stage)}
                    </span>
                  </td>
                  <td className="py-3 text-zinc-500 text-xs">{dateFromCityDate(pos.city_date)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-4 text-xs text-zinc-600">{positions.length} position(s)</p>
    </div>
  )
}

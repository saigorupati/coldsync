import { getOpenPositions, getResolvedPositions, getResolvedStats, getOpenYesPositions, getResolvedYesPositions } from '@/lib/queries'
import { formatUsd, formatCents, formatPnl, pnlColor, cityFromCityDate, dateFromCityDate, exitStageLabel, kalshiMarketUrl, outcomeColor } from '@/lib/format'
import Link from 'next/link'
import LocalTime from '../components/local-time'

export const dynamic = 'force-dynamic'

interface Props {
  searchParams: Promise<{ [key: string]: string | undefined }>
}

export default async function PositionsPage({ searchParams }: Props) {
  const params = await searchParams
  const tab = params.tab || 'open'

  if (tab === 'resolved') {
    const [resolved, stats, resolvedYes] = await Promise.all([
      getResolvedPositions(100),
      getResolvedStats(),
      getResolvedYesPositions(50),
    ])

    return (
      <div>
        <h2 className="text-2xl font-bold mb-4">Positions</h2>

        {/* Tabs */}
        <div className="flex gap-1 mb-6 border-b border-zinc-800">
          <Link
            href="/positions?tab=open"
            className="px-4 py-2 text-sm text-zinc-500 hover:text-zinc-300 transition-colors border-b-2 border-transparent"
          >
            Open
          </Link>
          <Link
            href="/positions?tab=resolved"
            className="px-4 py-2 text-sm text-white border-b-2 border-blue-500"
          >
            Resolved ({stats.total})
          </Link>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
          <div className="bg-zinc-900 rounded-lg p-3 border border-zinc-800">
            <p className="text-zinc-400 text-xs mb-1">Total P&L</p>
            <p className={`text-lg font-bold ${pnlColor(stats.totalPnl)}`}>{formatPnl(stats.totalPnl)}</p>
          </div>
          <div className="bg-zinc-900 rounded-lg p-3 border border-zinc-800">
            <p className="text-zinc-400 text-xs mb-1">Win Rate</p>
            <p className={`text-lg font-bold ${stats.winRate >= 0.9 ? 'text-green-400' : stats.winRate >= 0.8 ? 'text-yellow-400' : 'text-red-400'}`}>
              {(stats.winRate * 100).toFixed(1)}%
            </p>
          </div>
          <div className="bg-zinc-900 rounded-lg p-3 border border-zinc-800">
            <p className="text-zinc-400 text-xs mb-1">Wins</p>
            <p className="text-lg font-bold text-green-400">{stats.wins}</p>
          </div>
          <div className="bg-zinc-900 rounded-lg p-3 border border-zinc-800">
            <p className="text-zinc-400 text-xs mb-1">Losses</p>
            <p className="text-lg font-bold text-red-400">{stats.losses}</p>
          </div>
          <div className="bg-zinc-900 rounded-lg p-3 border border-zinc-800">
            <p className="text-zinc-400 text-xs mb-1">Early Exits</p>
            <p className="text-lg font-bold text-yellow-400">{stats.exited}</p>
          </div>
        </div>

        {/* NO Positions Table */}
        {resolved.length === 0 ? (
          <p className="text-zinc-500">No resolved positions yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-zinc-400 border-b border-zinc-800">
                  <th className="pb-3 pr-4">Ticker</th>
                  <th className="pb-3 pr-4">City</th>
                  <th className="pb-3 pr-4">Result</th>
                  <th className="pb-3 pr-4 text-right">Contracts</th>
                  <th className="pb-3 pr-4 text-right">Cost</th>
                  <th className="pb-3 pr-4 text-right">Payout</th>
                  <th className="pb-3 pr-4 text-right">P&L</th>
                  <th className="pb-3">Resolved</th>
                </tr>
              </thead>
              <tbody>
                {resolved.map((pos) => (
                  <tr
                    key={pos.ticker}
                    className={`border-b border-zinc-800/50 ${
                      pos.pnl && pos.pnl > 0 ? 'hover:bg-green-900/10' : 'hover:bg-red-900/10'
                    }`}
                  >
                    <td className="py-3 pr-4">
                      <a
                        href={kalshiMarketUrl(pos.ticker)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-blue-400 hover:text-blue-300 hover:underline font-mono"
                      >
                        {pos.ticker}
                      </a>
                    </td>
                    <td className="py-3 pr-4 text-zinc-300">{cityFromCityDate(pos.city_date)}</td>
                    <td className="py-3 pr-4">
                      <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                        pos.resolved_outcome === 'No' ? 'bg-green-900/50 text-green-400' :
                        pos.resolved_outcome === 'Yes' ? 'bg-red-900/50 text-red-400' :
                        pos.resolved_outcome === 'Exited' ? 'bg-yellow-900/50 text-yellow-400' :
                        'bg-zinc-800 text-zinc-400'
                      }`}>
                        {pos.resolved_outcome || '-'}
                      </span>
                    </td>
                    <td className="py-3 pr-4 text-right font-mono">{pos.no_contracts}</td>
                    <td className="py-3 pr-4 text-right font-mono">{formatUsd(pos.no_cost)}</td>
                    <td className="py-3 pr-4 text-right font-mono">{pos.payout != null ? formatUsd(pos.payout) : '-'}</td>
                    <td className={`py-3 pr-4 text-right font-mono font-bold ${pnlColor(pos.pnl ?? 0)}`}>
                      {pos.pnl != null ? formatPnl(pos.pnl) : '-'}
                    </td>
                    <td className="py-3 text-zinc-500 text-xs whitespace-nowrap">
                      <LocalTime date={pos.resolved_at} format="short" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* YES Flip Resolved Table */}
        {resolvedYes.length > 0 && (
          <>
            <h3 className="text-lg font-semibold mt-8 mb-4 text-purple-400">YES Flip Results</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-zinc-400 border-b border-zinc-800">
                    <th className="pb-3 pr-4">Ticker</th>
                    <th className="pb-3 pr-4">City</th>
                    <th className="pb-3 pr-4">Result</th>
                    <th className="pb-3 pr-4 text-right">Contracts</th>
                    <th className="pb-3 pr-4 text-right">Cost</th>
                    <th className="pb-3 pr-4 text-right">Payout</th>
                    <th className="pb-3 pr-4 text-right">P&L</th>
                    <th className="pb-3 pr-4 text-right">NO Loss</th>
                    <th className="pb-3">Resolved</th>
                  </tr>
                </thead>
                <tbody>
                  {resolvedYes.map((yp) => (
                    <tr
                      key={`yes-${yp.ticker}`}
                      className={`border-b border-zinc-800/50 ${
                        yp.pnl && yp.pnl > 0 ? 'hover:bg-green-900/10' : 'hover:bg-red-900/10'
                      }`}
                    >
                      <td className="py-3 pr-4">
                        <a
                          href={kalshiMarketUrl(yp.ticker)}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs text-purple-400 hover:text-purple-300 hover:underline font-mono"
                        >
                          {yp.ticker}
                        </a>
                      </td>
                      <td className="py-3 pr-4 text-zinc-300">{cityFromCityDate(yp.city_date)}</td>
                      <td className="py-3 pr-4">
                        <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                          yp.resolved_outcome === 'Yes' ? 'bg-green-900/50 text-green-400' :
                          yp.resolved_outcome === 'No' ? 'bg-red-900/50 text-red-400' :
                          yp.resolved_outcome === 'Stopped' ? 'bg-yellow-900/50 text-yellow-400' :
                          'bg-zinc-800 text-zinc-400'
                        }`}>
                          {yp.resolved_outcome || '-'}
                        </span>
                      </td>
                      <td className="py-3 pr-4 text-right font-mono">{yp.yes_contracts}</td>
                      <td className="py-3 pr-4 text-right font-mono">{formatUsd(yp.yes_cost)}</td>
                      <td className="py-3 pr-4 text-right font-mono">{yp.payout != null ? formatUsd(yp.payout) : '-'}</td>
                      <td className={`py-3 pr-4 text-right font-mono font-bold ${pnlColor(yp.pnl ?? 0)}`}>
                        {yp.pnl != null ? formatPnl(yp.pnl) : '-'}
                      </td>
                      <td className="py-3 pr-4 text-right font-mono text-red-400">
                        {formatPnl(yp.no_loss_amount)}
                      </td>
                      <td className="py-3 text-zinc-500 text-xs whitespace-nowrap">
                        <LocalTime date={yp.resolved_at} format="short" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    )
  }

  // Default: Open positions tab
  const [positions, yesPositions] = await Promise.all([
    getOpenPositions(),
    getOpenYesPositions(),
  ])
  // Filter out 0-contract positions (fully exited but awaiting resolution fix)
  const activePositions = positions.filter((p) => p.no_contracts > 0)
  const totalExposure = activePositions.reduce((sum, p) => sum + p.no_cost, 0)
  const yesExposure = yesPositions.reduce((sum, p) => sum + p.yes_cost, 0)

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Positions</h2>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 border-b border-zinc-800">
        <Link
          href="/positions?tab=open"
          className="px-4 py-2 text-sm text-white border-b-2 border-blue-500"
        >
          Open ({activePositions.length + yesPositions.length})
        </Link>
        <Link
          href="/positions?tab=resolved"
          className="px-4 py-2 text-sm text-zinc-500 hover:text-zinc-300 transition-colors border-b-2 border-transparent"
        >
          Resolved
        </Link>
      </div>

      {/* Exposure summary */}
      {(activePositions.length > 0 || yesPositions.length > 0) && (
        <div className="mb-4 text-sm text-zinc-400 flex gap-4">
          <span>NO exposure: <span className="text-white font-mono font-bold">{formatUsd(totalExposure)}</span></span>
          {yesPositions.length > 0 && (
            <span>YES exposure: <span className="text-purple-400 font-mono font-bold">{formatUsd(yesExposure)}</span></span>
          )}
        </div>
      )}

      {/* NO Positions */}
      {activePositions.length === 0 && yesPositions.length === 0 ? (
        <p className="text-zinc-500">No open positions.</p>
      ) : (
        <>
          {activePositions.length > 0 && (
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
                  {activePositions.map((pos) => (
                    <tr key={pos.ticker} className="border-b border-zinc-800/50 hover:bg-zinc-900/50">
                      <td className="py-3 pr-4">
                        <a
                          href={kalshiMarketUrl(pos.ticker)}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs text-blue-400 hover:text-blue-300 hover:underline font-mono"
                        >
                          {pos.ticker}
                        </a>
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

          {/* YES Flip Positions */}
          {yesPositions.length > 0 && (
            <>
              <h3 className="text-lg font-semibold mt-6 mb-3 text-purple-400">YES Flip Positions</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-zinc-400 border-b border-zinc-800">
                      <th className="pb-3 pr-4">Ticker</th>
                      <th className="pb-3 pr-4">City</th>
                      <th className="pb-3 pr-4 text-right">YES Contracts</th>
                      <th className="pb-3 pr-4 text-right">Entry</th>
                      <th className="pb-3 pr-4 text-right">Cost</th>
                      <th className="pb-3 pr-4 text-right">NO Loss</th>
                      <th className="pb-3 pr-4 text-right">Potential Payout</th>
                      <th className="pb-3">Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {yesPositions.map((yp) => (
                      <tr key={`yes-${yp.ticker}`} className="border-b border-zinc-800/50 hover:bg-purple-900/10">
                        <td className="py-3 pr-4">
                          <a
                            href={kalshiMarketUrl(yp.ticker)}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs text-purple-400 hover:text-purple-300 hover:underline font-mono"
                          >
                            {yp.ticker}
                          </a>
                        </td>
                        <td className="py-3 pr-4 text-zinc-300">{cityFromCityDate(yp.city_date)}</td>
                        <td className="py-3 pr-4 text-right font-mono">{yp.yes_contracts}</td>
                        <td className="py-3 pr-4 text-right font-mono">{formatCents(yp.entry_price_yes)}</td>
                        <td className="py-3 pr-4 text-right font-mono">{formatUsd(yp.yes_cost)}</td>
                        <td className="py-3 pr-4 text-right font-mono text-red-400">
                          {formatPnl(yp.no_loss_amount)}
                        </td>
                        <td className="py-3 pr-4 text-right font-mono text-green-400">
                          ${yp.yes_contracts.toFixed(2)}
                        </td>
                        <td className="py-3 text-zinc-500 text-xs">{dateFromCityDate(yp.city_date)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}

      <p className="mt-4 text-xs text-zinc-600">
        {activePositions.length} NO position(s){yesPositions.length > 0 ? `, ${yesPositions.length} YES flip(s)` : ''}
      </p>
    </div>
  )
}

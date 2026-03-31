import { getLatestScanResults, getLatestScanTime } from '@/lib/queries'
import type { ScanResult } from '@/lib/types'
import AutoRefresh from '../components/auto-refresh'
import ScoringFilters from '../components/scoring-filters'

export const dynamic = 'force-dynamic'

const TIER_STYLES: Record<string, string> = {
  A: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  B: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  C: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  D: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  SKIP: 'bg-zinc-800/50 text-zinc-600 border-zinc-700/30',
}

const CITY_ICONS: Record<string, string> = {
  NYC: '🗽', CHI: '🌬️', MIA: '🌴', LA: '🌅',
  DEN: '🏔️', ATL: '🍑', DFW: '⛳', HOU: '🚀',
  PHX: '🌵', SEA: '☕', SF: '🌉',
}

function cityLabel(cityDate: string): { city: string; code: string; date: string; icon: string } {
  const [code, rawDate] = cityDate.split('|')
  const icon = CITY_ICONS[code] || '🌡️'
  const date = rawDate
    ? new Date(rawDate + 'T00:00:00Z').toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        timeZone: 'UTC',
      })
    : ''
  return { city: code, code, date, icon }
}

function tempRange(question: string): string {
  // Kalshi format: "Will the high temperature ... be between 55 and 59 degrees?"
  const between = question.match(/between (\d+) and (\d+)/)
  if (between) return `${between[1]}-${between[2]}F`
  const orAbove = question.match(/(\d+) degrees or above/)
  if (orAbove) return `>=${orAbove[1]}F`
  const orBelow = question.match(/(\d+) degrees or below/)
  if (orBelow) return `<=${orBelow[1]}F`
  // Fallback: try ticker parsing (HIGHNY-26MAR30-T55 -> T55)
  const tickerMatch = question.match(/T(\d+)/)
  if (tickerMatch) return `>=${tickerMatch[1]}F`
  return question.slice(0, 20)
}

function tempRangeFromTicker(ticker: string): string {
  const match = ticker.match(/T(\d+)/)
  if (match) return `>=${match[1]}F`
  const bMatch = ticker.match(/B(\d+)(\d{2})/)
  if (bMatch) return `${bMatch[1]}-${bMatch[2]}F`
  return ticker
}

function scoreBar(score: number): { width: string; color: string } {
  const pct = Math.min((score / 8) * 100, 100)
  let color = 'bg-zinc-700'
  if (score >= 5) color = 'bg-emerald-500'
  else if (score >= 3) color = 'bg-emerald-600'
  else if (score >= 2) color = 'bg-yellow-600'
  else if (score >= 1) color = 'bg-orange-600'
  return { width: `${pct}%`, color }
}

function excessColor(excess: number): string {
  if (excess >= 0.08) return 'text-emerald-400'
  if (excess >= 0.03) return 'text-emerald-500'
  if (excess >= 0.01) return 'text-yellow-400'
  return 'text-zinc-500'
}

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>
}

export default async function ScoringPage({ searchParams }: PageProps) {
  const params = await searchParams
  const filterCity = (typeof params.city === 'string' ? params.city : '') || ''
  const filterDate = (typeof params.date === 'string' ? params.date : '') || ''
  const filterTier = (typeof params.tier === 'string' ? params.tier : '') || ''
  const filterMinScore = parseFloat((typeof params.minScore === 'string' ? params.minScore : '') || '0') || 0
  const filterTradeable = params.tradeable === '1'
  const sortBy = (typeof params.sort === 'string' ? params.sort : '') || ''

  const [allRows, latestTime] = await Promise.all([
    getLatestScanResults(),
    getLatestScanTime(),
  ])

  // Extract unique cities and dates for filter dropdowns
  const allCities = [...new Set(allRows.map(r => r.city_date.split('|')[0]))].sort()
  const allDates = [...new Set(allRows.map(r => r.city_date.split('|')[1]))].sort()

  // Apply filters
  let rows = allRows

  if (filterCity) {
    rows = rows.filter(r => r.city_date.split('|')[0] === filterCity)
  }
  if (filterDate) {
    rows = rows.filter(r => r.city_date.split('|')[1] === filterDate)
  }
  if (filterTier) {
    rows = rows.filter(r => r.tier === filterTier)
  }
  if (filterMinScore > 0) {
    rows = rows.filter(r => r.score >= filterMinScore)
  }
  if (filterTradeable) {
    rows = rows.filter(r => r.tier !== 'SKIP')
  }

  // Group by city_date
  const grouped: Record<string, ScanResult[]> = {}
  for (const row of rows) {
    if (!grouped[row.city_date]) grouped[row.city_date] = []
    grouped[row.city_date].push(row)
  }

  // Sort city groups
  let cityDates = Object.keys(grouped)

  if (sortBy === 'score') {
    cityDates.sort((a, b) => {
      const maxA = grouped[a].reduce((m, r) => Math.max(m, r.score), 0)
      const maxB = grouped[b].reduce((m, r) => Math.max(m, r.score), 0)
      return maxB - maxA
    })
    for (const cd of cityDates) {
      grouped[cd].sort((a, b) => b.score - a.score)
    }
  } else if (sortBy === 'excess') {
    cityDates.sort((a, b) => (grouped[b][0]?.excess ?? 0) - (grouped[a][0]?.excess ?? 0))
  } else if (sortBy === 'spread') {
    cityDates.sort((a, b) => {
      const minA = grouped[a].reduce((m, r) => Math.min(m, r.spread), 1)
      const minB = grouped[b].reduce((m, r) => Math.min(m, r.spread), 1)
      return minA - minB
    })
  } else if (sortBy === 'size') {
    cityDates.sort((a, b) => {
      const sumA = grouped[a].reduce((s, r) => s + r.order_size, 0)
      const sumB = grouped[b].reduce((s, r) => s + r.order_size, 0)
      return sumB - sumA
    })
  } else {
    cityDates.sort((a, b) => {
      const [, dateA] = a.split('|')
      const [, dateB] = b.split('|')
      return (dateA || '').localeCompare(dateB || '') || a.localeCompare(b)
    })
  }

  // Summary stats
  const totalBins = rows.length
  const actionable = rows.filter(r => r.tier !== 'SKIP').length
  const topScore = rows.reduce((max, r) => Math.max(max, r.score), 0)
  const totalSize = rows.reduce((s, r) => s + r.order_size, 0)
  const isFiltered = rows.length !== allRows.length

  return (
    <div>
      <AutoRefresh intervalSeconds={60} />

      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-2xl font-bold text-white">Live Scoring</h2>
          <p className="text-sm text-zinc-500 mt-1">
            {latestTime
              ? `Last scan: ${new Date(latestTime).toLocaleString('en-US', { timeZone: 'UTC', hour12: false })} UTC`
              : 'Waiting for first scan...'}
          </p>
        </div>
        <div className="flex gap-4 text-sm">
          <div className="text-center">
            <div className="text-lg font-bold text-white">
              {totalBins}
              {isFiltered && <span className="text-zinc-600 text-xs font-normal">/{allRows.length}</span>}
            </div>
            <div className="text-zinc-500">Bins</div>
          </div>
          <div className="text-center">
            <div className={`text-lg font-bold ${actionable > 0 ? 'text-emerald-400' : 'text-zinc-500'}`}>{actionable}</div>
            <div className="text-zinc-500">Tradeable</div>
          </div>
          <div className="text-center">
            <div className={`text-lg font-bold ${topScore >= 5 ? 'text-emerald-400' : topScore >= 3 ? 'text-yellow-400' : 'text-zinc-400'}`}>
              {topScore.toFixed(1)}
            </div>
            <div className="text-zinc-500">Top Score</div>
          </div>
          <div className="text-center">
            <div className={`text-lg font-bold ${totalSize > 0 ? 'text-blue-400' : 'text-zinc-500'}`}>
              ${totalSize.toFixed(0)}
            </div>
            <div className="text-zinc-500">Total Size</div>
          </div>
        </div>
      </div>

      {/* Filters */}
      <ScoringFilters cities={allCities} dates={allDates} />

      {/* Tier Legend */}
      <div className="flex gap-2 mb-6 text-xs">
        {['A', 'B', 'C', 'D', 'SKIP'].map(t => (
          <span key={t} className={`px-2 py-1 rounded border ${TIER_STYLES[t]}`}>
            {t}
          </span>
        ))}
        <span className="text-zinc-600 ml-2 self-center">
          A=Best - B=Good - C=Marginal - D=Extended - SKIP=Filtered
        </span>
      </div>

      {rows.length === 0 ? (
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-12 text-center">
          <p className="text-zinc-500 text-lg">
            {allRows.length === 0 ? 'No scan results yet' : 'No results match filters'}
          </p>
          <p className="text-zinc-600 text-sm mt-2">
            {allRows.length === 0
              ? 'Wait for the bot to complete a scan cycle'
              : `${allRows.length} bins available — try adjusting filters`}
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {cityDates.map((cityDate) => {
            const bins = grouped[cityDate]
            const excess = bins[0]?.excess ?? 0
            const probSum = bins[0]?.prob_sum ?? 0
            const { city, date, icon } = cityLabel(cityDate)
            const actionableBins = bins.filter(b => b.tier !== 'SKIP')
            const groupSize = bins.reduce((s, r) => s + r.order_size, 0)

            return (
              <div key={cityDate} className="bg-zinc-900 border border-zinc-800 rounded-lg overflow-hidden">
                {/* City Header */}
                <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-xl">{icon}</span>
                    <div>
                      <span className="font-semibold text-white">{city}</span>
                      <span className="text-zinc-500 ml-2">{date}</span>
                    </div>
                    {actionableBins.length > 0 && (
                      <span className="bg-emerald-500/15 text-emerald-400 text-xs px-2 py-0.5 rounded-full font-medium">
                        {actionableBins.length} tradeable
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-6 text-sm">
                    <div>
                      <span className="text-zinc-500">Prob Sum </span>
                      <span className="text-zinc-300 font-mono">{(probSum * 100).toFixed(1)}%</span>
                    </div>
                    <div>
                      <span className="text-zinc-500">Excess </span>
                      <span className={`font-mono font-medium ${excessColor(excess)}`}>
                        {excess >= 0 ? '+' : ''}{(excess * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div>
                      <span className="text-zinc-500">Bins </span>
                      <span className="text-zinc-300">{bins.length}</span>
                    </div>
                    {groupSize > 0 && (
                      <div>
                        <span className="text-zinc-500">Size </span>
                        <span className="text-blue-400 font-mono">${groupSize.toFixed(0)}</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Bins Table */}
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-zinc-500 text-xs uppercase tracking-wider">
                        <th className="px-4 py-2 text-left">Ticker</th>
                        <th className="px-3 py-2 text-left">Temp</th>
                        <th className="px-3 py-2 text-right">Yes</th>
                        <th className="px-3 py-2 text-right">No</th>
                        <th className="px-3 py-2 text-right">Spread</th>
                        <th className="px-3 py-2 text-right">Vol</th>
                        <th className="px-3 py-2 text-left w-32">Score</th>
                        <th className="px-3 py-2 text-center">Tier</th>
                        <th className="px-3 py-2 text-right">Size</th>
                        <th className="px-4 py-2 text-left">Note</th>
                      </tr>
                    </thead>
                    <tbody>
                      {bins.map((row) => {
                        const bar = scoreBar(row.score)
                        const isActionable = row.tier !== 'SKIP'

                        return (
                          <tr
                            key={row.id}
                            className={`border-t border-zinc-800/40 ${
                              isActionable
                                ? 'bg-zinc-800/20 hover:bg-zinc-800/40'
                                : 'opacity-50 hover:opacity-75'
                            } transition-all`}
                          >
                            <td className="px-4 py-2">
                              <code className={`text-xs ${isActionable ? 'text-zinc-300' : 'text-zinc-600'}`}>
                                {row.ticker}
                              </code>
                            </td>
                            <td className="px-3 py-2">
                              <span className={`font-mono ${isActionable ? 'text-white font-medium' : 'text-zinc-500'}`}>
                                {row.question ? tempRange(row.question) : tempRangeFromTicker(row.ticker)}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-right font-mono text-zinc-400">
                              {(row.yes_price * 100).toFixed(1)}c
                            </td>
                            <td className="px-3 py-2 text-right font-mono">
                              <span className={isActionable ? 'text-white' : 'text-zinc-400'}>
                                {(row.no_price * 100).toFixed(1)}c
                              </span>
                            </td>
                            <td className="px-3 py-2 text-right font-mono text-zinc-500">
                              {(row.spread * 100).toFixed(1)}c
                            </td>
                            <td className="px-3 py-2 text-right font-mono text-zinc-500">
                              {row.volume > 0 ? `$${row.volume.toFixed(0)}` : '-'}
                            </td>
                            <td className="px-3 py-2">
                              <div className="flex items-center gap-2">
                                <div className="w-16 bg-zinc-800 rounded-full h-1.5 overflow-hidden">
                                  <div className={`h-full rounded-full ${bar.color}`} style={{ width: bar.width }} />
                                </div>
                                <span className={`font-mono text-xs ${
                                  row.score >= 5 ? 'text-emerald-400' :
                                  row.score >= 3 ? 'text-emerald-500' :
                                  row.score >= 2 ? 'text-yellow-400' :
                                  row.score >= 1 ? 'text-orange-400' :
                                  'text-zinc-600'
                                }`}>
                                  {row.score.toFixed(1)}
                                </span>
                              </div>
                            </td>
                            <td className="px-3 py-2 text-center">
                              <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium border ${TIER_STYLES[row.tier] || TIER_STYLES.SKIP}`}>
                                {row.tier}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-right font-mono">
                              {row.order_size > 0
                                ? <span className="text-emerald-400">${row.order_size.toFixed(0)}</span>
                                : <span className="text-zinc-700">-</span>
                              }
                            </td>
                            <td className="px-4 py-2 text-zinc-600 text-xs truncate max-w-[180px]" title={row.skip_reason || ''}>
                              {row.skip_reason || ''}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

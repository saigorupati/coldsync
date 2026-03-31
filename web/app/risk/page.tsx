import { getRiskState, getPerformanceStats, getFrozenCities, getTotalPnl } from '@/lib/queries'
import { formatUsd, formatPnl, pnlColor, phaseLabel } from '@/lib/format'
import StatCard from '../components/stat-card'

export const dynamic = 'force-dynamic'

const RISK_PARAMS = [
  { label: 'Safety Buffer', key: 'safety_buffer_pct', format: (p: number) => ({ 1: '25%', 2: '20%', 3: '15%' }[p] || '25%') },
  { label: 'Max Unresolved', key: 'max_unresolved_pct', format: (p: number) => ({ 1: '50%', 2: '65%', 3: '75%' }[p] || '50%') },
  { label: 'Max Per Market', value: '2%' },
  { label: 'Max Per City/Date', value: '10%' },
  { label: 'Loss Warning Count', value: '2' },
  { label: 'Loss Hard Pause', value: '3' },
  { label: 'City Freeze Trigger', value: '2 losses' },
  { label: 'City Freeze Duration', value: '24h' },
  { label: 'Scale Up Streak', value: '5 days' },
  { label: 'Scale Up Factor', value: '1.10x' },
  { label: 'Scale Down Trigger', value: '2 daily losses' },
  { label: 'Scale Down Factor', value: '0.75x for 48h' },
  { label: 'Exit Stage 1', value: '-10% -> sell 33%' },
  { label: 'Exit Stage 2', value: '-20% -> sell 66%' },
  { label: 'Exit Stage 3', value: '-30% -> full exit' },
]

export default async function RiskPage() {
  const [risk, perf, frozenCities] = await Promise.all([
    getRiskState(),
    getPerformanceStats(),
    getFrozenCities(),
  ])

  const phase = risk?.phase ?? 1
  const scaleFactor = risk?.scale_factor ?? 1
  const startingBal = risk?.starting_balance ?? 0
  const walletBal = risk?.wallet_balance ?? 0

  const isPaused = risk?.paused_until && new Date(risk.paused_until) > new Date()
  const isScaled = risk?.scale_expires && new Date(risk.scale_expires) > new Date()

  // Phase progression
  const phaseRequirements = [
    {
      phase: 1,
      label: 'Learning',
      requirements: [
        { text: '14+ days active', met: perf.days_active >= 14, value: `${perf.days_active}/14 days` },
        { text: '90%+ No win rate', met: perf.no_win_rate >= 0.90, value: `${(perf.no_win_rate * 100).toFixed(1)}%` },
      ],
    },
    {
      phase: 2,
      label: 'Standard',
      requirements: [
        { text: '30+ days active', met: perf.days_active >= 30, value: `${perf.days_active}/30 days` },
        { text: 'P&L > 10% of starting', met: startingBal > 0 && perf.total_pnl / startingBal >= 0.10, value: startingBal > 0 ? `${((perf.total_pnl / startingBal) * 100).toFixed(1)}%` : 'N/A' },
      ],
    },
    {
      phase: 3,
      label: 'Scaled',
      requirements: [{ text: 'All conditions met', met: true, value: 'Active' }],
    },
  ]

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Risk Management</h2>

      {/* Status cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard
          label="Phase"
          value={`${phaseLabel(phase)}`}
          colorClass={phase === 3 ? 'text-purple-400' : phase === 2 ? 'text-blue-400' : 'text-yellow-400'}
        />
        <StatCard
          label="Scale Factor"
          value={`${(scaleFactor * 100).toFixed(0)}%`}
          colorClass={scaleFactor > 1 ? 'text-green-400' : scaleFactor < 1 ? 'text-orange-400' : 'text-white'}
        />
        <StatCard
          label="Days Active"
          value={String(perf.days_active)}
        />
        <StatCard
          label="Status"
          value={isPaused ? 'PAUSED' : 'Active'}
          colorClass={isPaused ? 'text-red-400' : 'text-green-400'}
        />
        <StatCard
          label="Starting Balance"
          value={formatUsd(startingBal)}
        />
        <StatCard
          label="Total P&L"
          value={formatPnl(perf.total_pnl)}
          colorClass={pnlColor(perf.total_pnl)}
        />
        <StatCard
          label="No Win Rate"
          value={`${(perf.no_win_rate * 100).toFixed(1)}%`}
          colorClass={perf.no_win_rate >= 0.90 ? 'text-green-400' : perf.no_win_rate >= 0.80 ? 'text-yellow-400' : 'text-red-400'}
        />
        <StatCard
          label="Record"
          value={`${perf.total_wins}W / ${perf.total_losses}L`}
          colorClass={perf.total_wins > perf.total_losses ? 'text-green-400' : 'text-zinc-400'}
        />
      </div>

      {/* Alerts */}
      {isPaused && (
        <div className="mb-6 p-4 bg-red-900/30 border border-red-800 rounded-lg">
          <p className="text-red-400 font-medium">
            Risk pause active until {new Date(risk!.paused_until!).toLocaleString()}
          </p>
        </div>
      )}

      {isScaled && scaleFactor !== 1 && (
        <div className="mb-6 p-4 bg-orange-900/30 border border-orange-800 rounded-lg">
          <p className="text-orange-400 font-medium">
            Scale override active ({(scaleFactor * 100).toFixed(0)}%) until {new Date(risk!.scale_expires!).toLocaleString()}
          </p>
        </div>
      )}

      {perf.consecutive_profitable_days >= 3 && (
        <div className="mb-6 p-4 bg-green-900/30 border border-green-800 rounded-lg">
          <p className="text-green-400 font-medium">
            {perf.consecutive_profitable_days} consecutive profitable days
          </p>
        </div>
      )}

      {/* Phase Progression */}
      <div className="mb-8">
        <h3 className="text-lg font-semibold mb-4">Phase Progression</h3>
        <div className="space-y-4">
          {phaseRequirements.map((pr) => (
            <div
              key={pr.phase}
              className={`p-4 rounded-lg border ${
                phase === pr.phase
                  ? 'border-blue-600 bg-blue-900/20'
                  : phase > pr.phase
                  ? 'border-green-800 bg-green-900/10'
                  : 'border-zinc-800 bg-zinc-900'
              }`}
            >
              <div className="flex items-center gap-3 mb-2">
                <span
                  className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold ${
                    phase > pr.phase
                      ? 'bg-green-600 text-white'
                      : phase === pr.phase
                      ? 'bg-blue-600 text-white'
                      : 'bg-zinc-700 text-zinc-400'
                  }`}
                >
                  {phase > pr.phase ? '\u2713' : pr.phase}
                </span>
                <span className={`font-medium ${phase >= pr.phase ? 'text-white' : 'text-zinc-500'}`}>
                  Phase {pr.phase}: {pr.label}
                </span>
                {phase === pr.phase && (
                  <span className="text-xs bg-blue-600 text-white px-2 py-0.5 rounded-full">Current</span>
                )}
              </div>
              <div className="ml-11 space-y-1">
                {pr.requirements.map((req, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    <span className={req.met ? 'text-green-400' : 'text-zinc-500'}>
                      {req.met ? '\u2713' : '\u2022'}
                    </span>
                    <span className={req.met ? 'text-green-400' : 'text-zinc-400'}>
                      {req.text}
                    </span>
                    <span className="text-zinc-600 ml-auto">{req.value}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Frozen Cities */}
      <div className="mb-8">
        <h3 className="text-lg font-semibold mb-4">Frozen Cities</h3>
        {frozenCities.length === 0 ? (
          <p className="text-zinc-500 text-sm">No cities currently frozen</p>
        ) : (
          <div className="bg-zinc-900 rounded-lg border border-zinc-800 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-800">
                  <th className="text-left p-3 text-zinc-400 font-medium">City/Date</th>
                  <th className="text-left p-3 text-zinc-400 font-medium">Frozen Until</th>
                  <th className="text-left p-3 text-zinc-400 font-medium">Time Remaining</th>
                </tr>
              </thead>
              <tbody>
                {frozenCities.map((fc) => {
                  const until = new Date(fc.frozen_until)
                  const remaining = Math.max(0, Math.floor((until.getTime() - Date.now()) / 3600000))
                  return (
                    <tr key={fc.city_date} className="border-b border-zinc-800/50">
                      <td className="p-3 text-white font-mono">{fc.city_date}</td>
                      <td className="p-3 text-zinc-300">{until.toLocaleString()}</td>
                      <td className="p-3 text-orange-400">{remaining}h</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Risk Parameters Reference */}
      <div>
        <h3 className="text-lg font-semibold mb-4">Risk Parameters</h3>
        <div className="bg-zinc-900 rounded-lg border border-zinc-800 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-800">
                <th className="text-left p-3 text-zinc-400 font-medium">Parameter</th>
                <th className="text-left p-3 text-zinc-400 font-medium">Value</th>
              </tr>
            </thead>
            <tbody>
              {RISK_PARAMS.map((param) => (
                <tr key={param.label} className="border-b border-zinc-800/50">
                  <td className="p-3 text-zinc-300">{param.label}</td>
                  <td className="p-3 text-white font-mono">
                    {'value' in param ? param.value : param.format(phase)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {risk?.balance_updated_at && (
        <p className="mt-6 text-xs text-zinc-600">
          Last updated: {new Date(risk.balance_updated_at).toLocaleString()}
        </p>
      )}
    </div>
  )
}

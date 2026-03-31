'use client'

import { useRouter, useSearchParams } from 'next/navigation'

interface ScoringFiltersProps {
  cities: string[]
  dates: string[]
}

const tiers = [
  { value: '', label: 'All Tiers' },
  { value: 'A', label: 'Tier A' },
  { value: 'B', label: 'Tier B' },
  { value: 'C', label: 'Tier C' },
  { value: 'D', label: 'Tier D' },
  { value: 'SKIP', label: 'SKIP' },
]

const minScores = [
  { value: '', label: 'Any Score' },
  { value: '1', label: 'Score >= 1' },
  { value: '2', label: 'Score >= 2' },
  { value: '3', label: 'Score >= 3' },
  { value: '5', label: 'Score >= 5' },
]

const sortOptions = [
  { value: '', label: 'Default (City > Score)' },
  { value: 'score', label: 'Highest Score' },
  { value: 'excess', label: 'Highest Excess' },
  { value: 'spread', label: 'Tightest Spread' },
  { value: 'size', label: 'Largest Size' },
]

const selectClass =
  'bg-zinc-800 border border-zinc-700 text-zinc-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-zinc-600 min-w-[130px]'

export default function ScoringFilters({ cities, dates }: ScoringFiltersProps) {
  const router = useRouter()
  const searchParams = useSearchParams()

  const activeCount = ['city', 'date', 'tier', 'minScore', 'sort', 'tradeable'].filter(
    (k) => searchParams.get(k)
  ).length

  function set(key: string, value: string) {
    const params = new URLSearchParams(searchParams.toString())
    if (value) {
      params.set(key, value)
    } else {
      params.delete(key)
    }
    router.push(`/scoring?${params.toString()}`)
  }

  function clearAll() {
    router.push('/scoring')
  }

  const tradeable = searchParams.get('tradeable') === '1'

  return (
    <div className="flex gap-3 flex-wrap items-center mb-5">
      <select
        value={searchParams.get('city') ?? ''}
        onChange={(e) => set('city', e.target.value)}
        className={selectClass}
      >
        <option value="">All Cities</option>
        {cities.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>

      <select
        value={searchParams.get('date') ?? ''}
        onChange={(e) => set('date', e.target.value)}
        className={selectClass}
      >
        <option value="">All Dates</option>
        {dates.map((d) => (
          <option key={d} value={d}>
            {new Date(d + 'T00:00:00Z').toLocaleDateString('en-US', {
              month: 'short',
              day: 'numeric',
              timeZone: 'UTC',
            })}
          </option>
        ))}
      </select>

      <select
        value={searchParams.get('tier') ?? ''}
        onChange={(e) => set('tier', e.target.value)}
        className={selectClass}
      >
        {tiers.map((t) => (
          <option key={t.value} value={t.value}>
            {t.label}
          </option>
        ))}
      </select>

      <select
        value={searchParams.get('minScore') ?? ''}
        onChange={(e) => set('minScore', e.target.value)}
        className={selectClass}
      >
        {minScores.map((s) => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </select>

      <button
        onClick={() => set('tradeable', tradeable ? '' : '1')}
        className={`px-3 py-2 text-sm rounded-lg border transition-colors ${
          tradeable
            ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40'
            : 'bg-zinc-800 text-zinc-400 border-zinc-700 hover:border-zinc-600'
        }`}
      >
        Tradeable Only
      </button>

      <select
        value={searchParams.get('sort') ?? ''}
        onChange={(e) => set('sort', e.target.value)}
        className={selectClass}
      >
        {sortOptions.map((s) => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </select>

      {activeCount > 0 && (
        <button
          onClick={clearAll}
          className="px-3 py-2 text-sm text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          Clear ({activeCount})
        </button>
      )}
    </div>
  )
}

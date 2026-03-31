'use client'

import { useRouter, useSearchParams } from 'next/navigation'

interface TradeFiltersProps {
  types: string[]
  statuses: string[]
  cities: string[]
}

const selectClass =
  'bg-zinc-800 border border-zinc-700 text-zinc-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-zinc-600 min-w-[130px]'

export default function TradeFilters({ types, statuses, cities }: TradeFiltersProps) {
  const router = useRouter()
  const searchParams = useSearchParams()

  const activeCount = ['type', 'status', 'city'].filter(
    (k) => searchParams.get(k)
  ).length

  function set(key: string, value: string) {
    const params = new URLSearchParams(searchParams.toString())
    if (value) {
      params.set(key, value)
    } else {
      params.delete(key)
    }
    router.push(`/trades?${params.toString()}`)
  }

  function clearAll() {
    router.push('/trades')
  }

  return (
    <div className="flex gap-3 flex-wrap items-center mb-5">
      <select
        value={searchParams.get('type') ?? ''}
        onChange={(e) => set('type', e.target.value)}
        className={selectClass}
      >
        <option value="">All Types</option>
        {types.map((t) => (
          <option key={t} value={t}>
            {t.replace('no_buy_', '').replace('no_limit_', 'limit ').replace('exit_', 'exit ')}
          </option>
        ))}
      </select>

      <select
        value={searchParams.get('status') ?? ''}
        onChange={(e) => set('status', e.target.value)}
        className={selectClass}
      >
        <option value="">All Statuses</option>
        {statuses.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>

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

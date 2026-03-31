export function formatUsd(n: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n)
}

export function formatCents(n: number): string {
  return `${(n * 100).toFixed(1)}c`
}

export function formatPnl(n: number): string {
  const sign = n >= 0 ? '+' : ''
  return `${sign}${formatUsd(n)}`
}

export function pnlColor(n: number): string {
  if (n > 0) return 'text-green-400'
  if (n < 0) return 'text-red-400'
  return 'text-zinc-400'
}

export function cityFromCityDate(cityDate: string): string {
  if (!cityDate) return '-'
  const parts = cityDate.split('|')
  return parts[0] || cityDate
}

export function dateFromCityDate(cityDate: string): string {
  if (!cityDate) return '-'
  const parts = cityDate.split('|')
  return parts[1] || ''
}

export function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  const diffHr = Math.floor(diffMs / 3600000)
  const diffDay = Math.floor(diffMs / 86400000)

  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  if (diffHr < 24) return `${diffHr}h ago`
  if (diffDay < 7) return `${diffDay}d ago`
  return date.toLocaleDateString()
}

export function phaseLabel(phase: number): string {
  const labels: Record<number, string> = {
    1: 'Learning',
    2: 'Standard',
    3: 'Scaled',
  }
  return labels[phase] || `Phase ${phase}`
}

export function exitStageLabel(stage: number): string {
  const labels: Record<number, string> = {
    0: 'None',
    1: 'Cut 33%',
    2: 'Cut 66%',
    3: 'Full Exit',
  }
  return labels[stage] || `Stage ${stage}`
}

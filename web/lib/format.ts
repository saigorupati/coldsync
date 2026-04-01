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
    4: 'YES Flip',
  }
  return labels[stage] || `Stage ${stage}`
}

// Kalshi URL builder
// Ticker: KXHIGHLAX-26MAR31-T67
// URL: https://kalshi.com/markets/kxhighlax/highest-temperature-in-los-angeles/kxhighlax-26mar31

const SERIES_SLUGS: Record<string, string> = {
  KXHIGHNY: 'highest-temperature-in-new-york',
  KXHIGHCHI: 'highest-temperature-in-chicago',
  KXHIGHMIA: 'highest-temperature-in-miami',
  KXHIGHLAX: 'highest-temperature-in-los-angeles',
  KXHIGHDEN: 'highest-temperature-in-denver',
  KXHIGHAUS: 'highest-temperature-in-austin',
  KXHIGHTATL: 'highest-temperature-in-atlanta',
  KXHIGHTBOS: 'highest-temperature-in-boston',
  KXHIGHTDAL: 'highest-temperature-in-dallas',
  KXHIGHTDC: 'highest-temperature-in-washington-dc',
  KXHIGHTHOU: 'highest-temperature-in-houston',
  KXHIGHTLV: 'highest-temperature-in-las-vegas',
  KXHIGHTMIN: 'highest-temperature-in-minneapolis',
  KXHIGHTNOLA: 'highest-temperature-in-new-orleans',
  KXHIGHTOKC: 'highest-temperature-in-oklahoma-city',
  KXHIGHTPHX: 'highest-temperature-in-phoenix',
  KXHIGHPHIL: 'highest-temperature-in-philadelphia',
  KXHIGHTSATX: 'highest-temperature-in-san-antonio',
  KXHIGHTSEA: 'highest-temperature-in-seattle',
  KXHIGHTSFO: 'highest-temperature-in-san-francisco',
}

export function kalshiMarketUrl(ticker: string): string {
  const parts = ticker.split('-')
  if (parts.length < 2) return `https://kalshi.com/markets/${ticker.toLowerCase()}`

  const series = parts[0].toUpperCase()
  const eventTicker = parts.slice(0, 2).join('-').toLowerCase()
  const seriesLower = series.toLowerCase()
  const slug = SERIES_SLUGS[series]

  if (slug) {
    return `https://kalshi.com/markets/${seriesLower}/${slug}/${eventTicker}`
  }
  return `https://kalshi.com/markets/${seriesLower}/${eventTicker}`
}

// Badge color helpers for trade types
export function typeColor(type: string): { bg: string; text: string } {
  if (type.includes('tier_A')) return { bg: 'bg-blue-900/50', text: 'text-blue-400' }
  if (type.includes('tier_B')) return { bg: 'bg-cyan-900/50', text: 'text-cyan-400' }
  if (type.includes('tier_C')) return { bg: 'bg-purple-900/50', text: 'text-purple-400' }
  if (type.includes('tier_D')) return { bg: 'bg-orange-900/50', text: 'text-orange-400' }
  if (type.includes('exit')) return { bg: 'bg-yellow-900/50', text: 'text-yellow-400' }
  if (type.includes('reconcile')) return { bg: 'bg-pink-900/50', text: 'text-pink-400' }
  return { bg: 'bg-zinc-800', text: 'text-zinc-400' }
}

export function statusColor(status: string): { bg: string; text: string } {
  switch (status) {
    case 'matched': return { bg: 'bg-green-900/50', text: 'text-green-400' }
    case 'resting': return { bg: 'bg-blue-900/50', text: 'text-blue-400' }
    case 'partial': return { bg: 'bg-yellow-900/50', text: 'text-yellow-400' }
    case 'dry_run': return { bg: 'bg-zinc-800', text: 'text-zinc-500' }
    case 'error': return { bg: 'bg-red-900/50', text: 'text-red-400' }
    case 'skipped': return { bg: 'bg-zinc-800', text: 'text-zinc-600' }
    default: return { bg: 'bg-zinc-800', text: 'text-zinc-400' }
  }
}

export function outcomeColor(outcome: string | null): string {
  if (outcome === 'No') return 'text-green-400' // We profit on No
  if (outcome === 'Yes') return 'text-red-400'
  if (outcome === 'Exited') return 'text-yellow-400'
  return 'text-zinc-400'
}

// Short label from question text
export function shortQuestion(question: string): string {
  if (!question) return '-'
  // Try to extract temp range like "74° to 75°" or "82° or above"
  const rangeMatch = question.match(/(\d+°\s*(?:to\s*\d+°|or\s+(?:above|below)))/i)
  if (rangeMatch) return rangeMatch[1]
  // Fallback: truncate
  return question.length > 40 ? question.slice(0, 37) + '...' : question
}

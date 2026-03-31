'use client'

import { useEffect, useState } from 'react'

interface LocalTimeProps {
  date: string | null | undefined
  format?: 'full' | 'short' | 'relative' | 'date-only' | 'time-only'
  className?: string
  fallback?: string
}

function formatFull(d: Date): string {
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

function formatShort(d: Date): string {
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

function formatDateOnly(d: Date): string {
  return d.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  })
}

function formatTimeOnly(d: Date): string {
  return d.toLocaleTimeString(undefined, {
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  })
}

function formatRelative(d: Date): string {
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  const diffHr = Math.floor(diffMs / 3600000)
  const diffDay = Math.floor(diffMs / 86400000)

  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  if (diffHr < 24) return `${diffHr}h ago`
  if (diffDay < 7) return `${diffDay}d ago`
  return formatDateOnly(d)
}

export default function LocalTime({ date, format = 'full', className, fallback = '-' }: LocalTimeProps) {
  const [display, setDisplay] = useState<string>('')

  useEffect(() => {
    if (!date) {
      setDisplay(fallback)
      return
    }
    const d = new Date(date)
    if (isNaN(d.getTime())) {
      setDisplay(fallback)
      return
    }
    switch (format) {
      case 'full':
        setDisplay(formatFull(d))
        break
      case 'short':
        setDisplay(formatShort(d))
        break
      case 'relative':
        setDisplay(formatRelative(d))
        break
      case 'date-only':
        setDisplay(formatDateOnly(d))
        break
      case 'time-only':
        setDisplay(formatTimeOnly(d))
        break
    }
  }, [date, format, fallback])

  // SSR: render empty to avoid hydration mismatch, client fills in
  if (!display) return <span className={className}>{fallback}</span>

  return <span className={className} title={date || undefined}>{display}</span>
}

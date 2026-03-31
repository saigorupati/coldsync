'use client'

import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts'

interface ChartData {
  date: string
  dailyPnl: number
  cumulativePnl: number
  balance: number
}

export default function PnlChart({ data }: { data: ChartData[] }) {
  return (
    <ResponsiveContainer width="100%" height={400}>
      <ComposedChart data={data} margin={{ top: 10, right: 10, bottom: 10, left: 10 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
        <XAxis
          dataKey="date"
          tick={{ fill: '#a1a1aa', fontSize: 12 }}
          axisLine={{ stroke: '#3f3f46' }}
          tickLine={false}
        />
        <YAxis
          tick={{ fill: '#a1a1aa', fontSize: 12 }}
          axisLine={{ stroke: '#3f3f46' }}
          tickLine={false}
          tickFormatter={(v) => `$${v}`}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: '#18181b',
            border: '1px solid #3f3f46',
            borderRadius: '8px',
            color: '#fafafa',
          }}
          formatter={(value: number, name: string) => [
            `$${value.toFixed(2)}`,
            name === 'cumulativePnl' ? 'Cumulative P&L' : 'Daily P&L',
          ]}
        />
        <Bar
          dataKey="dailyPnl"
          fill="#3b82f6"
          opacity={0.4}
          radius={[2, 2, 0, 0]}
        />
        <Line
          type="monotone"
          dataKey="cumulativePnl"
          stroke="#22c55e"
          strokeWidth={2}
          dot={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

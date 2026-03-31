interface StatCardProps {
  label: string
  value: string
  colorClass?: string
}

export default function StatCard({ label, value, colorClass }: StatCardProps) {
  return (
    <div className="bg-zinc-900 rounded-lg p-4 border border-zinc-800">
      <p className="text-zinc-400 text-sm mb-1">{label}</p>
      <p className={`text-2xl font-bold ${colorClass || 'text-white'}`}>{value}</p>
    </div>
  )
}

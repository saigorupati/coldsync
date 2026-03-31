import Link from 'next/link'

const navItems = [
  { href: '/', label: 'Overview' },
  { href: '/scoring', label: 'Scoring' },
  { href: '/positions', label: 'Positions' },
  { href: '/trades', label: 'Trades' },
  { href: '/pnl', label: 'P&L' },
]

export default function Sidebar() {
  return (
    <aside className="w-56 min-h-screen bg-zinc-900 border-r border-zinc-800 p-4 flex flex-col">
      <div className="mb-8">
        <h1 className="text-xl font-bold text-white tracking-tight">ColdSync</h1>
        <p className="text-xs text-zinc-500 mt-1">Kalshi Temperature Bot</p>
      </div>
      <nav className="flex flex-col gap-1">
        {navItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="px-3 py-2 rounded-md text-sm text-zinc-300 hover:text-white hover:bg-zinc-800 transition-colors"
          >
            {item.label}
          </Link>
        ))}
      </nav>
      <div className="mt-auto pt-4 border-t border-zinc-800">
        <p className="text-xs text-zinc-600">v0.1.0</p>
      </div>
    </aside>
  )
}

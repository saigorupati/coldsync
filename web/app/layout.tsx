import type { Metadata } from 'next'
import './globals.css'
import Sidebar from './components/sidebar'

export const metadata: Metadata = {
  title: 'ColdSync Dashboard',
  description: 'Kalshi temperature market bot monitoring',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        <div className="flex min-h-screen">
          <Sidebar />
          <main className="flex-1 p-6 overflow-auto">{children}</main>
        </div>
      </body>
    </html>
  )
}

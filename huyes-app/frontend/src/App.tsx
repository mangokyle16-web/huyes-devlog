import { useEffect, useState } from 'react'
import { BatchReport } from './pages/BatchReport'
import { Home } from './pages/Home'

export default function App() {
  const [batchId, setBatchId] = useState<string | null>(null)

  useEffect(() => {
    const m = window.location.pathname.match(/^\/b\/([A-Z0-9]{8})$/i)
    if (m) setBatchId(m[1].toUpperCase())
  }, [])

  if (batchId) return <BatchReport batchId={batchId} />
  return <Home />
}

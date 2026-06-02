import { useEffect, useState } from 'react'

interface BatchMeta {
  id: string
  created_at: string
  bean_count: number
  avg_bqs: number
  grade_dist: Record<string, number>
}

export function Home() {
  const [batches, setBatches] = useState<BatchMeta[]>([])

  useEffect(() => {
    fetch('/batches').then(r => r.json()).then(setBatches).catch(() => {})
  }, [])

  return (
    <div style={styles.root}>
      <header style={styles.header}>
        <span style={styles.logo}>☕ Huyes</span>
        <p style={styles.subtitle}>咖啡豆品質分析系統</p>
      </header>

      <section style={styles.section}>
        <h2 style={styles.sectionTitle}>最近批次</h2>
        {batches.length === 0 && (
          <p style={styles.empty}>尚無資料．掃描分豆機上的 QR Code 查看報告</p>
        )}
        {batches.map(b => (
          <a key={b.id} href={`/b/${b.id}`} style={styles.card}>
            <div style={styles.cardTop}>
              <span style={styles.batchId}>#{b.id}</span>
              <span style={styles.bqs}>{b.avg_bqs.toFixed(1)} 分</span>
            </div>
            <div style={styles.cardMeta}>
              {b.bean_count} 顆 · {new Date(b.created_at).toLocaleString('zh-TW')}
            </div>
            <div style={styles.gradePills}>
              {Object.entries(b.grade_dist).filter(([, v]) => v > 0).map(([g, n]) => (
                <span key={g} style={{ ...styles.pill, ...gradeColor(g) }}>
                  {g} {n}
                </span>
              ))}
            </div>
          </a>
        ))}
      </section>
    </div>
  )
}

function gradeColor(grade: string): React.CSSProperties {
  const map: Record<string, React.CSSProperties> = {
    '精選': { background: '#c8a96e', color: '#1a0a00' },
    '標準': { background: '#4a7c59', color: '#fff' },
    '混豆': { background: '#5a6a7a', color: '#fff' },
    '淘汰': { background: '#7a3a3a', color: '#fff' },
  }
  return map[grade] ?? { background: '#444', color: '#fff' }
}

const styles: Record<string, React.CSSProperties> = {
  root: { background: '#1a0a00', minHeight: '100vh', color: '#f0e6d0', fontFamily: 'system-ui, sans-serif', maxWidth: 480, margin: '0 auto', padding: '0 16px 40px' },
  header: { padding: '32px 0 16px', textAlign: 'center' },
  logo: { fontSize: 28, fontWeight: 700, letterSpacing: 2 },
  subtitle: { color: '#a08060', fontSize: 13, margin: '4px 0 0' },
  section: { marginTop: 24 },
  sectionTitle: { fontSize: 14, color: '#a08060', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 },
  empty: { color: '#706050', fontSize: 14, textAlign: 'center', marginTop: 40 },
  card: { display: 'block', background: '#2a1500', borderRadius: 12, padding: '16px', marginBottom: 12, textDecoration: 'none', color: 'inherit', border: '1px solid #3a2010' },
  cardTop: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  batchId: { fontFamily: 'monospace', fontSize: 16, color: '#c8a96e', fontWeight: 600 },
  bqs: { fontSize: 22, fontWeight: 700, color: '#f0e6d0' },
  cardMeta: { fontSize: 12, color: '#806040', marginTop: 4 },
  gradePills: { display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap' },
  pill: { fontSize: 12, padding: '2px 10px', borderRadius: 20, fontWeight: 500 },
}

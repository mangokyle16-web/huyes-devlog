import { useEffect, useRef, useState } from 'react'
import {
  PolarAngleAxis, PolarGrid, Radar, RadarChart,
  ResponsiveContainer,
} from 'recharts'
import { OriginCard } from '../components/OriginCard'
import { ShareCard } from '../components/ShareCard'

interface BeanRecord {
  bean_id: number
  bqs: number
  grade: string
  defect: number
  roast: number | null
  safety: number
  morphology: number
  reject: boolean
}

interface BatchData {
  id: string
  created_at: string
  bean_count: number
  avg_bqs: number
  grade_dist: Record<string, number>
  beans: BeanRecord[]
  spectra_vec: number[] | null
  notes: string
}

interface Origin {
  id: number
  name: string
  country: string
  region: string
  variety: string
  process: string
  description: string
  buy_url: string
  image_url: string
  similarity: number | null
}

const GRADE_ORDER = ['精選', '標準', '混豆', '淘汰']
const GRADE_COLOR: Record<string, string> = {
  '精選': '#c8a96e', '標準': '#4a9e6e', '混豆': '#7a8a9a', '淘汰': '#9a4a4a',
}

export function BatchReport({ batchId }: { batchId: string }) {
  const [data, setData] = useState<BatchData | null>(null)
  const [origins, setOrigins] = useState<Origin[]>([])
  const [tab, setTab] = useState<'report' | 'origin' | 'share'>('report')
  const [loading, setLoading] = useState(true)
  const shareRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetch(`/batch/${batchId}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [batchId])

  useEffect(() => {
    if (!data) return
    fetch(`/origins/search?batch_id=${batchId}&top_k=5`)
      .then(r => r.json())
      .then(setOrigins)
      .catch(() => {})
  }, [data, batchId])

  if (loading) return <div style={styles.loading}>分析中…</div>
  if (!data) return <div style={styles.loading}>找不到批次 #{batchId}</div>

  const radarData = [
    { subject: '缺陷', value: avgOf(data.beans, 'defect') },
    { subject: '烘焙', value: avgOf(data.beans, 'roast') ?? 50 },
    { subject: '食安', value: avgOf(data.beans, 'safety') },
    { subject: '形態', value: avgOf(data.beans, 'morphology') },
  ]

  return (
    <div style={styles.root}>
      {/* Header */}
      <header style={styles.header}>
        <a href="/" style={styles.back}>←</a>
        <span style={styles.logo}>☕ Huyes</span>
        <span style={styles.batchTag}>#{data.id}</span>
      </header>

      {/* BQS 大分數 */}
      <div style={styles.scoreBox}>
        <div style={styles.scoreNum}>{data.avg_bqs.toFixed(1)}</div>
        <div style={styles.scoreLabel}>Bean Quality Score</div>
        <div style={styles.scoreDate}>
          {new Date(data.created_at).toLocaleString('zh-TW')} · {data.bean_count} 顆
        </div>
      </div>

      {/* 等級分佈 */}
      <div style={styles.gradeRow}>
        {GRADE_ORDER.map(g => {
          const n = data.grade_dist[g] ?? 0
          const pct = data.bean_count > 0 ? (n / data.bean_count * 100).toFixed(0) : '0'
          return (
            <div key={g} style={styles.gradeCell}>
              <div style={{ ...styles.gradeDot, background: GRADE_COLOR[g] }} />
              <div style={styles.gradeNum}>{n}</div>
              <div style={styles.gradeName}>{g}</div>
              <div style={styles.gradePct}>{pct}%</div>
            </div>
          )
        })}
      </div>

      {/* Tab 切換 */}
      <div style={styles.tabs}>
        {(['report', 'origin', 'share'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            style={{ ...styles.tab, ...(tab === t ? styles.tabActive : {}) }}>
            {t === 'report' ? '分析報告' : t === 'origin' ? '相似產地' : '分享'}
          </button>
        ))}
      </div>

      {/* 報告 Tab */}
      {tab === 'report' && (
        <div>
          <ResponsiveContainer width="100%" height={220}>
            <RadarChart data={radarData}>
              <PolarGrid stroke="#3a2010" />
              <PolarAngleAxis dataKey="subject" tick={{ fill: '#a08060', fontSize: 12 }} />
              <Radar dataKey="value" stroke="#c8a96e" fill="#c8a96e" fillOpacity={0.25} />
            </RadarChart>
          </ResponsiveContainer>

          <h3 style={styles.subTitle}>各項分數</h3>
          {radarData.map(d => (
            <div key={d.subject} style={styles.scoreRow}>
              <span style={styles.scoreRowLabel}>{d.subject}</span>
              <div style={styles.scoreBar}>
                <div style={{ ...styles.scoreBarFill, width: `${d.value}%` }} />
              </div>
              <span style={styles.scoreRowVal}>{d.value.toFixed(1)}</span>
            </div>
          ))}
        </div>
      )}

      {/* 產地 Tab */}
      {tab === 'origin' && (
        <div>
          {origins.length === 0
            ? <p style={styles.empty}>正在建立產地資料庫，敬請期待</p>
            : origins.map(o => <OriginCard key={o.id} origin={o} />)
          }
        </div>
      )}

      {/* 分享 Tab */}
      {tab === 'share' && (
        <ShareCard data={data} radarData={radarData} cardRef={shareRef} />
      )}
    </div>
  )
}

function avgOf(beans: BeanRecord[], key: keyof BeanRecord): number {
  const vals = beans.map(b => b[key] as number).filter(v => v != null)
  return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0
}

const styles: Record<string, React.CSSProperties> = {
  root: { background: '#1a0a00', minHeight: '100vh', color: '#f0e6d0', fontFamily: 'system-ui, sans-serif', maxWidth: 480, margin: '0 auto', padding: '0 16px 60px' },
  loading: { background: '#1a0a00', minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#a08060', fontSize: 16 },
  header: { display: 'flex', alignItems: 'center', padding: '16px 0', gap: 12 },
  back: { color: '#c8a96e', fontSize: 20, textDecoration: 'none' },
  logo: { fontWeight: 700, fontSize: 18, flex: 1 },
  batchTag: { fontFamily: 'monospace', fontSize: 13, color: '#a08060', background: '#2a1500', padding: '2px 8px', borderRadius: 6 },
  scoreBox: { textAlign: 'center', padding: '24px 0 16px' },
  scoreNum: { fontSize: 64, fontWeight: 800, color: '#c8a96e', lineHeight: 1 },
  scoreLabel: { fontSize: 13, color: '#a08060', marginTop: 4, letterSpacing: 1 },
  scoreDate: { fontSize: 12, color: '#706050', marginTop: 8 },
  gradeRow: { display: 'flex', justifyContent: 'space-around', padding: '16px 0', borderTop: '1px solid #3a2010', borderBottom: '1px solid #3a2010' },
  gradeCell: { textAlign: 'center' },
  gradeDot: { width: 10, height: 10, borderRadius: '50%', margin: '0 auto 4px' },
  gradeNum: { fontSize: 22, fontWeight: 700 },
  gradeName: { fontSize: 11, color: '#a08060' },
  gradePct: { fontSize: 11, color: '#706050' },
  tabs: { display: 'flex', gap: 0, marginTop: 20, borderBottom: '1px solid #3a2010' },
  tab: { flex: 1, background: 'none', border: 'none', color: '#806040', padding: '10px 0', fontSize: 14, cursor: 'pointer' },
  tabActive: { color: '#c8a96e', borderBottom: '2px solid #c8a96e' },
  subTitle: { fontSize: 13, color: '#a08060', marginTop: 16, marginBottom: 10 },
  scoreRow: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 },
  scoreRowLabel: { width: 36, fontSize: 12, color: '#a08060' },
  scoreBar: { flex: 1, height: 6, background: '#3a2010', borderRadius: 3, overflow: 'hidden' },
  scoreBarFill: { height: '100%', background: '#c8a96e', borderRadius: 3 },
  scoreRowVal: { width: 36, textAlign: 'right', fontSize: 12, color: '#f0e6d0' },
  empty: { color: '#706050', fontSize: 14, textAlign: 'center', marginTop: 40 },
}

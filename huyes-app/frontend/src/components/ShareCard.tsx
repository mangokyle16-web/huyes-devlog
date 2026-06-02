import { type RefObject } from 'react'

interface RadarPoint { subject: string; value: number }
interface BatchData {
  id: string; avg_bqs: number; bean_count: number
  grade_dist: Record<string, number>; created_at: string
}

interface Props {
  data: BatchData
  radarData: RadarPoint[]
  cardRef: RefObject<HTMLDivElement | null>
}

const GRADE_COLOR: Record<string, string> = {
  '精選': '#c8a96e', '標準': '#4a9e6e', '混豆': '#7a8a9a', '淘汰': '#9a4a4a',
}

export function ShareCard({ data, radarData, cardRef }: Props) {
  const handleShare = async () => {
    const text = `☕ Huyes 咖啡豆分析報告 #${data.id}\n品質分數：${data.avg_bqs.toFixed(1)} 分\n${data.bean_count} 顆豆子 · ${Object.entries(data.grade_dist).filter(([,v])=>v>0).map(([g,n])=>`${g}${n}顆`).join(' ')}`
    if (navigator.share) {
      await navigator.share({ title: 'Huyes 咖啡豆報告', text, url: window.location.href })
    } else {
      await navigator.clipboard.writeText(text + '\n' + window.location.href)
      alert('已複製到剪貼簿')
    }
  }

  return (
    <div>
      {/* 視覺化分享卡片 */}
      <div ref={cardRef} style={styles.card}>
        <div style={styles.cardHeader}>
          <span style={styles.cardLogo}>☕ Huyes</span>
          <span style={styles.cardBatch}>#{data.id}</span>
        </div>

        <div style={styles.cardScore}>{data.avg_bqs.toFixed(1)}</div>
        <div style={styles.cardScoreLabel}>Bean Quality Score</div>

        <div style={styles.cardBars}>
          {radarData.map(d => (
            <div key={d.subject} style={styles.cardBarRow}>
              <span style={styles.cardBarLabel}>{d.subject}</span>
              <div style={styles.cardBarTrack}>
                <div style={{ ...styles.cardBarFill, width: `${d.value}%` }} />
              </div>
              <span style={styles.cardBarVal}>{d.value.toFixed(0)}</span>
            </div>
          ))}
        </div>

        <div style={styles.cardGrades}>
          {Object.entries(data.grade_dist).filter(([,v])=>v>0).map(([g,n]) => (
            <span key={g} style={{ ...styles.cardPill, background: GRADE_COLOR[g], color: g === '精選' ? '#1a0a00' : '#fff' }}>
              {g} {n}
            </span>
          ))}
        </div>

        <div style={styles.cardFooter}>
          {new Date(data.created_at).toLocaleDateString('zh-TW')} · {data.bean_count} 顆
        </div>
      </div>

      <button onClick={handleShare} style={styles.shareBtn}>
        分享報告
      </button>
      <p style={styles.shareHint}>透過 LINE / Instagram / Twitter 分享</p>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  card: { background: 'linear-gradient(145deg, #2a1500, #1a0a00)', borderRadius: 16, padding: '24px 20px', border: '1px solid #c8a96e33', marginTop: 16 },
  cardHeader: { display: 'flex', justifyContent: 'space-between', marginBottom: 20 },
  cardLogo: { fontWeight: 700, fontSize: 16, color: '#c8a96e' },
  cardBatch: { fontFamily: 'monospace', fontSize: 12, color: '#806040' },
  cardScore: { fontSize: 56, fontWeight: 800, color: '#c8a96e', textAlign: 'center', lineHeight: 1 },
  cardScoreLabel: { textAlign: 'center', fontSize: 11, color: '#a08060', letterSpacing: 1, marginTop: 4, marginBottom: 20 },
  cardBars: { display: 'flex', flexDirection: 'column', gap: 8 },
  cardBarRow: { display: 'flex', alignItems: 'center', gap: 8 },
  cardBarLabel: { width: 32, fontSize: 11, color: '#a08060' },
  cardBarTrack: { flex: 1, height: 5, background: '#3a2010', borderRadius: 3, overflow: 'hidden' },
  cardBarFill: { height: '100%', background: '#c8a96e', borderRadius: 3 },
  cardBarVal: { width: 28, textAlign: 'right', fontSize: 11, color: '#f0e6d0' },
  cardGrades: { display: 'flex', gap: 6, marginTop: 16, flexWrap: 'wrap' },
  cardPill: { fontSize: 11, padding: '2px 10px', borderRadius: 20, fontWeight: 600 },
  cardFooter: { fontSize: 11, color: '#604030', marginTop: 12, textAlign: 'center' },
  shareBtn: { width: '100%', background: '#c8a96e', color: '#1a0a00', border: 'none', borderRadius: 24, padding: '14px', fontSize: 16, fontWeight: 700, cursor: 'pointer', marginTop: 20 },
  shareHint: { textAlign: 'center', fontSize: 12, color: '#706050', marginTop: 8 },
}

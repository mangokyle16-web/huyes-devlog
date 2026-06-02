interface Origin {
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

export function OriginCard({ origin }: { origin: Origin }) {
  return (
    <div style={styles.card}>
      {origin.image_url && (
        <img src={origin.image_url} alt={origin.name} style={styles.img} />
      )}
      <div style={styles.body}>
        <div style={styles.top}>
          <span style={styles.name}>{origin.name}</span>
          {origin.similarity != null && (
            <span style={styles.sim}>{(origin.similarity * 100).toFixed(0)}% 相似</span>
          )}
        </div>
        <div style={styles.meta}>
          {origin.country} · {origin.region} · {origin.variety} · {origin.process}
        </div>
        {origin.description && (
          <p style={styles.desc}>{origin.description}</p>
        )}
        {origin.buy_url && (
          <a href={origin.buy_url} target="_blank" rel="noreferrer" style={styles.buyBtn}>
            前往購買 →
          </a>
        )}
      </div>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  card: { background: '#2a1500', borderRadius: 12, overflow: 'hidden', marginTop: 12, border: '1px solid #3a2010' },
  img: { width: '100%', height: 140, objectFit: 'cover' },
  body: { padding: '12px 14px' },
  top: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  name: { fontSize: 16, fontWeight: 600, color: '#f0e6d0' },
  sim: { fontSize: 12, color: '#c8a96e', background: '#3a2800', padding: '2px 8px', borderRadius: 10 },
  meta: { fontSize: 12, color: '#a08060', marginTop: 4 },
  desc: { fontSize: 13, color: '#c0b0a0', marginTop: 8, lineHeight: 1.5 },
  buyBtn: { display: 'inline-block', marginTop: 10, background: '#c8a96e', color: '#1a0a00', padding: '6px 16px', borderRadius: 20, fontSize: 13, fontWeight: 600, textDecoration: 'none' },
}

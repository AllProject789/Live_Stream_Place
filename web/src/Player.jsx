import Card from './Card'
import LivePlayer from './LivePlayer'
import SatelliteView from './SatelliteView'
import { cat } from './lib/categories'
import { recommend } from './lib/streams'

export default function Player({ stream, pool, onSelect, onClose, scene, onScene }) {
  if (!stream) return null
  const c = cat(stream.category)
  const nearby = recommend(stream, pool, 20)

  return (
    <aside className="panel">
      <div className="panel-grab" />
      <button className="panel-close" onClick={onClose} aria-label="Close">
        ✕
      </button>

      <LivePlayer key={stream.id} videoId={stream.id} title={stream.title} />

      <div className="panel-head">
        <h2>{stream.title}</h2>
        <div className="panel-meta">
          <span className="tag" style={{ '--c': c.color }}>
            {c.emoji} {c.label}
          </span>
          <span className="dim">{stream.channel}</span>
        </div>
        {stream.place && <p className="panel-place">📍 {stream.place}</p>}
        <a
          className="yt-link"
          href={`https://www.youtube.com/watch?v=${stream.id}`}
          target="_blank"
          rel="noreferrer"
        >
          Open on YouTube ↗
        </a>
      </div>

      <SatelliteView
        key={stream.id}
        stream={stream}
        overlay={scene}
        onOverlay={onScene}
      />

      <div className="panel-recs">
        <h3>{stream.lat != null ? 'Nearby live cams' : 'More cams like this'}</h3>
        <div className="rec-grid">
          {nearby.map((s) => (
            <Card key={s.id} stream={s} onSelect={onSelect} />
          ))}
        </div>
      </div>
    </aside>
  )
}

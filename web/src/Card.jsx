import { cat } from './lib/categories'
import { shortPlace } from './lib/streams'
import { km } from './lib/geo'

export default function Card({ stream, active, onSelect }) {
  const c = cat(stream.category)
  const place = shortPlace(stream.place)
  return (
    <button
      className={`card${active ? ' is-active' : ''}`}
      onClick={() => onSelect(stream)}
      title={stream.title}
    >
      <span className="card-thumb">
        <img src={stream.thumbnail} alt="" loading="lazy" />
        <span className="live-dot">LIVE</span>
        {stream._dist != null && <span className="card-dist">{km(stream._dist)}</span>}
      </span>
      <span className="card-body">
        <span className="card-title">{stream.title}</span>
        <span className="card-meta">
          <span className="tag" style={{ '--c': c.color }}>
            {c.emoji} {c.label}
          </span>
          <span className="card-place">{place || stream.channel}</span>
        </span>
      </span>
    </button>
  )
}

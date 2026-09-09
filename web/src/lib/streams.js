import { haversine } from './geo'

// The file build.py / refresh.py writes. When deploying, set in .env:
// VITE_STREAMS_URL=https://raw.githubusercontent.com/<user>/<repo>/main/streams.json
export const STREAMS_URL = import.meta.env.VITE_STREAMS_URL || '/streams.json'

export async function fetchStreams() {
  const res = await fetch(STREAMS_URL, { cache: 'no-cache' })
  if (!res.ok) throw new Error(`could not load streams.json (HTTP ${res.status})`)
  const data = await res.json()
  const streams = (data.streams || []).filter((s) => s && s.id)
  return { updatedAt: data.updated_at || null, streams }
}

// Short name from a place: "Times Square, Manhattan, New York County, New York, USA" -> "Times Square, USA"
export function shortPlace(place) {
  if (!place) return null
  const bits = place.split(',').map((b) => b.trim()).filter(Boolean)
  if (bits.length <= 2) return bits.join(', ')
  return `${bits[0]}, ${bits[bits.length - 1]}`
}

export function matches(s, q) {
  if (!q) return true
  const needle = q.toLowerCase()
  return (
    s.title?.toLowerCase().includes(needle) ||
    s.place?.toLowerCase().includes(needle) ||
    s.channel?.toLowerCase().includes(needle)
  )
}

/** 20 recommendations for the selected cam.
 *  If the location is known, nearest first (same idea as search.py),
 *  otherwise same category / channel. */
export function recommend(selected, pool, limit = 20) {
  const rest = pool.filter((s) => s.id !== selected?.id)
  if (!selected) return rest.slice(0, limit)

  if (selected.lat != null && selected.lon != null) {
    const withGeo = rest
      .filter((s) => s.lat != null && s.lon != null)
      .map((s) => ({ ...s, _dist: haversine(selected.lat, selected.lon, s.lat, s.lon) }))
      .sort((a, b) => a._dist - b._dist)
    if (withGeo.length >= limit) return withGeo.slice(0, limit)
    return [...withGeo, ...rest.filter((s) => s.lat == null)].slice(0, limit)
  }

  const score = (s) =>
    (s.channel === selected.channel ? 2 : 0) + (s.category === selected.category ? 1 : 0)
  return [...rest].sort((a, b) => score(b) - score(a)).slice(0, limit)
}

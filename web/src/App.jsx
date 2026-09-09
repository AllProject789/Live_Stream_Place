import { useEffect, useMemo, useState } from 'react'
import MapView from './MapView'
import Player from './Player'
import Card from './Card'
import { CATEGORY, CATEGORY_ORDER } from './lib/categories'
import { fetchStreams, matches } from './lib/streams'
import './styles.css'

export default function App() {
  const [data, setData] = useState({ streams: [], updatedAt: null })
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(null)   // category filter
  const [selected, setSelected] = useState(null)
  const [scene, setScene] = useState(null)     // Sentinel-2 scene shown on the map
  const [dockOpen, setDockOpen] = useState(true)
  // Read it on the first render - the effect below strips ?v from the URL
  const [wantedId] = useState(() => new URLSearchParams(window.location.search).get('v'))

  useEffect(() => {
    fetchStreams()
      .then((d) => {
        setData(d)
        // Opened with ?v=<videoId>: show that cam straight away (shareable link)
        if (wantedId) setSelected(d.streams.find((s) => s.id === wantedId) || null)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [wantedId])

  // Keep the URL in step with the selection (replace, so Back still works)
  useEffect(() => {
    const url = new URL(window.location.href)
    if (selected) url.searchParams.set('v', selected.id)
    else url.searchParams.delete('v')
    window.history.replaceState(null, '', url)
  }, [selected])

  // A scene is picked for one cam's coordinates, so it must not follow the
  // selection to the next cam. Every path that changes the cam goes through here.
  const choose = (s) => {
    setSelected(s)
    setScene(null)
  }

  const visible = useMemo(
    () => data.streams.filter((s) => (!active || s.category === active) && matches(s, query)),
    [data.streams, active, query],
  )

  // streams.json now only carries cams with lat/lon; this filter is just a
  // guard so an older file cannot break the app.
  const onMap = useMemo(() => visible.filter((s) => s.lat != null), [visible])

  // The 20 shown at the bottom when nothing is selected - round-robin by category
  const featured = useMemo(() => {
    const buckets = new Map()
    for (const s of visible) {
      const k = s.category || 'other'
      if (!buckets.has(k)) buckets.set(k, [])
      buckets.get(k).push(s)
    }
    const out = []
    for (let i = 0; out.length < 20; i++) {
      let added = false
      for (const list of buckets.values()) {
        if (list[i]) {
          out.push(list[i])
          added = true
          if (out.length === 20) break
        }
      }
      if (!added) break
    }
    return out
  }, [visible])

  const counts = useMemo(() => {
    const c = {}
    for (const s of data.streams) c[s.category] = (c[s.category] || 0) + 1
    return c
  }, [data.streams])

  // Esc closes the panel
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== 'Escape') return
      setSelected(null)
      setScene(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const dock = selected ? [] : featured

  return (
    <div className={`app${selected ? ' has-panel' : ''}`}>
      <MapView
        streams={onMap}
        selected={selected}
        onSelect={choose}
        panelOpen={!!selected}
        scene={scene}
      />

      <header className="topbar">
        <div className="brand">
          <span className="brand-dot" />
          <div>
            <strong>Live Cams</strong>
            <small className="count">
              {loading
                ? 'Loading…'
                : query || active
                  ? `${visible.length} / ${data.streams.length} cams`
                  : `${data.streams.length} live cams`}
            </small>
            {data.updatedAt && (
              <small className="stamp">
                updated: {new Date(data.updatedAt).toLocaleString('en-GB')}
              </small>
            )}
          </div>
        </div>

        <input
          className="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search a place, channel or title…"
        />

        <div className="chips">
          <button className={`chip${!active ? ' on' : ''}`} onClick={() => setActive(null)}>
            All
          </button>
          {CATEGORY_ORDER.filter((k) => counts[k]).map((k) => (
            <button
              key={k}
              className={`chip${active === k ? ' on' : ''}`}
              style={{ '--c': CATEGORY[k].color }}
              onClick={() => setActive(active === k ? null : k)}
            >
              {CATEGORY[k].emoji} {CATEGORY[k].label}
              <em>{counts[k]}</em>
            </button>
          ))}
        </div>
      </header>

      {error && <div className="error">⚠️ {error}</div>}

      {!selected && !loading && (
        <section className={`dock${dockOpen ? '' : ' collapsed'}`}>
          <div className="dock-head">
            <h3>
              {query || active ? 'Matches' : 'Watch now'}
              <span className="dim"> · {Math.min(dock.length, 20)}</span>
            </h3>
            <button className="ghost" onClick={() => setDockOpen((v) => !v)}>
              {dockOpen ? 'Hide ⌄' : 'Show ⌃'}
            </button>
          </div>
          <div className="dock-row">
            {dock.map((s) => (
              <Card key={s.id} stream={s} onSelect={choose} />
            ))}
            {!dock.length && <p className="empty">Nothing found - try another name.</p>}
          </div>
        </section>
      )}

      <Player
        stream={selected}
        pool={visible.length > 1 ? visible : data.streams}
        onSelect={choose}
        onClose={() => choose(null)}
        scene={scene}
        onScene={setScene}
      />

    </div>
  )
}

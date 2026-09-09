import { useEffect, useState } from 'react'
import {
  CLOUD_LIMIT,
  googleMapsUrl,
  sceneCrop,
  scenes,
  usable,
  worthIt,
} from './lib/satellite'

/** "What does this place look like now?" - the newest Sentinel-2 pass over the
 *  selected cam, as a still, with a toggle to lay it over the map.
 *
 *  The lookup happens here rather than in build.py because the answer changes
 *  every few days and only ever concerns the one cam that was clicked. Nothing
 *  is added to streams.json: lat/lon is the only input, and that is already in
 *  every row.
 */
export default function SatelliteView({ stream, overlay, onOverlay }) {
  const [list, setList] = useState(null)     // null = still loading
  const [error, setError] = useState(null)
  const [pick, setPick] = useState(null)     // the scene being shown
  const [imgFailed, setImgFailed] = useState(false)

  const { lat, lon } = stream

  // Player passes key={stream.id}, so this component remounts when the cam
  // changes - the state above starts fresh and needs no resetting here. (Same
  // reason LivePlayer gives for its own key.)
  useEffect(() => {
    if (lat == null || lon == null) return
    // A quick run through several cams must not let a slow earlier response
    // overwrite the current one.
    let live = true

    scenes(lat, lon)
      .then((found) => {
        if (!live) return
        setList(found)
        setPick(usable(found) || found[0] || null)
      })
      .catch((e) => live && setError(e.message))

    return () => {
      live = false
    }
  }, [lat, lon])

  if (lat == null) return null

  const cloudy = pick && pick.cloud > CLOUD_LIMIT
  const coarse = !worthIt(stream.category)

  return (
    <div className="sat">
      <h3>
        Satellite
        {pick && <span className="dim"> · {pick.date}</span>}
      </h3>

      {list === null && !error && <p className="sat-msg">Looking for a recent pass…</p>}
      {error && <p className="sat-msg">Could not reach the satellite index.</p>}
      {list?.length === 0 && <p className="sat-msg">No pass over this spot in the last 45 days.</p>}

      {pick && (
        <>
          <div className="sat-shot">
            {imgFailed ? (
              <p className="sat-msg">That scene could not be rendered.</p>
            ) : (
              <img
                key={pick.id}
                src={sceneCrop(pick.cog, lat, lon, { km: 4 })}
                alt={`Sentinel-2 view of ${stream.place || stream.title} on ${pick.date}`}
                loading="lazy"
                onError={() => setImgFailed(true)}
              />
            )}
            <span className="sat-scale">4 km across · 10 m/px</span>
          </div>

          <p className="sat-facts">
            <span className={`sat-cloud${cloudy ? ' bad' : ''}`}>
              {cloudy ? '☁️' : '🛰️'} {pick.cloud}% cloud
            </span>
            <span className="dim">{daysAgo(pick.date)}</span>
          </p>

          {cloudy && (
            <p className="sat-msg">
              Every recent pass here was cloudy - this is the clearest of them.
            </p>
          )}
          {coarse && (
            <p className="sat-msg">
              At 10 m a {stream.category} cam's surroundings are only a few pixels
              wide. Google Maps below is far sharper, just years older.
            </p>
          )}

          <div className="sat-actions">
            <button
              className={`sat-btn${overlay ? ' on' : ''}`}
              onClick={() => onOverlay(overlay ? null : pick)}
            >
              {overlay ? 'Hide from map' : 'Show on map'}
            </button>
            <a className="sat-btn" href={googleMapsUrl(lat, lon)} target="_blank" rel="noreferrer">
              Google Maps ↗
            </a>
          </div>

          {list.length > 1 && (
            <div className="sat-dates">
              {list.slice(0, 6).map((s) => (
                <button
                  key={s.id}
                  className={`sat-date${s.id === pick.id ? ' on' : ''}`}
                  title={`${s.cloud}% cloud`}
                  onClick={() => {
                    setPick(s)
                    setImgFailed(false)
                    if (overlay) onOverlay(s)   // keep the map in step
                  }}
                >
                  {s.date.slice(5)}
                  <em className={s.cloud > CLOUD_LIMIT ? 'bad' : ''}>{s.cloud}%</em>
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function daysAgo(date) {
  const d = Math.round((Date.now() - new Date(`${date}T12:00:00Z`)) / 864e5)
  return d <= 0 ? 'today' : d === 1 ? 'yesterday' : `${d} days ago`
}

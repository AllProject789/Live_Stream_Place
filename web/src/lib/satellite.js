// Satellite imagery for the cam you clicked.
//
// Two sources, because they answer different questions:
//
//   Esri World Imagery  - a basemap. ~0.5 m, so you can see streets and cars,
//                         but it is a mosaic compiled over years: detailed and
//                         old, with no usable per-tile date.
//   Sentinel-2 (ESA)    - 10 m, a fresh pass every ~5 days, free and dated.
//                         Coarser, but it is the only one that can answer
//                         "what does this place look like *now*".
//
// Sentinel-2 needs two calls, and neither one can do the other's job:
//
//   STAC (Earth Search) - which passes exist over this point, on which day, and
//                         how cloudy each was. It cannot draw a map: its own
//                         preview.jpg covers a whole 110 km granule.
//   TiTiler             - turns one scene's GeoTIFF into map tiles or a cropped
//                         PNG. It cannot tell us which scenes exist.
//
// So STAC picks the scene, TiTiler renders it.
//
// NASA GIBS was the obvious third option (keyless, date-parameterised WMTS) and
// was rejected: its HLS layer is 30 m, runs ~2 days behind, and its coverage is
// patchy in a way you cannot detect from the HTTP status - a day with no granule
// still answers 200, with a 334-byte transparent PNG. Reading STAC and drawing
// with TiTiler gives 10 m and a date we can actually trust.

// ---------------------------------------------------------------- basemap

// Note the tile order: {z}/{y}/{x}. OSM is {z}/{x}/{y}. Swap them by accident
// and tiles still load with no error - they are just of the wrong place.
export const ESRI_SAT =
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
export const ESRI_ATTR =
  'Imagery &copy; <a href="https://www.esri.com/">Esri</a>, Maxar, Earthstar Geographics'

// ---------------------------------------------------------------- Sentinel-2

const STAC = 'https://earth-search.aws.element84.com/v1/search'
const TITILER = 'https://titiler.xyz'

export const SENTINEL_ATTR =
  'Contains modified <a href="https://dataspace.copernicus.eu/">Copernicus Sentinel</a> data'

// A pass at 60% cloud is a white smudge. 40% still lets partly-cloudy days
// through, which are usually fine away from the cloud itself - and a clear day
// from last week beats an unusable one from yesterday.
export const CLOUD_LIMIT = 40

// The COG is 10 m/px, so z14 is about its native limit. Past that Leaflet
// upscales instead of hiding the layer (maxZoom without maxNativeZoom would
// make the imagery vanish the moment you zoom in on a pin).
const NATIVE_ZOOM = 14

// Session cache, keyed by rounded coordinates. Nothing is written to disk on
// purpose: unlike data/geo_cache.json - where Times Square's coordinates never
// change - the newest pass changes every few days, so a stored answer would go
// stale and quietly start reporting old imagery as "latest".
const cache = new Map()

/** Recent Sentinel-2 scenes over one point, newest first.
 *  -> [{ id, date, cloud, cog }]   date = YYYY-MM-DD, cog = GeoTIFF URL */
export async function scenes(lat, lon, { days = 45, limit = 8 } = {}) {
  const key = `${lat.toFixed(3)},${lon.toFixed(3)}`
  if (cache.has(key)) return cache.get(key)

  // Earth Search rejects a plain date ("2026-08-10/..") with HTTP 400 and the
  // message "does not match RFC3339 format" - it wants the full timestamp.
  const from = new Date(Date.now() - days * 864e5).toISOString().replace(/\.\d+Z$/, 'Z')

  const res = await fetch(STAC, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      collections: ['sentinel-2-l2a'],
      // GeoJSON order is [lon, lat] - the opposite of Leaflet's [lat, lon]
      intersects: { type: 'Point', coordinates: [lon, lat] },
      datetime: `${from}/..`,
      limit,
      sortby: [{ field: 'properties.datetime', direction: 'desc' }],
    }),
  })
  if (!res.ok) throw new Error(`satellite search failed (HTTP ${res.status})`)

  const { features = [] } = await res.json()
  const out = features
    .map((f) => ({
      id: f.id,
      date: f.properties.datetime.slice(0, 10),
      cloud: Math.round(f.properties['eo:cloud_cover'] ?? 100),
      // Take the href from the API rather than building the path by hand -
      // 'visual' is the true-colour GeoTIFF and the bucket layout is not ours.
      cog: f.assets?.visual?.href,
    }))
    .filter((s) => s.cog)

  cache.set(key, out)
  return out
}

/** Newest scene clear enough to be worth showing, else null. */
export const usable = (list) => list?.find((s) => s.cloud <= CLOUD_LIMIT) || null

/** Leaflet tile template for one scene. */
export const sceneTiles = (cog) =>
  `${TITILER}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=${encodeURIComponent(cog)}`

export const sceneTileOpts = { maxNativeZoom: NATIVE_ZOOM, maxZoom: 19 }

/** A square of `km` around a point, as [minLon, minLat, maxLon, maxLat]. */
function bboxAround(lat, lon, km) {
  const dLat = km / 2 / 111.32
  const dLon = dLat / Math.max(Math.cos((lat * Math.PI) / 180), 0.01)
  return [lon - dLon, lat - dLat, lon + dLon, lat + dLat]
}

/** One cropped PNG of the place - used for the still preview in the panel.
 *  TiTiler serves no CORS headers, so this may only ever be an <img> src;
 *  fetch() would be blocked. Errors are caught with the img's onError. */
export function sceneCrop(cog, lat, lon, { km = 4, size = 560 } = {}) {
  const [w, s, e, n] = bboxAround(lat, lon, km).map((v) => v.toFixed(5))
  const q = new URLSearchParams({ url: cog, width: size, height: size })
  return `${TITILER}/cog/bbox/${w},${s},${e},${n}.png?${q}`
}

/** How much detail 10 m/px really gives, per category - so the UI can be
 *  honest instead of letting people expect Google Maps. */
export const worthIt = (category) =>
  !['city', 'railway', 'airport', 'other'].includes(category)

// Google's own satellite tiles are deliberately not used: scraping them breaks
// their terms. Sending the user to Google Maps is fine, and gets them 0.5 m.
export const googleMapsUrl = (lat, lon) =>
  `https://www.google.com/maps/@?api=1&map_action=map&center=${lat},${lon}&basemap=satellite&zoom=17`

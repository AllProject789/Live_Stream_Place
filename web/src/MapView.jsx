import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import 'leaflet.markercluster'
import 'leaflet.markercluster/dist/MarkerCluster.css'
import { cat } from './lib/categories'
import { ESRI_ATTR, ESRI_SAT, SENTINEL_ATTR, sceneTileOpts, sceneTiles } from './lib/satellite'

// OpenStreetMap's free tiles (no key). The dark look comes from a CSS filter -
// see `.tiles-dark` in styles.css. That filter is scoped to this layer by
// class: applied to the whole tile pane it would invert the satellite imagery
// too, turning it into a photo negative.
// For heavier traffic, run your own tile server or use a paid provider (OSM policy).
const TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'

const pinIcon = (category) =>
  L.divIcon({
    className: 'pin',
    html: `<i style="--c:${cat(category).color}"></i>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  })

const clusterIcon = (cluster) => {
  const n = cluster.getChildCount()
  const size = n < 10 ? 34 : n < 100 ? 42 : 52
  return L.divIcon({
    html: `<div class="cluster-inner">${n}</div>`,
    className: 'cluster',
    iconSize: [size, size],
  })
}

export default function MapView({ streams, selected, onSelect, panelOpen, scene }) {
  const holder = useRef(null)
  const map = useRef(null)
  const cluster = useRef(null)
  const marks = useRef(new Map())
  const ring = useRef(null)
  const sat = useRef(null)
  const select = useRef(onSelect)

  // Marker click handlers always see the latest onSelect
  useEffect(() => {
    select.current = onSelect
  }, [onSelect])

  // The map is built once
  useEffect(() => {
    const m = L.map(holder.current, {
      center: [22, 12],
      zoom: 3,
      minZoom: 2,
      zoomControl: false,
      worldCopyJump: true,
    })
    // Two basemaps. `className` is what lets styles.css darken only the OSM one.
    const plain = L.tileLayer(TILES, { attribution: ATTR, maxZoom: 19, className: 'tiles-dark' })
    const photo = L.tileLayer(ESRI_SAT, { attribution: ESRI_ATTR, maxZoom: 19, className: 'tiles-photo' })
    plain.addTo(m)
    L.control.layers({ Map: plain, Satellite: photo }, {}, { position: 'bottomright' }).addTo(m)
    L.control.zoom({ position: 'bottomright' }).addTo(m)

    const c = L.markerClusterGroup({
      maxClusterRadius: 55,
      showCoverageOnHover: false,
      chunkedLoading: true,
      iconCreateFunction: clusterIcon,
    })
    m.addLayer(c)

    map.current = m
    cluster.current = c
    const registry = marks.current
    return () => {
      m.remove()
      map.current = null
      cluster.current = null
      registry.clear()
    }
  }, [])

  // Rebuild the pins whenever the filter changes
  useEffect(() => {
    const c = cluster.current
    if (!c) return
    c.clearLayers()
    marks.current.clear()
    const layers = []
    for (const s of streams) {
      if (s.lat == null || s.lon == null) continue
      const mk = L.marker([s.lat, s.lon], { icon: pinIcon(s.category), title: s.title })
      mk.on('click', () => select.current(s))
      marks.current.set(s.id, mk)
      layers.push(mk)
    }
    c.addLayers(layers)
  }, [streams])

  // Fly to the selected cam and ring it
  useEffect(() => {
    const m = map.current
    if (!m) return
    if (ring.current) {
      m.removeLayer(ring.current)
      ring.current = null
    }
    if (!selected || selected.lat == null) return

    ring.current = L.circleMarker([selected.lat, selected.lon], {
      radius: 16,
      color: cat(selected.category).color,
      weight: 2,
      opacity: 0.9,
      fillOpacity: 0.12,
      className: 'ring',
      interactive: false,
    }).addTo(m)

    // zoomToShowLayer is sensible on its own - it does nothing if the pin is
    // already visible, and only zooms/pans when it hides in a cluster. Do not mix flyTo in.
    const mk = marks.current.get(selected.id)
    const target = L.latLng(selected.lat, selected.lon)
    if (mk && cluster.current) {
      cluster.current.zoomToShowLayer(mk, () => {})
    } else if (!m.getBounds().pad(-0.25).contains(target) || m.getZoom() < 5) {
      m.flyTo(target, Math.max(m.getZoom(), 7), { duration: 0.7 })
    }
  }, [selected])

  // One Sentinel-2 scene, laid over whichever basemap is showing.
  // It goes in the tile pane, so the pins (marker pane) stay on top of it.
  useEffect(() => {
    const m = map.current
    if (!m) return
    if (sat.current) {
      m.removeLayer(sat.current)
      sat.current = null
    }
    if (!scene) return

    sat.current = L.tileLayer(sceneTiles(scene.cog), {
      ...sceneTileOpts,
      attribution: SENTINEL_ATTR,
      className: 'tiles-photo',
      // Explicit, so switching basemap afterwards cannot stack a fresh
      // basemap layer on top of this one and hide it.
      zIndex: 400,
    }).addTo(m)

    return () => {
      if (sat.current) {
        m.removeLayer(sat.current)
        sat.current = null
      }
    }
  }, [scene])

  // Recompute the map size when the panel opens or closes
  useEffect(() => {
    const t = setTimeout(() => map.current?.invalidateSize(), 320)
    return () => clearTimeout(t)
  }, [panelOpen])

  return <div ref={holder} className="map" />
}

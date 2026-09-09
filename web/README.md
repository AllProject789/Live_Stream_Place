# Live Cams — web app

Puts the data from `streams.json` on a map. Tap a pin and the live video plays
in the side panel, with the 20 nearest cams below it — tapping one of those does
the same thing again.

## Run

```bash
cd web
npm install
npm run dev          # http://localhost:5173
```

`npm run dev` and `npm run build` copy `../streams.json` into
`public/streams.json` first, so the data is always fresh. To do it by hand:
`npm run sync`

## Live data (straight from GitHub)

By default the app reads `/streams.json`. To read the file that GitHub Actions
keeps fresh instead, create `web/.env.local`:

```
VITE_STREAMS_URL=https://raw.githubusercontent.com/<user>/<repo>/main/streams.json
```

A deployed app then keeps refreshing itself every 4 hours.

## Deploy

```bash
npm run build        # -> web/dist/
```

Drop `dist/` on any static host — Netlify, Vercel, GitHub Pages.

## Layout

```
src/App.jsx            state, filters, layout
src/MapView.jsx        Leaflet map + marker clustering
src/Player.jsx         video panel + 20 recommendations
src/Card.jsx           thumbnail card (used by both the dock and the panel)
src/lib/streams.js     data loading + recommendation logic
src/lib/geo.js         haversine (same as search.py)
src/lib/categories.js  category colours/labels (mirrors filters.py)
```

## Notes

- **Map tiles**: OpenStreetMap's free tiles, no API key. The dark look comes
  from a CSS filter on `.leaflet-tile-pane`. For heavier traffic, run your own
  tile server (see the OSM usage policy).
- `streams.json` contains **only cams with lat/lon**, so every cam in it can be
  placed on the map. Cams whose location could not be worked out are recorded in
  `data/unresolved.json` instead.
- **Player** ([src/LivePlayer.jsx](src/LivePlayer.jsx)): `controls=0` removes
  YouTube's control bar (and the logo in it); the rest of the overlay — title,
  share, watch-later — only appears on hover, so a transparent `.frame-shield`
  sits on top to keep the mouse off the player entirely. Our own controls take
  its place: play/pause, mute/unmute and fullscreen (they slide up on hover).
  `modestbranding` is not used — YouTube deprecated it in 2023.
  Mute/unmute goes through `enablejsapi=1` + `postMessage`, which avoids loading
  YouTube's iframe_api script, so the video starts without waiting for it.
- Video autoplays muted (a browser requirement) — press 🔊 to turn sound on.
- Every cam keeps an **"Open on YouTube"** link below it, to satisfy YouTube's
  attribution terms. Do not remove it.
- `src/LivePlayer.jsx` handles both failure cases — a stream that has ended and
  one that cannot be embedded (message + a direct YouTube link).

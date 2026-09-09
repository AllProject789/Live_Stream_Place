# Live Stream Automation

Finds live webcam streams on YouTube, verifies them, and writes `streams.json` —
a file your app can read directly.

## Why

Live streams die and restart under a **new video ID**. Links collected by hand
break within days. This project keeps re-checking those IDs.

## Layout

```
config/queries.txt     the queries discover.py searches
config/channels.json   the list of trusted channels
data/inventory.json    the live cams of each channel
data/geo_cache.json    geocoding cache (commit it — it saves ~50 minutes)
data/index.json        cams with place + coordinates (used by search)
data/unresolved.json   cams whose location was not worked out (not in streams.json)
data/*.log             one log per script (crawl.log, build.log, ...)
scripts/reset.sh       clears generated data so you can test from scratch
streams.json           <- your app reads this — only cams with lat/lon
web/                   React app — shows the cams on a map
```

## Two separate halves — and why

| Part | Runs | Why |
|---|---|---|
| `discover.py`, `crawl.py`, `build.py` | **on your machine** | YouTube blocks datacenter IPs, so scraping is not reliable in CI |
| `refresh.py` | **GitHub Actions** | uses the official YouTube Data API — key-based, so the IP does not matter |

## Usage

### Build the index (locally)

```bash
pip install -r requirements.txt

python3 src/pipeline.py            # crawl -> build              (~6 min)
python3 src/pipeline.py --discover # discover -> crawl -> build  (~10 min)
```

Or one stage at a time:

```bash
python3 src/discover.py    # find new channels -> config/channels.json
python3 src/crawl.py       # live cams per channel -> data/inventory.json
python3 src/build.py       # place + coordinates -> streams.json + data/index.json
```

Every script logs to the terminal and to `data/<name>.log`, with a rate and an
ETA on the long loops.

### Testing from a clean slate

```bash
./scripts/reset.sh                 # derived data only    -> pipeline takes ~6 min
./scripts/reset.sh --cache         # + geocoding cache    -> ~55 min
./scripts/reset.sh --all           # + channel list       -> ~1 hour
./scripts/reset.sh --all --run     # ...and start the pipeline immediately
```

Everything it removes is copied to `.backups/<timestamp>/` first, and the two
expensive files ask for confirmation. `src/`, `web/src/` and
`config/queries.txt` are never touched.

### How crawl.py works

Two stages:

1. **Who is live** — read from the LIVE badge YouTube itself puts on each
   thumbnail of a channel's `/streams` tab (see `src/ytstreams.py`). That is
   1-5 requests per channel, ~25 seconds for 100 channels.
2. **Can it be embedded** — via yt-dlp, and only on the ~1,200 survivors of
   stage 1. A cam with embedding disabled shows nothing but "Video unavailable"
   in the app, and members-only streams drop out here too.

The old approach opened all ~42,000 candidate videos one by one to ask
`live_status`, which took about two hours — while only ~2.5% of them were live.
Stage 1 is scraping, so if YouTube changes its markup, `crawl.py --slow` still
has the old yt-dlp path (slow, but yt-dlp absorbs that kind of change). A
channel that fails stage 1 is named in a warning at the end of the run.

`build.py` geocodes, and Nominatim allows **1 request/second**, so the first run
is slow. Commit `data/geo_cache.json` and later runs are quick.

### Search by place name

```bash
python3 src/search.py "Times Square" "Venice" "Taj Mahal"
```

When there is no cam there, it says **how far the nearest one is** instead of
giving a wrong answer.

### Keeping it fresh automatically (GitHub Actions)

1. Google Cloud Console -> new project -> enable **YouTube Data API v3** -> API key
2. Repo -> Settings -> Secrets -> add `YOUTUBE_API_KEY`
3. `.github/workflows/update.yml` runs every 4 hours

Your app then reads:

```
https://raw.githubusercontent.com/<user>/<repo>/main/streams.json
```

### Run it daily on a Mac

```bash
./scripts/install-schedule.sh          # launchd, daily at 06:00
./scripts/install-schedule.sh remove
```

## Web app (React)

`web/` holds a React app — every cam on a map, tap a pin and the video plays.

```bash
cd web && npm install && npm run dev
```

Details in [web/README.md](web/README.md).

## The shape of streams.json

```json
{
  "updated_at": "2026-09-08T16:00:00+00:00",
  "count": 753,
  "streams": [
    {
      "id": "JQ_jwk_7OVE",
      "title": "EarthCam Live: Times Square North 4K",
      "channel": "EarthCam",
      "category": "city",
      "place": "Times Square, Manhattan, New York, USA",
      "lat": 40.757, "lon": -73.986,
      "thumbnail": "https://i.ytimg.com/vi/JQ_jwk_7OVE/hqdefault.jpg",
      "embed": "https://www.youtube.com/embed/JQ_jwk_7OVE"
    }
  ]
}
```

`category` = `city | beach | wildlife | railway | airport | harbour | nature | other`

## Quota

`refresh.py` costs **1 unit per 50 video IDs**, against a daily limit of 10,000.
750 cams = ~15 units per run. Every 4 hours = ~90 units a day. Plenty of room.

## Getting the location right

Title text is the only clue to where a cam points, and Nominatim will happily
match any two words to something, somewhere. Give it `Sea Otter` and it returns
a road in South Carolina — the cam is at Monterey Bay Aquarium. So
`src/places.py` rejects more than it accepts:

- A bare country or state name is not a candidate at all. A state centroid is
  not a cam's location.
- Results at **country / state / region / county** level are rejected, read from
  Nominatim's `addresstype`.
- A **street or building** level result is only accepted when a word of the
  query also appears in the result's *address*, not just in its name. Matching
  `Funchal Marina` to "Marina, Promenade do Funchal" is corroborated; matching
  `Sea Otter` to "Sea Otter, Hilton Head" is not.
- If the title names a country or a US state, the result must be in it.
- A single word with no geographic hint anywhere in the title is not tried at
  all — 78% of those were wrong in a sample.

Anything rejected lands in `data/unresolved.json`. A cam that cannot be placed
on the map is of no use to the app, so leaving it out beats pinning it in the
wrong country.

## Known limits

- **Not every cam's location is recognised.** Titles are messy and geocoding
  fails on them. Those cams go to `unresolved.json` and are **not in
  `streams.json`**. Improve the geocoding, re-run `build.py`, and some come back.
- **YouTube does not have a cam for every place.** Taj Mahal, Machu Picchu and
  the like have no permanent public live stream. That is an inventory problem,
  not a search problem.
- **Nominatim's rate limit** is 1 req/sec. For large or frequent rebuilds,
  consider your own instance or a paid geocoder.
- Compilation streams ("Top 200 cams") are dropped — they cannot be tied to one
  place.
- **Members-only streams are dropped** — they are live, but behind a paywall, so
  the public (and the app) cannot watch them.
- A **large island or a long river** can still be pinned loosely: the middle of
  Sardinia, or an arbitrary point on the Snake River. Rejecting those types
  outright would also throw out Maui, Koh Samui and a dozen good river cams, so
  they are kept.
- **Stage 1 of the crawl is scraping.** If YouTube changes its markup it breaks,
  and the fix is `crawl.py --slow` until this repo catches up.

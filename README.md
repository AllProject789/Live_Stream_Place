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
data/geo_cache.json    geocoding cache (commit it — it saves ~30 minutes)
data/index.json        every cam with place + coordinates (used by search)
data/unresolved.json   cams whose location was not worked out (not in streams.json)
data/*.log             one log per script (crawl.log, build.log, ...)
scripts/reset.sh       clears generated data so you can test from scratch
streams.json           <- your app reads this — the best 500 plus ALWAYS_CC, see "Which cams the app shows"
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
expensive files ask for confirmation. `src/` and `config/queries.txt`
are never touched.

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

`build.py` geocodes, and the public Nominatim allows **1 request/second**, so
the first run is slow — a cam needs two or three lookups, and 1,700 cams took
28 minutes from an empty cache. Commit `data/geo_cache.json` and later runs
take a second: only genuinely new cams cost anything.

#### Making it faster

The rate limit is the whole cost, so the only real lever is a geocoder that
does not impose one. Both settings are read from the environment, and the
answers come from the same software and the same OSM data, so the results do
not change:

```bash
docker run -d --name nominatim -p 8080:8080 \
  -e PBF_URL=https://download.geofabrik.de/europe-latest.osm.pbf \
  mediagis/nominatim:4.4        # a planet import is ~1 TB and takes days

NOMINATIM_URL=http://localhost:8080 NOMINATIM_INTERVAL=0 GEOCODE_WORKERS=8 \
  python3 src/build.py          # the same run, in seconds
```

| variable | default | what it does |
|---|---|---|
| `NOMINATIM_URL` | `https://nominatim.openstreetmap.org` | which geocoder to ask |
| `NOMINATIM_INTERVAL` | `1.0` | seconds between requests, measured from when each one *starts* |
| `GEOCODE_WORKERS` | `1` | cams geocoded at once — only worth raising when the interval is `0` |

Leave `GEOCODE_WORKERS` at 1 against the public instance: the rate limiter is
shared, so threads only queue behind it, and one cam at a time means Ctrl-C
stops promptly. Either way the cache is kept — the geocoding already done is
never repeated, so an interrupted run costs nothing but the cams it had left.

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
  `Sea Otter` to "Sea Otter, Hilton Head" is not. A distinctive venue name the
  title asks for outright — `Togwotee Mountain Lodge`, `Grand Targhee Resort` —
  counts as corroborated on its own; no lodge repeats its own street name.
- If the title names a country or a US state, the result must be in it.
- A single word with no geographic hint anywhere in the title is not tried at
  all — 78% of those were wrong in a sample.

What the title is asked for matters as much as what comes back. A landmark
phrase is pulled out wherever it sits — `Dornan's in Grand Teton National Park`
offers `Grand Teton National Park`, not just `Dornan's` — and it is asked first,
because `resolve()` only ever refines a hit into a *nearby* one, so a coarse
early answer (`Java, Indonesia`) is a ceiling that `Semeru Volcano` can never
get past.

### Reading the description

The title is the better evidence — it is short, and it is what the owner chose
to call the camera — so the description is only read when the title held no
place at all. And not all of it: a description is written for humans and most
of its lines are about the channel, so two kinds of line count and no others.
One says outright where the camera is (`📍`, "Located in", "Live from"), and
one names a country or a US state, which the result then has to agree with
anyway.

Even that is not enough on its own. The marker words are ordinary English and
catch ordinary English with them — "streaming live from our new (2025) floating
taco boat" matched, and Nominatim answered with Our Lady of Pompeii Catholic
Church — so a hint with no proper noun in it is dropped. What survives places
about 30 cams the title could not: Senyati Safari Camp, Tortilis Camp in
Amboseli, a Tuscan vineyard.

### What the channel knows

A title is all there is about one cam, but cams from one channel share an area,
and `build.py` reads that in a second pass. Each channel's home is the median of
its own located cams — a median, because finding the wrong pins is the point and
a few outliers cannot move one. A channel whose cams genuinely span the world
(EarthCam, afarTV) has no home and is left alone.

For a channel that does have one, a pin outside it is wrong however well the
words matched: `Snow King Mountain Base - SeeJH.ai` is in Wyoming, not the Snow
King that Nominatim finds in Kyrgyzstan, and nothing inside that title could
have caught it. Those cams are re-read with the area as a constraint. The same
fact places the cams whose titles name nowhere at all (`Bayfront Cam`): if the
title yields nothing inside the area, the area itself is the answer. Those rows
carry `"approx": true`, the app draws them as hollow pins, and the panel labels
them *approximate* — an honest area beats a confident-looking address the camera
is nowhere near.

Anything still rejected lands in `data/unresolved.json`. A cam that cannot be
placed on the map is of no use to the app, so leaving it out beats pinning it in
the wrong country.

## Which cams the app shows

`data/index.json` holds every cam that could be placed. `streams.json` — the
file the app reads — holds the best **500** of them, and the two rules that
pick them are worth stating plainly (a third, `ALWAYS_CC`, follows):

1. **The pin has to be the camera's own.** A cam placed only on its channel's
   area (`"approx": true`) is left out. It is an honest answer, but it is not
   one the map should stand behind when there are better cams to show.
2. **Ranked by concurrent viewers, most-watched first.** Subscribers say the
   channel is worth something; viewers say *this camera, right now* is, and
   that is the thing being ranked. Subscribers only break ties — and the ties
   are the majority, because the median cam has 2 viewers and most of the list
   sits on 1-5. A tie on both falls back to the video id, so the same numbers
   always produce the same file.

Both numbers come from the same yt-dlp call `crawl.py` already makes to check
embeddability, so they cost nothing extra.

### ...and the countries that are never cut

Ranking by viewers alone lets a whole country miss out. Indian cams draw far
smaller concurrent audiences than a Hawaii volcano does, so on that measure not
one of them survives the top 500 — India would be absent from the map
altogether.

So `ALWAYS_CC` names the countries that are appended *after* the limit, in the
same viewers-first order. The top 500 is exactly what it was; the country's own
cams ride along behind it, and `streams.json` holds 500 + however many there
are. They face the same test as the 500 — an exact pin only, never a cam placed
on its channel's area — so each one carries a real lat/lon.

```bash
ALWAYS_CC=in python3 src/build.py       # the default: India
ALWAYS_CC=in,np,lk python3 src/build.py # India, Nepal and Sri Lanka
ALWAYS_CC= python3 src/build.py         # off - the top 500 and nothing else
```

It keys on the ISO2 country code Nominatim returns (recorded as `cc` on every
placed row), not on the place name, because `place` comes back in the local
language — India is as often `भारत` as `India`, and Italy is `Italia`.

```bash
STREAM_LIMIT=800 python3 src/build.py    # show more (default 500)
```

## Known limits

- **Not every cam's location is recognised.** Titles are messy and geocoding
  fails on them. Those cams go to `unresolved.json` and are **not in
  `streams.json`**. Improve the geocoding, re-run `build.py`, and some come back.
- **YouTube does not have a cam for every place.** Taj Mahal, Machu Picchu and
  the like have no permanent public live stream. That is an inventory problem,
  not a search problem.
- **Nominatim's rate limit** is 1 req/sec, and that is the whole of `build.py`'s
  running time on an empty cache. For large or frequent rebuilds, point
  `NOMINATIM_URL` at your own instance — see *Making it faster* above.
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
- **An Indian temple cam is harder to place than most.** The title names the
  temple, and the same temple name is repeated in every city: there is a Shirdi
  Sai Baba Temple in Chennai, a Swaminarayan Mandir in nearly every district,
  and the London one is famous enough that Nominatim's own importance score
  waves it through. What actually distinguishes them is the city sitting beside
  the name — `Ujjain`, `Vadtal`, `Varanasi` — and nothing reads it yet, so some
  of these cams land in `unresolved.json` and some lean on the channel's area
  in pass 2. Adding `Temple` and `Mandir` to the landmark list was tried and
  made it worse, for the reason the comment beside that list now records.

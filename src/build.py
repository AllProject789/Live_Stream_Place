"""inventory.json -> streams.json (read by the app) + data/index.json (for search).
   Usage: python3 src/build.py

Two passes. The first reads each cam's own title, which is all the information
there is about that one cam. The second reads the channel: cams from one
channel usually share an area, and a pin far outside it is wrong even when the
title's words matched perfectly — 'Snow King Mountain Base - SeeJH.ai' is in
Wyoming, not the Snow King that Nominatim finds in Kyrgyzstan. The same fact
places the cams whose titles name no place at all ('Bayfront Cam').
"""
import collections
import datetime
import json
import os
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from filters import categorize
from log import Progress, setup
from places import expected_cc, expected_state, haversine, resolve_cam, reverse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
log = setup("build")

# A channel counts as broadcasting from one area when the *typical* one of its
# located cams sits within this far of their median. Typical, not worst: the
# spread has to be measured with the wrong pins still in it, and a 75th
# percentile let five of them speak for a channel. See Jackson Hole read as
# 362 km wide that way and lost its home - so the guard that would have caught
# those five pins was switched off by the five pins. Its median distance is
# 36 km. Channels that really are spread out are still nowhere near: Steel
# Highway 322 km, EarthCam 716 km.
HOME_SPREAD_KM = 120
MIN_HOME_CAMS = 4        # fewer than this and the median means nothing

# Geocoding runs one cam at a time by default. That is not a speed choice - the
# public Nominatim allows one request a second, so threads would only queue up
# behind the rate limiter - it is so that Ctrl-C stops the run promptly and the
# cache written so far is kept. Against your own instance (NOMINATIM_URL,
# NOMINATIM_INTERVAL=0) set GEOCODE_WORKERS and the same work takes seconds.
WORKERS = int(os.environ.get("GEOCODE_WORKERS", "1"))

# How many cams the app is given. index.json keeps every cam that could be
# placed - search.py wants all of them - while streams.json carries the best of
# them: a map of 1,300 pins is not worth more than a map of 500 when the tail
# of it is somebody's driveway.
LIMIT = int(os.environ.get("STREAM_LIMIT", "500"))

# Countries that are never cut. The top LIMIT is chosen by viewers alone, and
# on that measure a whole country can miss out: Indian cams draw far smaller
# concurrent audiences than a Hawaii volcano, so ranking them against the
# world's busiest cams leaves none of them in. These are appended *after* the
# LIMIT instead - the top 500 stays exactly what it was, and the country's own
# cams ride along behind it.
#
# Keyed on the ISO2 country code rather than the place name, because Nominatim
# answers in the local language. Comma-separated, so ALWAYS_CC=in,np adds two.
ALWAYS_CC = [c.strip().lower() for c in os.environ.get("ALWAYS_CC", "in").split(",") if c.strip()]


def rank(row):
    """Sort key for streams.json - concurrent viewers, highest first.

    Viewers alone decide the order. Subscribers say the channel is worth
    something; concurrent viewers say *this camera, right now* is, and that is
    the thing being ranked.

    Subscribers are still read, but only to break ties, and the ties are the
    majority: the median cam has 2 viewers, so most of the list is cams on 1-5
    and their order would otherwise be arbitrary. A tie on both falls back to
    the id, which never changes, so a rebuild with the same numbers produces
    the same file.

    Returned negated, so a plain ascending sort puts the busiest cam first.
    """
    return (-(row.get("views") or 0), -(row.get("subs") or 0), row["id"])


def save(index, unresolved):
    json.dump(index, open(os.path.join(ROOT, "data", "index.json"), "w"),
              indent=1, ensure_ascii=False)
    json.dump(unresolved, open(os.path.join(ROOT, "data", "unresolved.json"), "w"),
              indent=1, ensure_ascii=False)


def row_for(ch, v):
    return {"id": v["id"], "title": v["title"], "channel": ch,
            "category": categorize(v["title"]),
            "thumbnail": f"https://i.ytimg.com/vi/{v['id']}/hqdefault.jpg",
            "embed": f"https://www.youtube.com/embed/{v['id']}",
            "views": v.get("views") or 0, "subs": v.get("subs") or 0}


def homes(cams):
    """Where each channel broadcasts from — {channel: (lat, lon, radius_km)}.

    Read from the cams that did resolve. A median is used rather than a mean
    precisely because some of those pins are the wrong ones we are looking for:
    a handful of outliers in Kyrgyzstan and Jamaica cannot move it. The
    majority country is taken first for the same reason, and a channel whose
    cams genuinely span the world (EarthCam, afarTV) fails the spread test and
    gets no home at all.
    """
    by = collections.defaultdict(list)
    for c in cams:
        if c["geo"]:
            by[c["channel"]].append(c["geo"])

    out = {}
    for ch, geos in by.items():
        if len(geos) < MIN_HOME_CAMS:
            continue
        cc = collections.Counter(g.get("cc") for g in geos).most_common(1)[0][0]
        local = [g for g in geos if g.get("cc") == cc]
        if len(local) < MIN_HOME_CAMS or len(local) < 0.6 * len(geos):
            continue                      # no clear majority country
        lat = statistics.median(g["lat"] for g in local)
        lon = statistics.median(g["lon"] for g in local)
        # Snap to the nearest cam that actually exists. A median taken on each
        # axis separately is not one of the points and can miss land entirely -
        # Duluth's fell in Lake Superior and Lanzarote's in the Atlantic, where
        # reverse geocoding answers "Minnesota" and "España". The nearest real
        # cam is on shore, and reverse() then names the town.
        lat, lon = min(((g["lat"], g["lon"]) for g in local),
                       key=lambda p: haversine(lat, lon, p[0], p[1]))
        spread = statistics.median(haversine(lat, lon, g["lat"], g["lon"])
                                   for g in local)
        if spread <= HOME_SPREAD_KM:
            # Three times the typical distance, floored and capped: wide enough
            # that a cam at the edge of the area the channel already covers is
            # not thrown out for being at the edge, narrow enough that the
            # circle still means something.
            out[ch] = (lat, lon, min(max(3 * spread, 80.0), 300.0), cc)
    return out


def _doubtful(cam, home):
    """Is this pin worth a second look against the channel's area?

    Only when the title itself said nothing about where the cam is. A title
    that names its own country or US state has already had the pin checked
    against it by resolve(), and that is better evidence than the channel:
    'Kensington Cam2 Philadelphia, PA.' belongs in Pennsylvania even though the
    rest of its channel films in Los Angeles, and the area would have moved it
    3,800 km.
    """
    geo = cam["geo"]
    title = cam["video"]["title"]
    if geo and (expected_cc(title) or expected_state(title)):
        return False
    lat, lon, radius, _ = home[cam["channel"]]
    return not geo or haversine(lat, lon, geo["lat"], geo["lon"]) > radius


def _fits(title, cc, place):
    """Does the channel's area agree with what the title says?

    A cam the title contradicts is better left off the map than pinned in the
    wrong state: 'Kensington Cam4 Phila, PA.' rides on a channel that films in
    California, and nothing had placed it, so the area was free to claim it -
    3,800 km from the Pennsylvania its own title names. The title wins.
    """
    want = expected_cc(title)
    if want and cc and cc not in want:
        return False
    states = expected_state(title)
    return not (states and cc == "us"
                and not any(st in (place or "") for st in states))


def main():
    inv = json.load(open(os.path.join(ROOT, "data", "inventory.json")))
    total = sum(len(c["live"]) for c in inv)
    log.info(f"geocoding {total} cams from {len(inv)} channels")
    log.info("(uncached lookups are rate-limited to 1/second by Nominatim)")

    # ── pass 1: each cam's own title ────────────────────────────────────────
    jobs = [(ch["channel"], v) for ch in inv for v in ch["live"]]
    cams, located = [], 0
    progress = Progress(total, log, "geocoded", every=50)

    def collect(channel, v, found):
        nonlocal located
        query, geo = found
        cams.append({"channel": channel, "video": v, "query": query, "geo": geo})
        located += bool(geo)
        progress.tick(extra=f"located={located} unlocated={len(cams) - located}")
        if progress.done % 100 == 0:
            write(cams)                   # checkpoint, so an interrupted run is not lost

    if WORKERS > 1:
        log.info(f"geocoding {WORKERS} cams at a time")
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            # map keeps the input order, so the index comes out the same either way
            for (channel, v), found in zip(jobs, ex.map(
                    lambda j: resolve_cam(j[1]["title"], j[1].get("description")), jobs)):
                collect(channel, v, found)
    else:
        for channel, v in jobs:
            collect(channel, v, resolve_cam(v["title"], v.get("description")))
    progress.finish()

    # ── pass 2: what the channel says about cams the title could not place ──
    home = homes(cams)
    log.info(f"pass 2 - {len(home)} of {len(inv)} channels broadcast from one area")
    suspect = [c for c in cams if c["channel"] in home and _doubtful(c, home)]
    log.info(f"pass 2 - re-reading {len(suspect)} cams pinned outside their "
             f"channel's area, or not pinned at all")

    moved = approx = refused = 0
    progress = Progress(len(suspect), log, "rechecked", every=25)
    for c in suspect:
        lat, lon, radius, cc = home[c["channel"]]
        was = c["geo"]
        query, geo = resolve_cam(c["video"]["title"], c["video"].get("description"),
                                 near=(lat, lon), radius_km=radius)
        if geo:
            c["query"], c["geo"] = query, geo
            moved += 1
        else:
            # Nothing in the title matches anywhere in the channel's area, so
            # either it named no place or it named the wrong one. The area
            # itself is vague but true - pin that, and mark it as vague.
            place = reverse(lat, lon) or c["channel"]
            if _fits(c["video"]["title"], cc, place):
                c["query"] = f"channel:{c['channel']}"
                c["geo"] = {"place": place, "lat": lat, "lon": lon, "approx": True}
                approx += 1
            else:
                c["geo"] = None
                refused += 1
        progress.tick(extra=f"repinned={moved} channel area={approx} left off={refused}")
    progress.finish(f"repinned={moved} channel area={approx} left off={refused}")

    index, unresolved = write(cams)
    exact = [r for r in index if not r.get("approx")]
    log.info(f"located = {len(index)} ({len(exact)} exact, {len(index) - len(exact)} "
             f"channel area) | unlocated = {len(unresolved)} "
             f"({100 * len(index) // max(total, 1)}% located)")

    # The app gets the best cams that are pinned where they actually are. A cam
    # placed only on its channel's area is not one of them: it would be a pin
    # the map cannot stand behind, and there are better cams to show instead.
    picked = sorted(exact, key=rank)[:LIMIT]
    if picked:
        log.info(f"picked {len(picked)} of {len(exact)} exactly-placed cams "
                 f"(cut-off: {picked[-1]['views']} viewers, "
                 f"{picked[-1]['subs']} subscribers)")

    # ...then every cam from an ALWAYS_CC country that the cut-off left behind,
    # appended in the same viewers-first order. Same standard as the 500: an
    # exact pin only, so each one carries a real lat/lon rather than its
    # channel's area.
    taken = {r["id"] for r in picked}
    for cc in ALWAYS_CC:
        extra = sorted((r for r in exact if r.get("cc") == cc and r["id"] not in taken),
                       key=rank)
        picked += extra
        taken.update(r["id"] for r in extra)
        in_top = sum(1 for r in picked[:LIMIT] if r.get("cc") == cc)
        log.info(f"always-include {cc}: {len(extra)} appended "
                 f"({in_top} were already in the top {LIMIT})")

    streams = {"updated_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
               "count": len(picked),
               "streams": picked}
    json.dump(streams, open(os.path.join(ROOT, "streams.json"), "w"),
              indent=1, ensure_ascii=False)
    log.info(f"wrote streams.json with {streams['count']} cams")


def write(cams):
    """Split the cams into the located and the not, and save both."""
    index, unresolved = [], []
    for c in cams:
        row = row_for(c["channel"], c["video"])
        geo = c["geo"]
        if geo:
            row.update({"place": geo["place"], "lat": geo["lat"], "lon": geo["lon"],
                        "matched_on": c["query"]})
            # ISO2 country code, straight from Nominatim. Recorded because
            # `place` cannot be filtered on: it comes back in the local
            # language, so India is 'भारत' as often as 'India' and Italy is
            # 'Italia'. ALWAYS_CC below keys on this.
            if geo.get("cc"):
                row["cc"] = geo["cc"]
            # An area, not a point — the app draws these differently, and the
            # distinction is lost if it has to guess from the place name.
            if geo.get("approx"):
                row["approx"] = True
            index.append(row)
        else:
            # No location -> kept out of streams.json (the app needs lat/lon),
            # but recorded in unresolved.json for when geocoding improves.
            unresolved.append(row)
    save(index, unresolved)
    return index, unresolved


if __name__ == "__main__":
    main()

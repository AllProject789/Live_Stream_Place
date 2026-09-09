"""inventory.json -> streams.json (read by the app) + data/index.json (for search).
   Usage: python3 src/build.py"""
import datetime
import json
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
from filters import categorize
from log import Progress, setup
from places import resolve

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
log = setup("build")


def save(index, unresolved):
    json.dump(index, open(os.path.join(ROOT, "data", "index.json"), "w"),
              indent=1, ensure_ascii=False)
    json.dump(unresolved, open(os.path.join(ROOT, "data", "unresolved.json"), "w"),
              indent=1, ensure_ascii=False)


def main():
    inv = json.load(open(os.path.join(ROOT, "data", "inventory.json")))
    index, unresolved = [], []
    total = sum(len(c["live"]) for c in inv)
    log.info(f"geocoding {total} cams from {len(inv)} channels")
    log.info("(uncached lookups are rate-limited to 1/second by Nominatim)")
    progress = Progress(total, log, "geocoded", every=50)

    for ch in inv:
        for v in ch["live"]:
            query, geo = resolve(v["title"])
            row = {"id": v["id"], "title": v["title"], "channel": ch["channel"],
                   "category": categorize(v["title"]),
                   "thumbnail": f"https://i.ytimg.com/vi/{v['id']}/hqdefault.jpg",
                   "embed": f"https://www.youtube.com/embed/{v['id']}"}
            if geo:
                row.update({"place": geo["place"], "lat": geo["lat"], "lon": geo["lon"],
                            "matched_on": query})
                index.append(row)
            else:
                # No location -> kept out of streams.json (the app needs lat/lon),
                # but recorded in unresolved.json for when geocoding improves.
                unresolved.append(row)
            progress.tick(extra=f"located={len(index)} unlocated={len(unresolved)}")
            if progress.done % 100 == 0:
                save(index, unresolved)   # checkpoint, so an interrupted run is not lost

    progress.finish()
    save(index, unresolved)

    # The file the app reads — only cams whose location is known. A cam that
    # cannot be placed on the map is of no use to the app.
    streams = {"updated_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
               "count": len(index),
               "streams": index}
    json.dump(streams, open(os.path.join(ROOT, "streams.json"), "w"),
              indent=1, ensure_ascii=False)
    log.info(f"located = {len(index)} | unlocated = {len(unresolved)} "
             f"({100 * len(index) // max(total, 1)}% located)")
    log.info(f"wrote streams.json with {streams['count']} cams")


if __name__ == "__main__":
    main()

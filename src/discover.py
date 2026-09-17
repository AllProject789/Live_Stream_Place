"""Find new live-cam channels. Run locally (yt-dlp is blocked on GitHub Actions).
   Usage:  python3 src/discover.py
   Output: new channels appended to config/channels.json"""
import json
import os
import subprocess
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from filters import COMPILATION, NOTCAM, place_like
from log import Progress, setup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_FILTER = "&sp=EgJAAQ%253D%253D"          # YouTube's "Live" search filter
log = setup("discover")


def load_queries():
    with open(os.path.join(ROOT, "config", "queries.txt"), encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


def search(q):
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(q) + LIVE_FILTER
    try:
        out = subprocess.run(["yt-dlp", "--flat-playlist", "--playlist-end", "20", "--dump-json", url],
                             capture_output=True, text=True, timeout=180).stdout
    except Exception:
        return []
    rows = []
    for line in out.splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def main():
    queries = load_queries()
    log.info(f"searching {len(queries)} queries with YouTube's Live filter")
    progress = Progress(len(queries), log, "queries", every=10)
    found = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for rows in ex.map(search, queries):
            for d in rows:
                url = d.get("channel_url") or d.get("uploader_url")
                name = d.get("channel") or d.get("uploader")
                if not url or not name:
                    continue
                found.setdefault(url, {"name": name, "url": url, "titles": []})
                found[url]["titles"].append(d.get("title", ""))
            progress.tick(extra=f"channels={len(found)}")
    progress.finish()

    # Quality gate
    keep = []
    for e in found.values():
        titles = e["titles"]
        comps = [t for t in titles if COMPILATION.search(t)]
        if NOTCAM.search(e["name"]):                 continue
        if len(comps) >= max(1, len(titles) * 0.6):  continue
        if not any(place_like(t) for t in titles):   continue
        keep.append({"name": e["name"], "url": e["url"], "seen": len(titles)})

    path = os.path.join(ROOT, "config", "channels.json")
    old = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []
    by_url = {c["url"]: c for c in old}
    added = 0
    for c in keep:
        if c["url"] not in by_url:
            by_url[c["url"]] = c
            added += 1
    out = sorted(by_url.values(), key=lambda c: -c.get("seen", 0))
    json.dump(out, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    log.info(f"channels seen = {len(found)} | passed quality gate = {len(keep)} | new = {added}")
    log.info(f"wrote config/channels.json: {len(out)} channels")


if __name__ == "__main__":
    main()

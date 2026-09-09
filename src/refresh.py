"""For GitHub Actions: check which cams are still live, via the YouTube Data API.

   yt-dlp is not used here because YouTube blocks datacenter IPs.
   Requires: environment variable YOUTUBE_API_KEY
   Cost:     1 quota unit per 50 IDs (daily limit 10,000)
"""
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request
sys.path.insert(0, os.path.dirname(__file__))
from log import Progress, setup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://www.googleapis.com/youtube/v3/videos"
log = setup("refresh")


def chunks(seq, n=50):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def check_live(ids, key):
    """Return {video_id: True/False}.

    True = live right now *and* embeddable elsewhere. A non-embeddable cam only
    shows "Video unavailable" in the app, so it does not count as live.
    Adding the `status` part costs nothing — videos.list is 1 unit per call.
    """
    status = {}
    progress = Progress(len(ids), log, "checked", every=200)
    for group in chunks(ids, 50):
        url = API + "?" + urllib.parse.urlencode({
            "part": "snippet,status", "id": ",".join(group), "key": key})
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.load(r)
        alive = {it["id"]: (it["snippet"].get("liveBroadcastContent") == "live"
                            and it.get("status", {}).get("embeddable", True))
                 for it in data.get("items", [])}
        for vid in group:
            status[vid] = alive.get(vid, False)   # missing = gone
        progress.tick(len(group), extra=f"live={sum(status.values())}")
    progress.report(f"live={sum(status.values())}")
    return status


def main():
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        log.error("YOUTUBE_API_KEY is not set")
        sys.exit(1)

    path = os.path.join(ROOT, "streams.json")
    if not os.path.exists(path):
        log.error("streams.json not found - run crawl.py and build.py first")
        sys.exit(1)

    data = json.load(open(path))
    streams = data["streams"]
    ids = [s["id"] for s in streams]
    log.info(f"checking {len(ids)} cams against the YouTube Data API")

    live_map = check_live(ids, key)
    alive = [s for s in streams if live_map.get(s["id"])]
    dead = [s for s in streams if not live_map.get(s["id"])]

    data = {"updated_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "count": len(alive), "streams": alive}
    json.dump(data, open(path, "w"), indent=1, ensure_ascii=False)

    # Keep the dead ones aside — useful for finding a replacement for that place
    json.dump(dead, open(os.path.join(ROOT, "data", "dead.json"), "w"),
              indent=1, ensure_ascii=False)
    log.info(f"checked = {len(ids)}  live = {len(alive)}  dead = {len(dead)}")
    log.info(f"quota used = {(len(ids) + 49) // 50} units of 10,000/day")


if __name__ == "__main__":
    main()

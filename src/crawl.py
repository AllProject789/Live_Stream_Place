"""Collect the cams that are live right now, channel by channel.

   Usage:  python3 src/crawl.py           # fast path (LIVE badge)  ~4 min
           python3 src/crawl.py --slow    # old path (yt-dlp)       ~2 hours
   Output: data/inventory.json

Two stages:
  1. Which streams are live — from the LIVE badge on the channel's /streams tab
     (see ytstreams.py). 1-5 requests per channel, ~25 seconds in total.
  2. Which of those actually play on other sites — via yt-dlp, run only on the
     ~1,200 survivors. A cam with embedding disabled shows nothing but "Video
     unavailable" in our app, and members-only streams make yt-dlp error out, so
     they drop away here too.

Why --slow is kept: stage 1 is scraping. If YouTube changes its markup, the old
path is still there — slower, but yt-dlp absorbs that kind of change for us.
"""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from filters import COMPILATION, place_like
from log import Progress, setup
from ytstreams import channel_live

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
log = setup("crawl")


def keep_title(t):
    """Drop compilations and titles with no place in them."""
    return bool(t) and not COMPILATION.search(t) and place_like(t)


# ─────────────────────────── stage 1: who is live ───────────────────────────

def fast(ch):
    """Read the LIVE badge — 1-5 requests per channel."""
    try:
        live, seen, reqs = channel_live(ch["url"])
    except Exception as e:
        return ch, None, f"{type(e).__name__}: {e}"[:60]
    cams = [{"id": v["id"], "title": v["title"]} for v in live if keep_title(v["title"])]
    return ch, cams, f"seen {seen:4} req {reqs}"


def crawl(ch):
    """Old path: every stream on the /streams tab (liveness unknown at this point)."""
    try:
        out = subprocess.run(["yt-dlp", "--flat-playlist", "--dump-json", ch["url"] + "/streams"],
                             capture_output=True, text=True, timeout=300).stdout
    except Exception:
        return ch, [], ""
    cams = []
    for line in out.splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        if keep_title(d.get("title", "")):
            cams.append({"id": d["id"], "title": d["title"]})
    return ch, cams, "candidates"


# ───────────────────── stage 2: can it be embedded? ─────────────────────

def check_batch(ids):
    """One yt-dlp call opens several videos and asks for live_status + embeddability."""
    urls = ["https://www.youtube.com/watch?v=" + i for i in ids]
    try:
        out = subprocess.run(["yt-dlp", "--no-warnings", "--ignore-errors", "--skip-download",
                              "--print", "%(id)s|%(live_status)s|%(playable_in_embed)s", *urls],
                             capture_output=True, text=True, timeout=900).stdout
    except Exception:
        return set()
    keep = set()
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 3:
            continue
        vid, status, embed = (x.strip() for x in parts[:3])
        # embed=False means the owner disabled playback on other sites — that cam
        # would only ever show "Video unavailable" in our app.
        if status == "is_live" and embed != "False":
            keep.add(vid)
    return keep


def verify_live(ids, workers=8, size=25):
    """Return only the IDs that are live *and* embeddable.

    live_status values: is_live ✓ | was_live ✗ | is_upcoming ✗ | not_live ✗
    members-only / private / deleted videos make yt-dlp error out and never reach
    the list — which is correct, the public cannot watch them either.
    """
    ids = list(ids)
    batches = [ids[i:i + size] for i in range(0, len(ids), size)]
    live = set()
    progress = Progress(len(ids), log, "checked", every=size * 2)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        # tick by the real batch length - the last batch is usually short
        for batch, got in zip(batches, ex.map(check_batch, batches)):
            live |= got
            progress.tick(len(batch), extra=f"embeddable={len(live)}")
    progress.finish(f"embeddable={len(live)}")
    return live


def main():
    slow = "--slow" in sys.argv
    channels = json.load(open(os.path.join(ROOT, "config", "channels.json")))
    found, failed = [], []

    log.info(f"stage 1/2 - {len(channels)} channels via "
             f"{'yt-dlp (slow path)' if slow else 'LIVE badge'}")
    progress = Progress(len(channels), log, "channels", every=20)
    with ThreadPoolExecutor(max_workers=8 if slow else 12) as ex:
        for ch, cams, note in ex.map(crawl if slow else fast, channels):
            if cams is None:                       # stage 1 failed for this channel
                failed.append(ch["name"])
                log.warning(f"  {ch['name'][:34]}: {note}")
                continue
            if cams:
                found.append({"channel": ch["name"], "url": ch["url"], "live": cams})
            progress.tick(extra=f"cams={sum(len(r['live']) for r in found)}")
    progress.finish(f"cams={sum(len(r['live']) for r in found)}")

    total = sum(len(r["live"]) for r in found)
    log.info(f"stage 2/2 - checking which of {total} cams can be embedded")
    ok_ids = verify_live({v["id"] for r in found for v in r["live"]})

    result = []
    for r in found:
        kept = [v for v in r["live"] if v["id"] in ok_ids]
        if kept:
            result.append({"channel": r["channel"], "url": r["url"], "live": kept})
    result.sort(key=lambda r: -len(r["live"]))

    json.dump(result, open(os.path.join(ROOT, "data", "inventory.json"), "w"),
              indent=1, ensure_ascii=False)
    kept = sum(len(r["live"]) for r in result)
    log.info(f"live found = {total}  ->  embeddable = {kept}  (dropped {total - kept})")
    log.info(f"wrote data/inventory.json: {kept} cams across {len(result)} channels")
    if failed:
        log.warning(f"stage 1 failed on {len(failed)} channels: {', '.join(failed[:5])}"
                    f"{'...' if len(failed) > 5 else ''} - retry, or use --slow")


if __name__ == "__main__":
    main()

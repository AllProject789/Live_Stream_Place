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
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from filters import COMPILATION, NEWSCAST, place_like
from log import Progress, setup
from ytstreams import channel_live

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
log = setup("crawl")


def keep_title(t):
    """Drop compilations, news broadcasts, and titles with no place in them."""
    return (bool(t) and not COMPILATION.search(t) and not NEWSCAST.search(t)
            and place_like(t))


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

# Everything stage 2 needs, in one yt-dlp call. The `j` conversion returns a
# JSON object per line rather than a delimited string, because a description
# contains newlines and would otherwise run into the next cam's row.
FIELDS = ("%(.{id,live_status,playable_in_embed,"
          "concurrent_view_count,channel_follower_count,description})j")

# A description is mostly links and boilerplate. What build.py wants out of it
# is a place name, so the links go here and the rest is capped - it has to live
# in inventory.json, and 1,700 full descriptions would be megabytes of sponsor text.
LINKY = re.compile(r"(?i)https?://|www\.|subscribe|patreon|instagram|facebook|twitter"
                   r"|discord|paypal|merch|perks|join this channel")
DESC_CHARS = 400


def trim_description(text):
    lines = [l.strip() for l in (text or "").splitlines()
             if l.strip() and not LINKY.search(l)]
    return " \n".join(lines)[:DESC_CHARS]


def check_batch(ids):
    """One yt-dlp call opens several videos and asks for live_status, embeddability,
       and the numbers build.py ranks cams by."""
    urls = ["https://www.youtube.com/watch?v=" + i for i in ids]
    try:
        out = subprocess.run(["yt-dlp", "--no-warnings", "--ignore-errors", "--skip-download",
                              "--print", FIELDS, *urls],
                             capture_output=True, text=True, timeout=900).stdout
    except Exception:
        return {}
    keep = {}
    for line in out.splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        # embed=False means the owner disabled playback on other sites — that cam
        # would only ever show "Video unavailable" in our app.
        if d.get("live_status") != "is_live" or d.get("playable_in_embed") is False:
            continue
        keep[d["id"]] = {"views": d.get("concurrent_view_count") or 0,
                         "subs": d.get("channel_follower_count") or 0,
                         "description": trim_description(d.get("description"))}
    return keep


def verify_live(ids, workers=8, size=25):
    """{id: facts} for the cams that are live *and* embeddable.

    live_status values: is_live ✓ | was_live ✗ | is_upcoming ✗ | not_live ✗
    members-only / private / deleted videos make yt-dlp error out and never reach
    the list — which is correct, the public cannot watch them either.
    """
    ids = list(ids)
    batches = [ids[i:i + size] for i in range(0, len(ids), size)]
    live = {}
    progress = Progress(len(ids), log, "checked", every=size * 2)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        # tick by the real batch length - the last batch is usually short
        for batch, got in zip(batches, ex.map(check_batch, batches)):
            live.update(got)
            progress.tick(len(batch), extra=f"embeddable={len(live)}")
    progress.finish(f"embeddable={len(live)}")
    return live


def dedupe(cams):
    """One cam per title within a channel — the copy with the most viewers.

    A channel can run the same feed as several simultaneous streams, each with
    its own video id and the same title: 'Sai Bhakti Original' had ten of one
    Shirdi cam, 'Kedarnath Live Darshan Official' ten of one. They geocode
    identically, so all ten reach the same coordinate and the map draws ten
    pins on one temple. The busiest copy is the one the audience is actually
    watching, and it is the one kept.
    """
    best = {}
    for v in cams:
        key = v["title"].strip().lower()
        if key not in best or (v.get("views") or 0) > (best[key].get("views") or 0):
            best[key] = v
    return list(best.values())


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
    facts = verify_live({v["id"] for r in found for v in r["live"]})

    result = []
    for r in found:
        kept = [v | facts[v["id"]] for v in r["live"] if v["id"] in facts]
        kept = dedupe(kept)
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

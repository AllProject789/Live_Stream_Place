"""The whole local pipeline in one command.

    python3 src/pipeline.py              # crawl -> build            (~6 min)
    python3 src/pipeline.py --discover   # discover -> crawl -> build
    python3 src/pipeline.py --refresh    # ...then also verify liveness (needs API key)

Why local: discover.py uses yt-dlp and YouTube blocks datacenter IPs, so it is
not reliable on GitHub Actions. refresh.py uses the official API, so that one
runs on Actions every 4 hours.

Each run appends to data/pipeline.log, and every step also keeps its own log
(data/crawl.log, data/build.log, ...). The current streams.json is copied to
data/streams.prev.json before the build, so a bad run does not lose the last
good result.
"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
sys.path.insert(0, os.path.dirname(__file__))
from log import human, setup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
log = setup("pipeline")


def step(name, script, *args):
    """Run one stage as a subprocess, streaming its output straight through."""
    log.info(f"=== {name}: start ===")
    started = datetime.datetime.now()
    proc = subprocess.run([sys.executable, "-u", os.path.join(ROOT, "src", script), *args],
                          cwd=ROOT)
    took = (datetime.datetime.now() - started).total_seconds()

    if proc.returncode != 0:
        log.error(f"=== {name}: FAILED (exit {proc.returncode}) after {human(took)} ===")
        log.error(f"see data/{script.replace('.py', '')}.log for details")
        sys.exit(proc.returncode)
    log.info(f"=== {name}: done in {human(took)} ===")


def main():
    ap = argparse.ArgumentParser(description="Live cam index - full pipeline")
    ap.add_argument("--discover", action="store_true",
                    help="also look for new channels (once a month is plenty)")
    ap.add_argument("--refresh", action="store_true",
                    help="verify liveness via the YouTube API at the end (needs YOUTUBE_API_KEY)")
    ap.add_argument("--slow", action="store_true",
                    help="crawl with yt-dlp instead of the LIVE badge (~2 hours)")
    args = ap.parse_args()

    log.info("########## pipeline start ##########")

    if args.discover:
        step("discover (new channels)", "discover.py")

    step("crawl (collect and verify live cams)", "crawl.py", *(["--slow"] if args.slow else []))

    # build rewrites streams.json — keep a copy of the current one first
    src = os.path.join(ROOT, "streams.json")
    if os.path.exists(src):
        shutil.copy2(src, os.path.join(ROOT, "data", "streams.prev.json"))
        log.info("saved current streams.json to data/streams.prev.json")

    step("build (place names and coordinates)", "build.py")

    if args.refresh:
        if os.environ.get("YOUTUBE_API_KEY"):
            step("refresh (liveness check)", "refresh.py")
        else:
            log.warning("skipped refresh - YOUTUBE_API_KEY is not set")

    d = json.load(open(src))
    log.info(f"########## pipeline done: {d['count']} cams, all with lat/lon ##########")


if __name__ == "__main__":
    main()

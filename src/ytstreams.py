"""Which of a channel's streams are live right now — read from YouTube's LIVE badge.

Why this file exists
--------------------
crawl.py used to open every candidate video with yt-dlp and ask for
`live_status`. Collecting the /streams tab of 100 channels yields ~42,000
candidates, and opening them one by one takes ~2 hours — while only ~2.5% turn
out to be live. So 97.5% of the work is spent confirming that an old stream is
still finished.

But liveness is **already in the HTML** of the /streams tab: YouTube puts a LIVE
badge on each thumbnail.

    thumbnailBadgeViewModel -> badgeStyle: THUMBNAIL_OVERLAY_BADGE_STYLE_LIVE

yt-dlp's --flat-playlist throws that away, but reading the HTML directly keeps
it. That turns one request per video into **1-5 requests per channel**.

Live streams also sort to the top of the /streams tab, so we can stop at the
first page without a single LIVE badge — everything past it is years old.

Risk: this is scraping, so it breaks if YouTube changes its markup. yt-dlp does
the same thing, so it is not a new class of risk — and `crawl.py --slow` keeps
the old path available.
"""
import json
import re
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
LIVE_BADGE = "THUMBNAIL_OVERLAY_BADGE_STYLE_LIVE"
INITIAL = re.compile(r"var ytInitialData = (\{.*?\});</script>")
API_KEY = re.compile(r'"INNERTUBE_API_KEY":"([^"]+)"')
CLIENT_VER = re.compile(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"')


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "en-US,en;q=0.9"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


def _browse(key, ver, token):
    """Fetch the next page — the same endpoint the browser uses when you scroll."""
    body = json.dumps({"context": {"client": {"clientName": "WEB", "clientVersion": ver}},
                       "continuation": token}).encode()
    req = urllib.request.Request(
        "https://www.youtube.com/youtubei/v1/browse?key=%s&prettyPrint=false" % key,
        data=body, headers={"Content-Type": "application/json", "User-Agent": UA})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


def _lockups(node, out):
    """Collect lockupViewModel nodes (one per video card) in page order."""
    if isinstance(node, dict):
        if "lockupViewModel" in node:
            out.append(node["lockupViewModel"])
            return
        for v in node.values():
            _lockups(v, out)
    elif isinstance(node, list):
        for v in node:
            _lockups(v, out)


def _next_token(node):
    if isinstance(node, dict):
        if "continuationItemRenderer" in node:
            m = re.search(r'"token":\s*"([^"]+)"', json.dumps(node["continuationItemRenderer"]))
            return m.group(1) if m else None
        for v in node.values():
            if (t := _next_token(v)):
                return t
    elif isinstance(node, list):
        for v in node:
            if (t := _next_token(v)):
                return t
    return None


def _title(lock):
    m = re.search(r'"content":\s*"((?:[^"\\]|\\.)*)"', json.dumps(lock.get("metadata", {})))
    return json.loads('"%s"' % m.group(1)) if m else ""


def _page(node):
    locks = []
    _lockups(node, locks)
    rows = [{"id": l["contentId"], "title": _title(l), "live": LIVE_BADGE in json.dumps(l)}
            for l in locks if l.get("contentId")]
    return rows, _next_token(node)


def channel_live(url, max_pages=25):
    """Return (live cams, videos seen, requests used). Raises on unknown markup."""
    html = _get(url.rstrip("/") + "/streams")
    key, ver, first = API_KEY.search(html), CLIENT_VER.search(html), INITIAL.search(html)
    if not (key and ver and first):
        raise ValueError("unrecognised YouTube markup")

    rows, token = _page(json.loads(first.group(1)))
    live, seen, reqs = [r for r in rows if r["live"]], len(rows), 1
    # The first page with no live stream on it means we are past them all
    while token and rows and any(r["live"] for r in rows) and reqs < max_pages:
        rows, token = _page(json.loads(_browse(key.group(1), ver.group(1), token)))
        reqs += 1
        seen += len(rows)
        live += [r for r in rows if r["live"]]
    return live, seen, reqs

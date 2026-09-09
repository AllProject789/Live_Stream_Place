"""Extract a place name from a video title and turn it into coordinates."""
import json, os, re, sys, time, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from filters import COUNTRIES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(ROOT, "data", "geo_cache.json")

NOISE = re.compile(r"(?i)\b(live\s*stream(ing)?|live\s*cam(era)?|webcam|live\s*now|live|cam"
                   r"|24\s*/?\s*7|\d{3,4}p|[2-9]k|\d{2,3}\s*fps|ultra\s*hd|hd|uhd|ptz"
                   r"|members[\s-]*only|no\s*ads|with\s*sound"
                   r"|powered by.*|presented by.*)\b")
DATE  = re.compile(r"\b20\d\d[-/ ]\d\d?[-/ ]\d\d?\b|\b\d{1,2}:\d{2}\b")
EMOJI = re.compile("[\U00010000-\U0010ffff←-⯿☀-➿️‍]", flags=re.UNICODE)
HASHTAG = re.compile(r"#\w+")

def clean(title):
    t = EMOJI.sub(" ", title)
    t = HASHTAG.sub(" ", t)
    t = DATE.sub(" ", t)
    t = re.sub(r"(?i)^\s*earthcam\s*:?", " ", t)
    t = NOISE.sub(" ", t)
    return re.sub(r"\s{2,}", " ", t).strip(" -–—|·:,")

# Camera jargon - a chunk containing these words is not a place
JARGON = re.compile(r"(?i)\b(camera|cam|ptz|fixed|turnout|view|angle|zoom|pan|tilt"
                    r"|north|south|east|west|upper|lower|overview|stream|feed"
                    r"|channel|trains?|railcam|weather|traffic|scenic|panorama"
                    r"|time\s*-?\s*lapse)\b")

def _junk(part):
    """Unlikely to be a place name?"""
    core = re.sub(r"[^\w\s,]", " ", JARGON.sub(" ", part))
    return len([w for w in core.split() if len(w) > 2]) == 0

def _tail(part, n=3):
    """Trim the leading description:
       'Trains in the Street at La Grange, Kentucky, USA' -> 'La Grange, Kentucky, USA'"""
    bits = [b.strip() for b in part.split(",") if b.strip()]
    if len(bits) < 2:
        return None
    head = bits[0]
    m = re.search(r"((?:[A-Z][\w']*\s+)*[A-Z][\w']*)\s*$", head)   # last proper-noun group
    if m:
        head = m.group(1)
    out = ", ".join([head] + bits[1:][-(n - 1):])
    return out if out.lower() != part.lower() else None

# A connector word dangling at either end of a candidate confuses Nominatim:
# 'Hawaii in' fuzzy-matched "Hawaii Beach" in Goa, India.
CONNECTOR = {"in", "of", "the", "at", "from", "and", "on", "by", "to", "with",
             "for", "a", "an", "near", "de", "du", "la", "le", "van", "von"}

def _strip_connectors(c):
    """Strip dangling connector words - but only lowercase ones.

    In 'La Grange', 'Le Mans', 'Van Buren', 'De Panne' the word is *part of
    the name*, and then it is capitalised. Without this check
    'La Grange, Kentucky, USA' became 'Grange, Kentucky, USA', which does not
    geocode - and the fallback then matched the whole state, 100 km off.
    """
    words = c.split()

    def drop(w):
        w = w.strip(",")
        return w.islower() and w in CONNECTOR

    while words and drop(words[0]):
        words.pop(0)
    while words and drop(words[-1]):
        words.pop()
    return " ".join(words)


# A single common word is not a place name - Nominatim will find something by
# that name somewhere ('Beach' -> Pattaya, 'Rabbits' -> Australia, 'Cuts' -> France).
GENERIC_ONE_WORD = set("""beach bay park street road avenue river lake hill tower market
square harbor harbour port marina pier valley falls forest garden station bridge castle
island mountain volcano waterfall resort hotel bar cafe restaurant church temple museum
zoo farm ranch lodge camp trail waterhole pan hide sanctuary reserve downtown skyline
plaza boulevard beachfront oceanfront views view cuts rabbits members elephants lions
birds squirrels zebra hippos giraffes wildlife safari nature ocean sea coast shore
sunrise sunset weather traffic city town village center centre
sound water noise relax sleep flowing quarry siding placeholder yard depot crossing
junction bridge bird cams multi main old new upper lower side
more best top watch see explore sounds relaxing scenic webcams feed panorama""".split())


def _words(c):
    """Words of a candidate. Hyphens split too - 'Horton-in-Ribblesdale' is
       not one word, it is three."""
    return re.sub(r"[^\w\s]", " ", c).lower().split()


def _suffixes(part, keep=3):
    """Tails of a comma'd chunk, most specific first.

    'W Aquino Street Market Area, Agdao, Davao City'
        -> ['Agdao, Davao City', 'Davao City']

    _tail() only trims the head of the first chunk; if every word there is
    capitalised nothing gets cut. So here we drop the first chunk entirely -
    sending Nominatim 'Agdao, Davao City' beats sending it
    'PHILIPPINES W Aquino Street Market Area'.
    """
    bits = [b.strip() for b in part.split(",") if b.strip()]
    return [", ".join(bits[i:][-keep:]) for i in range(1, len(bits))]


# A country name is not a place - a candidate like 'PHILIPPINES W' makes
# Nominatim find a matching name in any corner of the country (Ormoc, Baguio...).
def _trim_lead(part):
    """Drop leading country names, camera jargon and one-or-two letter chunks."""
    words = part.split()
    i = 0
    while i < len(words):
        w = words[i].strip(",.:'\"").lower()
        if w in COUNTRIES or JARGON.fullmatch(w) or len(w) <= 2:
            i += 1
        else:
            break
    rest = " ".join(words[i:])
    return rest if any(len(w) > 2 for w in rest.split()) else ""


# 'Griffith, IN' / 'Burlington, WI' / 'Moran, WY' - an uppercase two-letter
# code after a comma. Case-sensitive and only after a comma, otherwise the
# English words 'in', 'or', 'me', 'la' get read as states.
ABBR_RE = re.compile(r",\s*([A-Z]{2})\b")
US_ABBR = set("""AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN
MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC""".split())
CA_ABBR = {"ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU"}

# A US result's display_name always comes back in English and contains the full
# state name ("Griffith, Lake County, Indiana, United States"). So the state can
# be read from the title and compared with display_name directly - no new cache
# field needed. This goes one step beyond the country check: 'Burlington, WI'
# used to resolve in Vermont - right country, wrong state.
ABBR_TO_STATE = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
STATE_NAMES = {v.lower(): v for v in ABBR_TO_STATE.values()}

STATE_START = re.compile(
    r"^(" + "|".join(re.escape(v) for v in ABBR_TO_STATE.values()) + r")\b", re.I)


def _expand_states(t):
    """'Burlington, WI Doug's Auto' -> 'Burlington, Wisconsin Doug's Auto'

    Nominatim does not understand two-letter codes; it understands full names.
    """
    return ABBR_RE.sub(
        lambda m: ", " + ABBR_TO_STATE[m.group(1)] if m.group(1) in ABBR_TO_STATE else m.group(0),
        t)


# 'Kentucky, USA' / 'Massachusetts' / 'Maine US' - a bare state name. Like a
# country, a state is far too large for its centroid to be a cam's location.
# Without this check 'Boston Weather Cam, Massachusetts' got pinned in the
# middle of the state, while 'Boston' geocodes perfectly well.
ADMIN_TAIL = re.compile(r"(?i)[\s,]+(usa?|united\s+states|canada|uk)\.?$")


def _bare_admin(c):
    core = ADMIN_TAIL.sub("", c).strip(" .,")
    return core.lower() in STATE_NAMES


def _tail_words(part, k):
    """The last k words before the comma, plus the geographic tail:
       'Kensington Cam2 Philadelphia, Pennsylvania' -> 'Philadelphia, Pennsylvania'

    _tail() keeps the whole proper-noun group, so a place written mid-title is
    never tried on its own and the fallback ends up matching the whole state.
    """
    bits = [b.strip() for b in part.split(",") if b.strip()]
    if len(bits) < 2:
        return None
    head = bits[0].split()
    if len(head) <= k:
        return None
    slice_ = head[-k:]
    # Do not manufacture junk like 'Boston Weather, Massachusetts' ->
    # 'Weather, Massachusetts': a chunk starting with a common word is not a
    # place name, and Nominatim will match that somewhere in the world too.
    first = slice_[0].strip(",").lower()
    if first in GENERIC_ONE_WORD or first in CONNECTOR or JARGON.fullmatch(first):
        return None
    return ", ".join([" ".join(slice_)] + bits[1:][-2:])


def _state_pairs(part):
    """If a chunk starts with a state name, join it to the previous chunk:
       'Burlington, Wisconsin Doug's Auto Service' -> 'Burlington, Wisconsin'"""
    bits = [b.strip() for b in part.split(",") if b.strip()]
    out = []
    for i in range(1, len(bits)):
        m = STATE_START.match(bits[i])
        if m:
            out.append(f"{bits[i - 1]}, {m.group(1)}")
    return out


def candidates(title):
    """Possible place names, most trustworthy first.

    Where the place sits in a title varies by channel - Virtual Railfan puts it
    first ("Ashland, Virginia, USA | LIVE Train Camera"), others put it last
    ("Hush Bar | Chaweng | Koh Samui | Thailand"). So candidates are ranked by
    *how place-like the chunk is*, not by position.
    """
    res, seen = [], []

    def add(c):
        c = re.sub(r"\s+,", ",", re.sub(r"\s{2,}", " ", (c or ""))).strip(" -–—:,|()")
        c = _strip_connectors(c)
        if len(c) < 3 or c.lower() in seen:
            return
        if c.lower() in COUNTRIES:      # a bare country name = country centroid,
            return                      # not a cam location - do not waste a request
        if _bare_admin(c):              # ...and a bare state name is no better
            return
        # If every word is generic it is not a place, comma or not:
        # '(Birds, Squirrels, Rabbits)' lists what the cam shows,
        # 'Thailand, Beach' is a country plus a common noun,
        # 'Forest Stream' is generic twice over (stream is in JARGON as well).
        words = _words(c)
        if words and all(w in GENERIC_ONE_WORD or w in CONNECTOR or w in COUNTRIES
                         or JARGON.fullmatch(w) for w in words):
            return
        seen.append(c.lower())
        res.append(c)

    # A place in brackets - but only when it is not camera jargon
    for m in re.findall(r"\(([^)]{3,60})\)", title):
        if "," in m and not _junk(m):
            add(m)

    t = _expand_states(clean(title))
    parts = [p.strip(" -–—:") for p in re.split(r"[|·•]|\s[-–—]\s", t) if p.strip()]
    # '@' means 'at' - in 'Teign Estuary Cam @ Teignmouth' the place follows it.
    # The whole chunk is kept too (for crossing cams like 'W Main @ Maple St').
    parts += [b.strip() for p in parts if "@" in p for b in p.split("@") if b.strip()]
    useful = [p for p in parts if not _junk(p)]

    # Comma'd chunks are the strongest signal ("Ashland, Virginia, USA")
    for p_ in useful:
        if "," in p_:
            add(p_)
            add(_tail(p_))          # with the leading junk removed
            for k in (1, 2):
                add(_tail_words(p_, k))   # a place written mid-title, plus the tail
            for sp in _state_pairs(p_):
                add(sp)             # 'town, state' - the most reliable pair
            for suf in _suffixes(p_):
                add(suf)            # variants that drop the first chunk entirely

    # With no comma anywhere, attach a geographic tail ("Koh Samui, Thailand")
    if not any("," in p_ for p_ in useful) and len(useful) >= 2:
        add(", ".join(useful[-2:]))

    # Rank by *signal*, not position: a country name is strongest, then a comma.
    # (in 'Venice Italy - The View on Canal from Hotel Pausania' the place is
    #  in the first chunk, not the last)
    def rank(p_):
        low = p_.lower()
        return -(3 * any(c in low.split() or c in low for c in COUNTRIES) + 2 * ("," in p_))
    for p_ in sorted(useful, key=rank):
        # 'Times Square North' -> 'Times Square' (North is a camera angle, not a place)
        stripped = re.sub(r"\s{2,}", " ", JARGON.sub(" ", p_)).strip(" -–—:,")
        if stripped and stripped.lower() != p_.lower() and len(stripped) >= 3:
            add(stripped)
        add(p_)
        # 'Mallorca Paguera Cala Fornells' -> 'Mallorca' (broader but correct)
        # Broad fallback: the first two words, then just the first
        # ('Mallorca Paguera Cala Fornells' -> 'Mallorca')
        lead = _trim_lead(p_)
        for pat in (r"([A-Z][\w']*(?:\s+[A-Z][\w']*)?)\b", r"([A-Z][\w']*)\b"):
            m = re.match(pat, lead)
            if m and m.group(1).lower() != p_.lower():
                add(m.group(1))
    # Note: junk chunks (Stream, Camera, PTZ...) are deliberately not added back -
    # Nominatim finds a village by that exact name somewhere in the world.

    return res[:7]

_cache = None
def _load():
    global _cache
    if _cache is None:
        _cache = json.load(open(CACHE_PATH)) if os.path.exists(CACHE_PATH) else {}
    return _cache

# Reject business addresses (shop/office/bar) - accept everything else.
# A whitelist was tried, but it also threw out real places like Venice.
BAD_CLASS = {"amenity", "shop", "office", "craft", "healthcare", "building"}

def _acceptable(row):
    return row.get("class") not in BAD_CLASS

# A country / state / region / county level result - its centroid is not any
# one cam's location. This check used to be "does display_name contain a
# comma", which only caught countries: 'Kentucky, United States' and
# 'Sardigna, Italia' both have commas, so they passed and the pin landed in
# the middle of the state. Nominatim's addresstype says it outright.
COARSE_TYPES = {"country", "state", "region", "province", "state_district",
                "county", "continent", "ocean", "sea", "archipelago"}


def _coarse(val):
    atype = val.get("atype")
    if atype is not None:
        return atype in COARSE_TYPES
    return "," not in (val.get("place") or "")     # old entries with no atype


# Accept a street/building level result only when some word of the query also
# appears in the result's *address* - matching the name alone is not enough.
#
# Give Nominatim any two words and it finds a road by that name somewhere in
# the world, and importance does not separate them (a real 'Soliman Street'
# and a bogus 'Sea Otter' both score 0.05). A real match corroborates:
#     'Funchal Marina'  -> Marina, Promenade do *Funchal*, ...      ✓
#     'Sea Otter'       -> Sea Otter, Hilton Head, South Carolina   ✗
#                          (that cam is actually at Monterey Bay Aquarium)
def _uncorroborated(query, val):
    if (val.get("rank") or 0) < 20:            # village/city level - skip this check
        return False
    if (val.get("imp") or 0) >= 0.25:          # genuinely well known (Times Square)
        return False
    bits = [b.strip().lower() for b in (val.get("place") or "").split(",")]
    name, rest = bits[0], " ".join(bits[1:])
    words = {w for w in re.sub(r"[^\w\s]", " ", query.lower()).split() if len(w) > 3}
    return not (any(w in name for w in words) and any(w in rest for w in words))


def _strict_ok(query, val):
    return not (_coarse(val) or _uncorroborated(query, val))

def geocode(query, allow_coarse=True):
    """OpenStreetMap Nominatim. Free, but 1 request/second - the cache is vital.

    With allow_coarse=False, results as broad as a country/continent/sea are
    rejected. build.py uses it that way; search.py (where the user may type
    'Italy' themselves) keeps the old behaviour.
    """
    def out(val):
        if val and not allow_coarse and not _strict_ok(query, val):
            return None
        return val

    cache = _load()
    hit = cache.get(query)
    # Old entries lack "cc" and "atype" (both added later) - treat those as
    # stale and re-fetch, or the country and coarseness checks never apply.
    fresh = hit is None or (isinstance(hit, dict) and "cls" in hit
                            and "cc" in hit and "atype" in hit)
    if query in cache and fresh:
        return out(hit)
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "limit": 3, "addressdetails": 1})
    req = urllib.request.Request(url, headers={"User-Agent": "livecam-index/1.0"})
    try:
        rows = json.load(urllib.request.urlopen(req, timeout=20))
    except Exception:
        rows = []
    time.sleep(1.1)
    # From limit=3, take the first row that *passes the accuracy checks*. Always
    # taking the first row sometimes caught a state centroid when a later row
    # held the real city. If none pass, keep the first anyway - search.py (where
    # the user may type 'Italy') still needs an answer.
    val, first = None, None
    for row in rows:
        if not _acceptable(row):
            continue
        cur = {"place": row["display_name"], "lat": float(row["lat"]),
               "lon": float(row["lon"]), "cls": row.get("class"), "typ": row.get("type"),
               # ISO2 country code - language-independent, so 'Italia' vs 'Italy' is moot
               "cc": (row.get("address") or {}).get("country_code"),
               # addresstype = 'state' / 'city' / 'road'... - tells us the level.
               # importance = Nominatim's fame score (0..1).
               "atype": row.get("addresstype"), "rank": row.get("place_rank"),
               "imp": row.get("importance") or 0.0}
        first = first or cur
        if _strict_ok(query, cur):
            val = cur
            break
    val = val or first
    cache[query] = val
    json.dump(cache, open(CACHE_PATH, "w"), ensure_ascii=False)
    return out(val)

# Names from filters.COUNTRIES -> ISO2. ('africa' is a continent, so not listed.)
CC = {
    "usa": "us", "uk": "gb", "scotland": "gb", "wales": "gb", "italy": "it",
    "spain": "es", "greece": "gr", "france": "fr", "germany": "de", "japan": "jp",
    "thailand": "th", "australia": "au", "canada": "ca", "mexico": "mx", "brazil": "br",
    "portugal": "pt", "norway": "no", "sweden": "se", "iceland": "is",
    "switzerland": "ch", "austria": "at", "croatia": "hr", "turkey": "tr",
    "egypt": "eg", "kenya": "ke", "india": "in", "china": "cn", "korea": "kr",
    "netherlands": "nl", "belgium": "be", "poland": "pl", "ireland": "ie",
    "denmark": "dk", "finland": "fi", "peru": "pe", "chile": "cl",
    "argentina": "ar", "colombia": "co", "indonesia": "id", "philippines": "ph",
    "vietnam": "vn", "malaysia": "my", "singapore": "sg", "botswana": "bw",
    "zimbabwe": "zw", "namibia": "na", "tanzania": "tz",
}

# A state/province name pins the country too. For the 600+ US cams this is the
# most effective filter: it rejects results like 'Ohio' -> Australia,
# 'Hawaii' -> India, 'California' -> Turkmenistan.
CC.update({s: "us" for s in """alabama alaska arizona arkansas california colorado
connecticut delaware florida georgia hawaii idaho illinois indiana iowa kansas kentucky
louisiana maine maryland massachusetts michigan minnesota mississippi missouri montana
nebraska nevada ohio oklahoma oregon pennsylvania tennessee texas utah vermont virginia
washington wisconsin wyoming""".split()})
CC.update({s: "ca" for s in """ontario quebec alberta manitoba saskatchewan
newfoundland yukon nunavut""".split()})
CC.update({"england": "gb", "cornwall": "gb", "yorkshire": "gb"})
# Note: 'new york', 'new hampshire', 'new jersey', 'new mexico', 'north/south
# carolina', 'north/south dakota', 'west virginia', 'rhode island', 'british
# columbia', 'nova scotia', 'new brunswick' - two-word names are listed below.
CC_MULTI = {
    "new york": "us", "new hampshire": "us", "new jersey": "us", "new mexico": "us",
    "north carolina": "us", "south carolina": "us", "north dakota": "us",
    "south dakota": "us", "west virginia": "us", "rhode island": "us",
    "british columbia": "ca", "nova scotia": "ca", "new brunswick": "ca",
    "prince edward island": "ca", "northwest territories": "ca",
}



def expected_state(title):
    """Which US state does the title name? (empty set = do not check)"""
    out = set()
    for code in ABBR_RE.findall(title):
        if code in ABBR_TO_STATE:
            out.add(ABBR_TO_STATE[code])
    low = title.lower()
    for name, proper in STATE_NAMES.items():
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            out.add(proper)
    return out


def expected_cc(title):
    """Which country does the title talk about? (empty set = unknown, skip)"""
    low = title.lower()
    out = set()
    for name, cc in CC_MULTI.items():       # two-word names first
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            out.add(cc)
    for name, cc in CC.items():
        # 'New Mexico' is not Mexico; in 'Indiana' the \b stops 'india' matching
        if name == "mexico" and re.search(r"\bnew\s+mexico\b", low):
            continue
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            out.add(cc)
    for code in ABBR_RE.findall(title):
        if code in US_ABBR:   out.add("us")
        elif code in CA_ABBR: out.add("ca")
    return out


def resolve(title):
    """Title -> (query used, geo). (None, None) when nothing matches.

    If the title names a country, the result must be in that country. Left
    unchecked, Nominatim fits a common one-word name somewhere in the world -
    'From' -> Norway, 'Members' -> Missouri, 'Elephants' -> Cameroun.
    """
    want = expected_cc(title)
    want_state = expected_state(title)
    for cand in candidates(title):
        # A single word with no geographic hint in the title is a gamble.
        # Nominatim always finds something by that exact name somewhere -
        # 'Dave' -> Belgium, 'Deck' -> Brazil, 'Hatchet' -> Alabama,
        # 'NASA' -> Lake Malawi. In a sample 78% of these were wrong, so
        # leaving them unresolved beats pinning them in the wrong place.
        if not want and len(_words(cand)) < 2:
            continue
        g = geocode(cand, allow_coarse=False)
        if not g:
            continue
        cc = g.get("cc")
        if want and cc and cc not in want:
            continue                    # title says another country - reject
        if want_state and cc == "us" and not any(st in g["place"] for st in want_state):
            continue                    # title says another state - reject
        return cand, g
    return None, None

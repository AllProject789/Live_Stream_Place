"""Extract a place name from a video title and turn it into coordinates."""
import atexit, json, math, os, re, sys, threading, time, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from filters import COUNTRIES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(ROOT, "data", "geo_cache.json")

# Which geocoder, and how fast it may be asked.
#
# The public Nominatim allows one request a second, and that is the default.
# Point NOMINATIM_URL at your own instance (or a paid one) and set
# NOMINATIM_INTERVAL to 0 to run at full speed - the answers come from the same
# software and the same OSM data, so the results do not change.
NOMINATIM_URL = os.environ.get("NOMINATIM_URL",
                               "https://nominatim.openstreetmap.org").rstrip("/")
MIN_INTERVAL = float(os.environ.get("NOMINATIM_INTERVAL", "1.0"))

_net = threading.Lock()
_next_at = 0.0


def _throttle():
    """Wait until the next request is allowed.

    The wait is measured from when the *previous request started*, not from
    when it finished. Sleeping a flat second after each call charged us for the
    server's response time as well - about 0.9s on the public instance - so
    every lookup cost two seconds instead of one, and a 1,700-cam run took 53
    minutes instead of 28. One request per second is still one per second.
    """
    global _next_at
    with _net:
        wait = _next_at - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _next_at = time.monotonic() + MIN_INTERVAL


def _get(path, params):
    """One call to the geocoder. Returns parsed JSON, or None if it failed."""
    url = f"{NOMINATIM_URL}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "livecam-index/1.0"})
    _throttle()
    try:
        return json.load(urllib.request.urlopen(req, timeout=20))
    except Exception:
        return None

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
#
# 'darshan' and the devotional words after it are the Indian equivalent of
# 'Live Cam': every temple stream is titled "Live Darshan <temple>", so the
# word says what the camera shows, never where it is. Left in, it led the
# candidate list and did real damage - "Live Darshan Shri Kashi Vishwanath
# Dham" (Varanasi) was asked as 'Darshan Shri' and answered with Shri Vitthal
# Rukmini Mandir in Pandharpur, 1100 km away. _uncorroborated() could not catch
# that one either: the result's address is "Sparsha Darshan Queue Line", so the
# word appears in the name *and* the address and the match looked corroborated.
JARGON = re.compile(r"(?i)\b(camera|cam|ptz|fixed|turnout|view|angle|zoom|pan|tilt"
                    r"|north|south|east|west|upper|lower|overview|stream|feed"
                    r"|channel|trains?|railcam|weather|traffic|scenic|panorama"
                    r"|time\s*-?\s*lapse"
                    r"|darshan|aarti|arti|bhasm|bhajan|bhakti|satsang|jhanki)\b")

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


# The same convention without the comma, at the very end of a title:
# 'Kensington Cam5 Philadelphia PA.' Requiring a capitalised word in front is
# what keeps English out - a bare \b[A-Z]{2}\b reads 'IN', 'OR' and 'ME' as
# states, and a title in capitals would be nothing but state codes.
ABBR_TAIL = re.compile(r"\b([A-Z][a-z]+)\s+([A-Z]{2})\b\.?\s*$")


def _expand_states(t):
    """'Burlington, WI Doug's Auto' -> 'Burlington, Wisconsin Doug's Auto'

    Nominatim does not understand two-letter codes; it understands full names.
    """
    t = ABBR_RE.sub(
        lambda m: ", " + ABBR_TO_STATE[m.group(1)] if m.group(1) in ABBR_TO_STATE else m.group(0),
        t)
    return ABBR_TAIL.sub(
        lambda m: (f"{m.group(1)}, {ABBR_TO_STATE[m.group(2)]}"
                   if m.group(2) in ABBR_TO_STATE else m.group(0)), t)


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


# A multi-word name ending in a landmark word is a strong place name, and it is
# usually written mid-title with no comma to mark it. Nothing looked for one, so
# "Dornan's in Grand Teton National Park" only ever offered 'Dornan's' and
# "Red Sox Fenway Park Live Cam" only 'Red Sox' - both of which Nominatim
# matched as a road in the wrong country.
LANDMARK_WORD = (r"(?:National\s+Park|State\s+Park|National\s+Forest|National\s+Monument"
                 r"|Game\s+Reserve|Nature\s+Reserve|Conservancy|Botanical\s+Gardens?"
                 r"|Safari\s+Lodge|Safari\s+Camp|Camp|Volcano|Crater|Glacier|Lighthouse"
                 r"|Aquarium|Stadium|Ballpark|Arena|Airport|Memorial|Museum|Cathedral"
                 r"|Basilica|Castle|Palace|Observatory|Lodge|Resort|Ranch|Marina|Pier"
                 r"|Waterhole|Falls|Canyon|Gorge|Mountain|Tower|Park|Bridge)")
# 'Temple' and 'Mandir' were tried in that list and belong with 'Beach' below,
# not above: in India the temple name is repeated in every city, so the phrase
# is a category and not a name. Asked as a landmark - which is asked first, and
# first hit wins - 'Shirdi Sai Baba Temple' left Shirdi for a branch temple in
# Chennai 1100 km away (it geocodes correctly without the word), 'Swaminarayan
# Mandir Vadtal' dropped the one word that distinguishes it and landed in Vyara,
# and 'Shree Mahakaleshwar Temple' found a namesake 370 km from Ujjain. What
# actually places an Indian temple cam is the city beside it, so these titles
# are left to the ordinary chunk rules.
# 'Beach', 'Harbour', 'Square', 'Pier' and 'Inn' were in that list and had to
# come out. They read as landmark words but they are common nouns, and the
# phrases they form are descriptions rather than names - at which point
# Nominatim finds something called exactly that, anywhere: 'Key West Harbor'
# -> Newport Beach, California (the cam is in Florida), 'Puerto Rico Beach'
# -> Albania, 'Tropical Beach' -> Sweden. A beach in a title is reached
# through its comma'd chunk instead, where _drop_generic_tail() turns
# 'York Harbor Beach, Maine' into 'York Harbor, Maine'.
LANDMARK = re.compile(r"\b((?:[A-Z][\w'’-]*\.?\s+){1,3}?(" + LANDMARK_WORD + r"))\b")
VENUE_WORD = re.compile(r"(?i)\b" + LANDMARK_WORD + r"\b")


def _landmarks(t):
    """Landmark phrases in a title: (as written, trimmed back) pairs.

    Neither form can be trusted over the other in general. In 'Grand Teton
    National Park' the leading words are part of the name; in 'Red Sox Fenway
    Park' and 'Erupting Semeru Volcano' they are a team and a verb, and only
    the trimmed form finds the place.

    What decides it is the order they are asked in, and the trimmed form has to
    come second - asked first it answered for phrases that were perfectly good
    as written. 'Alpine Valley RV Park' was asked as 'RV Park' and matched one
    in Gillette 460 km away; 'Colorado Model Railroad Museum' as 'Railroad
    Museum' left Greeley for Golden; 'Fairmont Kea Lani Resort' as 'Lani
    Resort' crossed from Maui to the Big Island. Each of those three geocodes
    correctly as written, so the trim is only ever a fallback.
    """
    out = []
    for m in LANDMARK.finditer(t):
        full, word = m.group(1), m.group(2)
        lead = full[:m.start(2) - m.start(1)].split()
        # 'Sorobon Luxury Beach Resort' must not be trimmed to 'Beach Resort':
        # a common noun in front of the landmark word means what is left over
        # is a category of place, not the name of one.
        short = (f"{lead[-1]} {word}"
                 if len(lead) > 1 and lead[-1].lower() not in GENERIC_ONE_WORD
                 else None)
        out.append((full, short))
    return out


def _admin_tail(t):
    """The one state or country the title names - '' when none or several.

    A landmark phrase on its own is a name without an address, and Nominatim
    answers it from anywhere on earth: 'York Harbor' -> Newfoundland. Appending
    the title's own state or country pins it where the title says it is.
    """
    st = expected_state(t)
    if len(st) == 1:
        return next(iter(st))
    # Whole words, not whole chunks. Splitting on commas and matching the chunk
    # left 'Indonesia ( C)' - the remains of "... in Java, Indonesia (Cam C)" -
    # matching nothing, and the volcano went unpinned for the sake of a stray
    # letter. Two countries in one title is no tail at all: it is ambiguous.
    low = t.lower()
    found = {c for c in COUNTRIES if re.search(r"\b" + re.escape(c) + r"\b", low)}
    if len(found) == 1:
        return next(iter(found)).title()
    return ""


def _drop_generic_tail(part):
    """'York Harbor Beach, Maine USA' -> 'York Harbor, Maine USA'

    A common noun tacked onto a place name stops Nominatim finding it, while
    the name without it geocodes straight away.
    """
    bits = [b.strip() for b in part.split(",") if b.strip()]
    if len(bits) < 2:
        return None
    head = bits[0].split()
    if len(head) > 1 and head[-1].strip(",").lower() in GENERIC_ONE_WORD:
        head.pop()
    out = ", ".join([" ".join(head)] + bits[1:])
    return out if out.lower() != part.lower() else None


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
    # Brackets end a chunk, they do not belong inside one. Left joined up, the
    # camera note in "..., Connecticut, USA (Fixed View - East)" travelled with
    # the place and Nominatim was asked for 'Connecticut, USA (Fixed View';
    # "(Cam C)" likewise produced 'Indonesia ( C'. Split there and the note
    # becomes its own chunk, which _junk() then drops - while a bracket that
    # holds a real place ("Lincoln Harbor (New York City)") still survives as a
    # chunk of its own.
    parts = [p.strip(" -–—:") for p in re.split(r"[|·•()\[\]]|\s[-–—]\s", t) if p.strip()]
    # '@' means 'at' - in 'Teign Estuary Cam @ Teignmouth' the place follows it.
    # The whole chunk is kept too (for crossing cams like 'W Main @ Maple St').
    parts += [b.strip() for p in parts if "@" in p for b in p.split("@") if b.strip()]
    useful = [p for p in parts if not _junk(p)]

    # A landmark phrase goes first. resolve() keeps the first hit and only
    # replaces it with a *nearby* finer one, so a coarse early hit is a ceiling:
    # with 'Java, Indonesia' taken first, 'Semeru Volcano' could never win, and
    # the cam sat in the middle of an island 200 km long.
    tail = _admin_tail(t)
    lms = _landmarks(t)

    def ask(lm):
        if tail and tail.lower() not in lm.lower():
            add(f"{lm}, {tail}")     # the title's own state or country pins it
        add(lm)

    for full, _ in lms:              # every phrase as written, first
        ask(full)
    for _, short in lms:             # then, only as a fallback, trimmed back
        if short:
            ask(short)

    # Comma'd chunks are the strongest signal ("Ashland, Virginia, USA")
    for p_ in useful:
        if "," in p_:
            add(p_)
            add(_tail(p_))          # with the leading junk removed
            for k in (1, 2):
                add(_tail_words(p_, k))   # a place written mid-title, plus the tail
            for sp in _state_pairs(p_):
                add(sp)             # 'town, state' - the most reliable pair
            add(_drop_generic_tail(p_))   # 'York Harbor Beach, Maine' -> 'York Harbor, Maine'
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

    return res[:10]

_cache = None
_cache_lock = threading.Lock()
_unsaved = 0
# Rewriting the whole file after every lookup costs 14ms on a 6,000-entry
# cache. Small next to a network call, but it is pure waste, and it is the one
# thing standing between this module and running several lookups at once.
FLUSH_EVERY = 25


def _load():
    global _cache
    if _cache is None:
        _cache = json.load(open(CACHE_PATH, encoding="utf-8")) if os.path.exists(CACHE_PATH) else {}
    return _cache


def _flush():
    """Write the cache out. Registered to run at exit, so a Ctrl-C keeps it."""
    global _unsaved
    with _cache_lock:
        if _cache is None or not _unsaved:
            return
        tmp = CACHE_PATH + ".tmp"       # never leave a half-written cache behind
        json.dump(_cache, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(tmp, CACHE_PATH)
        _unsaved = 0


atexit.register(_flush)


def _store(key, val):
    global _unsaved
    with _cache_lock:
        _load()[key] = val
        _unsaved += 1
        due = _unsaved >= FLUSH_EVERY
    if due:
        _flush()

# Reject business addresses (shop/office) - accept everything else.
# A whitelist was tried, but it also threw out real places like Venice.
#
# 'amenity' and 'building' used to be rejected here too, and they cost more
# than they saved: Nominatim files Fenway Park under amenity and Tsavo National
# Park under building, so both were thrown away and the next row down won
# instead - a Fenway Park in Australia, and for Tsavo nothing at all. What the
# rejection was really guarding against (a cafe matching a two-word query) is
# now _uncorroborated()'s job, and it judges the match rather than the label.
BAD_CLASS = {"shop", "office", "craft", "healthcare"}

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
def _query_words(query):
    """The words of a query that can corroborate a result.

    State and country names cannot. candidates() appends the title's own state
    or country to a landmark phrase, so finding 'Wyoming' in a Wyoming address
    proves only that we put it there - and that is how 'RV Park, Wyoming'
    passed for an RV park in Gillette, 460 km from the Alpine one the title
    names. Every US result in a state contains that state's name; the word
    carries no information about *which* place was found.
    """
    words = re.sub(r"[^\w\s]", " ", query.lower()).split()
    return [w for w in words
            if len(w) > 3 and w not in STATE_NAMES and w not in COUNTRIES]


def _venue_match(query, name):
    """Is the result's name the query, whole, and does the query name a venue?

    A distinctive venue name is corroboration in itself. Neither
    'Togwotee Mountain Lodge' nor 'Grand Targhee Resort' repeats a word of its
    own street address, so the address test below threw both away even though
    each was the right answer, uniquely named and asked for by name.

    The guard is that *every* significant word of the query has to be in the
    result's name, and the query has to look like a venue - three words, or a
    landmark word. Two common words still do not qualify, which is what keeps
    'Sea Otter' -> Hilton Head out.
    """
    words = _query_words(query)
    if len(words) < 2 or not all(w in name for w in words):
        return False
    # ...and match it from the front. Containing every word is not enough when
    # the result's name has more of its own in front: 'Lani Resort' is every
    # word of 'Mauna Lani Resort', and taking that carried a Maui cam to the
    # Big Island. A venue asked for by name answers with that name, not with a
    # longer one it happens to end in.
    #
    # The front is read from the query as written, state names included: they
    # cannot corroborate a result, but they can be part of a venue's name, and
    # skipping over the first word of 'Colorado Model Railroad Museum' made it
    # fail to match "Colorado Model Railroad Museum".
    lead = [w for w in re.sub(r"[^\w\s]", " ", query.lower()).split() if len(w) > 3]
    if not lead or not name.startswith(lead[0]):
        return False
    return len(query.split()) >= 3 or bool(VENUE_WORD.search(query))


def _uncorroborated(query, val):
    if (val.get("rank") or 0) < 20:            # village/city level - skip this check
        return False
    if (val.get("imp") or 0) >= 0.25:          # genuinely well known (Times Square)
        return False
    bits = [b.strip().lower() for b in (val.get("place") or "").split(",")]
    name, rest = bits[0], " ".join(bits[1:])
    if _venue_match(query, name):
        return False
    words = set(_query_words(query))
    return not (any(w in name for w in words) and any(w in rest for w in words))


def _strict_ok(query, val):
    return not (_coarse(val) or _uncorroborated(query, val))

def geocode(query, allow_coarse=True):
    """OpenStreetMap Nominatim. Free, but rate-limited - the cache is vital.

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
    rows = _get("search", {"q": query, "format": "json",
                           "limit": 3, "addressdetails": 1}) or []
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
    _store(query, val)
    return out(val)

def reverse(lat, lon):
    """Coordinates -> a place name, at about county/city level.

    Only used to give a channel's home area a name to show, so zoom=10 is
    deliberate: "Teton County, Wyoming, United States" is honest about being an
    area, where a street address would pretend to a precision we do not have.
    """
    key = f"@{lat:.4f},{lon:.4f}"          # '@' cannot start a real query, so
    cache = _load()                        # home areas share the geocode cache
    if key in cache:
        return cache[key]
    row = _get("reverse", {"lat": lat, "lon": lon, "format": "json", "zoom": 10}) or {}
    val = row.get("display_name")
    _store(key, val)
    return val


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
    m = ABBR_TAIL.search(title)
    if m and m.group(2) in ABBR_TO_STATE:
        out.add(ABBR_TO_STATE[m.group(2)])
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
    codes = ABBR_RE.findall(title)
    m = ABBR_TAIL.search(title)
    if m:
        codes.append(m.group(2))
    for code in codes:
        if code in US_ABBR:   out.add("us")
        elif code in CA_ABBR: out.add("ca")
    return out


def haversine(lat1, lon1, lat2, lon2):
    """Distance between two coordinates, in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


# Picking between candidates.
#
# candidates() lists the broad names ahead of the specific ones - 'Davao City'
# comes before 'Bankerohan Market' - and resolve() used to return the first one
# that geocoded. So 385 of 756 cams settled for a city centroid while
# 'Bankerohan Market, Davao City' - which Nominatim pins on the market itself,
# 200 m from the camera - was never even requested. Every cam in the city then
# shared one coordinate.
#
# So every candidate is tried now and the most precise hit wins. Nominatim's
# place_rank says how precise a hit is:
#   <=12 city | 16-18 town | 19-25 village/suburb | 26+ street/building/POI
FINE_RANK = 26          # precise enough to stop looking
NEAR_KM = 25            # how far a finer hit may sit from the one it replaces

# Nominatim ranks a river or a bay as finely as a building, but their geometry
# runs for kilometres, so the point it returns is a centroid - no more a camera
# position than a city's is. On a real run these dragged cams away from where
# they were: Boston -> 'Charles River' (22 km, into the next county),
# 'Cape Cod, Bass River' -> 'Cape Cod', Port Colborne -> 'Welland Canal',
# Cala Liberotto -> 'Gulf of Orosei'. Fine as a first answer, never as a
# refinement - which is the only thing this set is consulted for. Note it keys
# on addresstype, not on the name: 'Gulf of Orosei' is a bay and excluded,
# 'Colwell Bay' is a village and kept.
SPREAD_TYPES = {"river", "stream", "canal", "bay", "gulf", "strait", "sound",
                "peninsula", "cape", "isthmus", "mountain_range", "ridge", "valley",
                "lake", "reservoir"}

# The same problem one level down. addresstype is too blunt for rails: the
# Green Line is railway/light_rail - 20 km of track, and its midpoint landed a
# Boston cam in Somerville - while Assisi's station is railway/station, a point
# and a perfectly good answer. Both are addresstype 'railway', so the OSM type
# is what has to be read.
SPREAD_KINDS = {"light_rail", "rail", "subway", "tram", "monorail", "narrow_gauge",
                "funicular", "route", "bus_route", "ferry"}


def _rank(geo):
    return geo.get("rank") or 0


def _areas(place):
    """The administrative parts of a display_name, most specific first.

    House numbers and postcodes are dropped: they are digits, they match
    nothing useful, and leaving the postcode in made 'Connecticut, 06794,
    United States' look like it agreed with Iowa on its last two parts.
    """
    bits = [b.strip().lower() for b in (place or "").split(",")]
    return [b for b in bits if b and not re.fullmatch(r"[\d\s-]+", b)]


def _same_place(anchor, geo):
    """Is `geo` the same place as `anchor`, only pinned more precisely?

    This is the guard the change above needs: a specific-sounding candidate is
    exactly the kind Nominatim matches in the wrong corner of the world.

    It used to accept a finer hit whose *text* contained the anchor's name, and
    that is how 'Washington Depot Live Railcam - Washington, IA' ended up in
    Connecticut, 1528 km out: the anchor was Washington, Iowa, the candidate
    'Washington Depot' matched a village in Connecticut, and the name
    'washington' appears in both. (The title's ", IA" could not save it either -
    expected_state() reads the word 'Washington' as a state name too, so the
    state check had Iowa *or* Washington to satisfy and the village satisfied
    it.) So agreement now has to be administrative, and the shared area has to
    be finer than the country - every US result agrees on 'united states'.
    """
    if geo.get("atype") in SPREAD_TYPES or geo.get("typ") in SPREAD_KINDS:
        return False
    here, there = _areas(anchor.get("place")), _areas(geo.get("place"))
    if not (set(here[1:-1]) & set(there[1:-1])):     # [1:-1] = drop name, drop country
        return False
    return haversine(anchor["lat"], anchor["lon"], geo["lat"], geo["lon"]) <= NEAR_KM


# Where in a description a place is worth reading from. A description is not a
# title: it is long, it is written for humans, and most of its lines are about
# the channel rather than the camera. Taking the first line would pin cams on
# whatever city a sponsor happens to be in, so only two kinds of line count -
# one that says outright where the camera is, and one that names a country or a
# US state (which resolve() then has to agree with anyway).
MARKER = re.compile(r"(?i)(?:\U0001F4CD|location\s*[:\-]|located\s+(?:in|at)"
                    r"|filmed\s+(?:in|at)|streaming\s+(?:live\s+)?from"
                    r"|live\s+from|webcam\s+(?:in|at)|camera\s+(?:in|at))\s*(.+)")


# A place is a proper noun, so a hint without one is not a place. The marker
# words are ordinary English and catch ordinary English with them: "streaming
# live from our new (2025) floating taco boat" matched, and Nominatim answered
# it with Our Lady of Pompeii Catholic Church.
PROPER = re.compile(r"\b[A-Z][a-z]{2,}")


def place_hint(description):
    """The part of a description that might name a place - '' when none does."""
    lines = [l.strip(" \t-–—|·:") for l in re.split(r"[\n]", description or "") if l.strip()]
    for line in lines:
        m = MARKER.search(line)
        hint = m.group(1).strip()[:120] if m else ""
        if len(hint) > 2 and PROPER.search(hint):
            return hint
    for line in lines[:8]:
        if expected_cc(line) or expected_state(line):
            return line[:120]
    return ""


def resolve_cam(title, description=None, near=None, radius_km=None):
    """Place one cam: its title first, then its description.

    The title is the better evidence - it is short, and it is what the owner
    chose to name the camera. The description is only read when the title held
    no place at all, and what comes out of it goes through exactly the same
    checks.
    """
    query, geo = resolve(title, near=near, radius_km=radius_km)
    if geo:
        return query, geo
    hint = place_hint(description)
    if hint:
        return resolve(hint, near=near, radius_km=radius_km)
    return None, None


def resolve(title, near=None, radius_km=None):
    """Title -> (query used, geo). (None, None) when nothing matches.

    If the title names a country, the result must be in that country. Left
    unchecked, Nominatim fits a common one-word name somewhere in the world -
    'From' -> Norway, 'Members' -> Missouri, 'Elephants' -> Cameroun.

    `near`/`radius_km` add the same kind of check from the outside: the caller
    knows roughly where this cam's channel broadcasts from, so a result outside
    that circle is wrong however well it matches the words. That is what tells
    'Snow King Mountain Base - SeeJH.ai' (Wyoming) apart from the Snow King
    that Nominatim finds in Kyrgyzstan - the title says neither country, so
    nothing inside the title could have caught it.
    """
    want = expected_cc(title)
    want_state = expected_state(title)
    best = None                         # (candidate, geo) - most precise so far
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
        if near and haversine(near[0], near[1], g["lat"], g["lon"]) > radius_km:
            continue                    # outside the channel's area - reject
        if best is None:
            best = (cand, g)            # the first hit is the one to beat
        elif _rank(g) > _rank(best[1]) and _same_place(best[1], g):
            best = (cand, g)
        if _rank(best[1]) >= FINE_RANK:
            break                       # building level - nothing better to find
    return best or (None, None)

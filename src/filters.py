"""Junk-detection rules — the whole project gets them from here."""
import re

# One video touring many places -> cannot be tied to a single location
COMPILATION = re.compile(
    r"\b(\d{2,4}\s*(top|best|live)|top\s*\d{2,4}|tour|worldwide|around the world"
    r"|world live|random cams?|multi[- ]?cam|compilation|mix|playlist|montage"
    r"|relaxing music|with music|music\b)", re.I)

# Not a webcam channel (news / gaming / podcast and friends). Matched against
# *channel names* only - as a title filter it is far too eager: on a real crawl
# it dropped 'Indian Hill Trading Post', 'Korean Culture TV4' and a traffic cam
# captioned '(Travel News 4K)' to catch a single news broadcast. Titles get
# NEWSCAST below instead.
# 'news\d*' rather than 'news': a broadcaster puts its channel number straight
# on the word, and \b does not fire between 's' and '1', so 'News18 Gujarati'
# read as a webcam channel and brought five bulletins in with it.
NOTCAM = re.compile(
    r"\b(news\d*|tv\d|fox|abc|nbc|cbs|cnn|bbc|sky news|24 news"
    # Indian and pan-Asian broadcasters, for the same reason the American ones
    # are here: a 24-hour news feed is live and it is not a camera. They only
    # showed up once config/queries.txt started asking for India by name.
    r"|india today|aaj tak|ndtv|zee news|times now|republic bharat"
    r"|al jazeera|global review"
    r"|gaming|records|sermon|podcast|trading|crypto)\b", re.I)

# An actual news broadcast, for filtering *titles*. A news channel can sit in
# config/channels.json quite legitimately - ABC13 Houston runs four real city
# cams alongside its bulletin - so the channel stays and only the broadcast is
# dropped. Keyed on broadcast phrasing rather than the bare word 'news', which
# is why it matches 1 title in 1061 and no cams.
NEWSCAST = re.compile(
    r"(?i)\b(?:"
    r"(?:breaking|local|latest|world|national|business|sports?)\s+news"
    r"|news\s*(?:cast|room|desk|hour|live|now|update|bulletin|headlines?"
    r"|channel|network|cent(?:er|re))"
    r"|news\s+(?:and|&)\s+weather|weather\s+(?:and|&)\s+news"
    r"|top\s+stories|live\s+coverage|press\s+conference|24/?7\s+news"
    r")\b")

COUNTRIES = set("""usa uk italy spain greece france germany japan thailand australia canada
mexico brazil portugal norway sweden iceland switzerland austria croatia turkey egypt kenya
india china korea netherlands belgium poland ireland scotland wales denmark finland peru
chile argentina colombia indonesia philippines vietnam malaysia singapore africa botswana
zimbabwe namibia tanzania""".split())

GENERIC = {"Live","Cam","Webcam","Stream","Streaming","The","New","LIVE","Camera",
           "View","Now","Real","Time","HD"}

def place_like(title: str) -> bool:
    """Does this look like a cam pointed at one specific place?"""
    if COMPILATION.search(title):
        return False
    low = title.lower()
    if "," in title:
        return True
    if any(c in low for c in COUNTRIES):
        return True
    caps = re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", title)
    return len([c for c in caps if c not in GENERIC]) >= 1

CATEGORIES = [
    ("railway",  r"\b(train|rail|railfan|railway|locomotive|crossing|depot|yard)\b"),
    ("airport",  r"\b(airport|runway|airfield|aviation|terminal)\b"),
    ("wildlife", r"\b(safari|bear|elephant|wildlife|bird|zoo|aquarium|shark|animal"
                 r"|giraffe|lion|waterhole|nest|cat tv|feeder)\b"),
    ("beach",    r"\b(beach|surf|shore|pier|ocean|coast|bay)\b"),
    ("harbour",  r"\b(harbou?r|port|marina|dock|waterfront)\b"),
    ("nature",   r"\b(volcano|glacier|waterfall|mountain|lake|river|falls|national park"
                 r"|forest|valley|canyon|aurora|northern lights)\b"),
    ("city",     r"\b(square|street|downtown|skyline|plaza|boulevard|bridge|city|old town)\b"),
]

def categorize(title: str) -> str:
    low = title.lower()
    for name, pat in CATEGORIES:
        if re.search(pat, low):
            return name
    return "other"

"""Junk-detection rules — the whole project gets them from here."""
import re

# One video touring many places -> cannot be tied to a single location
COMPILATION = re.compile(
    r"\b(\d{2,4}\s*(top|best|live)|top\s*\d{2,4}|tour|worldwide|around the world"
    r"|world live|random cams?|multi[- ]?cam|compilation|mix|playlist|montage"
    r"|relaxing music|with music|music\b)", re.I)

# Not a webcam channel (news / gaming / podcast and friends)
NOTCAM = re.compile(
    r"\b(news|tv\d|fox|abc|nbc|cbs|cnn|bbc|sky news|24 news"
    r"|gaming|records|sermon|podcast|trading|crypto)\b", re.I)

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

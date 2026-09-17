"""Find a cam by place name.
   Usage:  python3 src/search.py "Times Square" "Taj Mahal"
   Note:   when there is no cam there, it says how far the nearest one is
           instead of giving a wrong answer."""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
from places import geocode, haversine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RADIUS_KM = 60


def load_index():
    return json.load(open(os.path.join(ROOT, "data", "index.json")))


def _variants(q):
    """Nominatim does not understand 'Venice Italy' — also try comma'd forms."""
    q = q.strip()
    seen, out = set(), []
    for v in (q, q.replace(" ", ", ", 1) if " " in q else None,
              q.rsplit(" ", 1)[0] + ", " + q.rsplit(" ", 1)[1] if " " in q else None,
              q.split(",")[0].strip() if "," in q else None):
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def geo_query(query):
    """query -> coordinates, trying several phrasings."""
    for v in _variants(query):
        g = geocode(v)
        if g:
            return g
    return None


def search(query, index=None, radius_km=RADIUS_KM, limit=5, category=None):
    """Return (status, results). status = ok | far | unknown"""
    index = index if index is not None else load_index()
    g = geo_query(query)
    if not g:
        return "unknown", []
    rows = [c for c in index if not category or c.get("category") == category]
    hits = sorted(((haversine(g["lat"], g["lon"], c["lat"], c["lon"]), c) for c in rows),
                  key=lambda x: x[0])
    near = [(d, c) for d, c in hits if d <= radius_km][:limit]
    if near:
        return "ok", near
    return ("far", hits[:1]) if hits else ("unknown", [])


def main():
    index = load_index()
    for q in sys.argv[1:]:
        status, res = search(q, index)
        print(f"\n{q}")
        if status == "unknown":
            print("   place not recognised")
            continue
        if status == "far":
            d, c = res[0]
            print(f"   no cam here. nearest is {d:.0f} km away:")
            print(f"      {c['title'][:56]}  [{c.get('category', '?')}]  {c['id']}")
            continue
        for d, c in res:
            print(f"   {d:5.1f} km  [{c.get('category', '?'):8}] {c['title'][:50]}  {c['id']}")


if __name__ == "__main__":
    main()

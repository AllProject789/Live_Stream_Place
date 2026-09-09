// haversine from search.py - distance between two coordinates, in km
export function haversine(lat1, lon1, lat2, lon2) {
  const R = 6371
  const rad = (d) => (d * Math.PI) / 180
  const dp = rad(lat2 - lat1)
  const dl = rad(lon2 - lon1)
  const h =
    Math.sin(dp / 2) ** 2 +
    Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dl / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

export function km(d) {
  if (d == null) return null
  return d < 1 ? `${Math.round(d * 1000)} m` : d < 100 ? `${d.toFixed(1)} km` : `${Math.round(d)} km`
}

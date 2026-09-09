// Mirrors the categories in filters.py (city|beach|wildlife|railway|airport|harbour|nature|other)
export const CATEGORY = {
  city:     { label: 'City',     emoji: '🏙️', color: '#f59e0b' },
  beach:    { label: 'Beach',    emoji: '🏖️', color: '#22d3ee' },
  wildlife: { label: 'Wildlife', emoji: '🦁', color: '#a3e635' },
  railway:  { label: 'Railway',  emoji: '🚆', color: '#c084fc' },
  airport:  { label: 'Airport',  emoji: '✈️', color: '#60a5fa' },
  harbour:  { label: 'Harbour',  emoji: '⚓', color: '#2dd4bf' },
  nature:   { label: 'Nature',   emoji: '🏔️', color: '#34d399' },
  other:    { label: 'Other',    emoji: '📹', color: '#f472b6' },
}

export const CATEGORY_ORDER = ['city', 'beach', 'nature', 'wildlife', 'railway', 'harbour', 'airport', 'other']

export const cat = (c) => CATEGORY[c] || CATEGORY.other

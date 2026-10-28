"""
DIGIPIN encoder/decoder — Python port of India Post's reference implementation
(github.com/INDIAPOST-gov/digipin, src/digipin.js).

DIGIPIN splits the India bounding box into a 4x4 grid ten times, giving a
10-character code for a ~4 m x 4 m cell. Characters exclude look-alikes
(no 0/1/O/I).
"""

DIGIPIN_GRID = (
    ("F", "C", "9", "8"),
    ("J", "3", "2", "7"),
    ("K", "4", "5", "6"),
    ("L", "M", "P", "T"),
)
MIN_LAT, MAX_LAT, MIN_LON, MAX_LON = 2.5, 38.5, 63.5, 99.5
_POSITION = {ch: (r, c) for r, row in enumerate(DIGIPIN_GRID) for c, ch in enumerate(row)}


def encode(lat: float, lon: float) -> str:
    if not MIN_LAT <= lat <= MAX_LAT:
        raise ValueError("Latitude out of range")
    if not MIN_LON <= lon <= MAX_LON:
        raise ValueError("Longitude out of range")
    min_lat, max_lat, min_lon, max_lon = MIN_LAT, MAX_LAT, MIN_LON, MAX_LON
    code = []
    for _ in range(10):
        lat_div = (max_lat - min_lat) / 4
        lon_div = (max_lon - min_lon) / 4
        # Row 0 is the northern band, matching the reference implementation.
        row = min(max(3 - int((lat - min_lat) // lat_div), 0), 3)
        col = min(max(int((lon - min_lon) // lon_div), 0), 3)
        code.append(DIGIPIN_GRID[row][col])
        max_lat = min_lat + lat_div * (4 - row)
        min_lat = min_lat + lat_div * (3 - row)
        min_lon = min_lon + lon_div * col
        max_lon = min_lon + lon_div
    return "".join(code)


def decode(code: str) -> tuple[float, float]:
    """Return the centre (lat, lon) of the DIGIPIN cell."""
    pin = code.strip().upper()
    if len(pin) != 10 or any(ch not in _POSITION for ch in pin):
        raise ValueError("Invalid DIGIPIN")
    min_lat, max_lat, min_lon, max_lon = MIN_LAT, MAX_LAT, MIN_LON, MAX_LON
    for ch in pin:
        r, c = _POSITION[ch]
        lat_div = (max_lat - min_lat) / 4
        lon_div = (max_lon - min_lon) / 4
        min_lat, max_lat = max_lat - lat_div * (r + 1), max_lat - lat_div * r
        min_lon, max_lon = min_lon + lon_div * c, min_lon + lon_div * (c + 1)
    return (min_lat + max_lat) / 2, (min_lon + max_lon) / 2

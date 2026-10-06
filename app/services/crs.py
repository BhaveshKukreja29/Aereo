import math

from pyproj import CRS
from pyproj.exceptions import CRSError

from app.services.errors import FileProcessingError


def crs_label(crs: CRS) -> str:
    authority = crs.to_authority()
    if authority == ("OGC", "CRS84"):
        return "EPSG:4326"
    if authority:
        return f"{authority[0]}:{authority[1]}"
    return crs.to_string()


def parse_crs(value) -> CRS:
    try:
        return CRS.from_user_input(value)
    except CRSError as exc:
        raise FileProcessingError("File CRS could not be read") from exc


def utm_epsg(latitude: float, longitude: float) -> str:
    # Zones are 6 degrees wide, starting at -180. North is 326xx, south is 327xx.
    zone = int((longitude + 180) // 6) + 1
    zone = min(max(zone, 1), 60)
    base = 32600 if latitude >= 0 else 32700
    return f"EPSG:{base + zone}"


def looks_like_lon_lat(bounds: tuple[float, float, float, float]) -> bool:
    minx, miny, maxx, maxy = bounds
    if not all(math.isfinite(value) for value in (minx, miny, maxx, maxy)):
        return False
    return -180 <= minx <= maxx <= 180 and -90 <= miny <= maxy <= 90

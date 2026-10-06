from dataclasses import dataclass

import geopandas as gpd
from pyproj import CRS

from app.services.crs import crs_label, utm_epsg
from app.services.errors import FileProcessingError

POLYGONS = {"Polygon", "MultiPolygon"}
LINES = {"LineString", "MultiLineString"}
POINTS = {"Point", "MultiPoint"}


@dataclass
class Measurement:
    area_m2: float | None = None
    length_m: float | None = None
    measurement_crs: str | None = None
    message: str | None = None


def measure_geometries(geometries: gpd.GeoSeries) -> list[Measurement]:
    if len(geometries) == 0:
        return []
    if geometries.crs is None:
        raise FileProcessingError("Features have no CRS")

    projected, label = _project_for_measurement(geometries, CRS.from_user_input(geometries.crs))
    return [_measure_one(geom, label) for geom in projected]


def _project_for_measurement(geometries: gpd.GeoSeries, crs: CRS) -> tuple[gpd.GeoSeries, str]:
    if crs.is_geographic:
        lonlat = geometries.to_crs(4326)
        minx, miny, maxx, maxy = lonlat.total_bounds
        code = utm_epsg((miny + maxy) / 2, (minx + maxx) / 2)
        try:
            return geometries.to_crs(code), code
        except Exception as exc:
            raise FileProcessingError("Could not project the file for measurement") from exc
    if crs.is_projected:
        return geometries, crs_label(crs)
    raise FileProcessingError("CRS cannot be used for measurements")


def _measure_one(geom, label: str) -> Measurement:
    if geom is None or geom.is_empty:
        return Measurement(message="Empty geometry")
    if geom.geom_type in POLYGONS:
        return Measurement(area_m2=round(float(geom.area), 3), measurement_crs=label)
    if geom.geom_type in LINES:
        return Measurement(length_m=round(float(geom.length), 3), measurement_crs=label)
    if geom.geom_type in POINTS:
        return Measurement()
    return Measurement(message="Geometry type is not supported for measurement")

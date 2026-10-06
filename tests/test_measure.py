import geopandas as gpd
import pytest
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon, box

from app.services.measure import measure_geometries

UTM43 = "EPSG:32643"


def _series(geoms, crs):
    return gpd.GeoSeries(geoms, crs=crs)


def test_geographic_square_is_measured_in_meters_not_degrees():
    # 1 degree by 1 degree. Shoelace on raw coordinates would return 1.
    geom = box(75, 27, 76, 28)
    measurement = measure_geometries(_series([geom], 4326))[0]

    assert measurement.measurement_crs == UTM43
    assert measurement.area_m2 == pytest.approx(1.091e10, rel=0.02)
    assert measurement.area_m2 > 1_000_000_000


def test_file_uses_one_utm_zone_from_the_middle():
    west = box(10, 27, 10.01, 27.01)
    east = box(75, 27, 75.01, 27.01)
    measured = measure_geometries(_series([west, east], 4326))

    assert measured[0].measurement_crs == measured[1].measurement_crs
    assert measured[0].area_m2 > 100_000
    assert measured[1].area_m2 > 100_000


def test_projected_polygon_with_hole_and_line_and_point():
    outer = box(500000, 3000000, 501000, 3001000)
    inner = box(500100, 3000100, 500200, 3000200)
    polygon = Polygon(outer.exterior.coords, [inner.exterior.coords])
    line = LineString([(500000, 3000000), (501000, 3000000)])
    measured = measure_geometries(_series([polygon, line, Point(500500, 3000500)], UTM43))

    assert polygon.area == 990_000
    assert measured[0].area_m2 == 990_000
    assert measured[0].measurement_crs == UTM43
    assert measured[0].length_m is None
    assert measured[1].length_m == 1_000
    assert measured[1].area_m2 is None
    assert measured[2].area_m2 is None
    assert measured[2].length_m is None
    assert measured[2].message is None


def test_multipolygon_areas_are_summed():
    geom = MultiPolygon([box(0, 0, 1000, 1000), box(2000, 0, 3500, 1000)])
    measurement = measure_geometries(_series([geom], UTM43))[0]
    assert measurement.area_m2 == 2_500_000


def test_geometry_collection_is_skipped():
    geom = GeometryCollection([box(0, 0, 10, 10), Point(0, 0)])
    measurement = measure_geometries(_series([geom], UTM43))[0]
    assert measurement.area_m2 is None
    assert measurement.message == "Geometry type is not supported for measurement"


def test_empty_geometry_is_reported_without_crashing():
    measurement = measure_geometries(_series([Polygon()], UTM43))[0]
    assert measurement.area_m2 is None
    assert measurement.message == "Empty geometry"



import io
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point, Polygon, box

from app.config import Settings
from app.main import create_app


def _square_gdf():
    outer = box(500000, 3000000, 501000, 3001000)
    inner = box(500100, 3000100, 500200, 3000200)
    polygon = Polygon(list(outer.exterior.coords), [list(inner.exterior.coords)])
    return gpd.GeoDataFrame(
        {"name": ["parcel", "road", "pin"]},
        geometry=[
            polygon,
            LineString([(500000, 3000000), (501000, 3000000)]),
            Point(500500, 3000500),
        ],
        crs="EPSG:32643",
    )


def _polygon_gdf():
    # A shapefile layer can only store one geometry type.
    return _square_gdf().iloc[[0]].set_geometry("geometry").reset_index(drop=True)


def _zip_shapefile(gdf: gpd.GeoDataFrame, directory: Path, name: str = "survey") -> Path:
    target = directory / "shp"
    target.mkdir()
    gdf.to_file(target / f"{name}.shp")
    archive_path = directory / f"{name}.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for path in target.iterdir():
            if path.suffix != ".zip":
                archive.write(path, path.name)
    return archive_path


def _kml_from_wgs84(gdf: gpd.GeoDataFrame) -> bytes:
    placemarks = []
    for _, row in gdf.to_crs(4326).iterrows():
        placemarks.append(_placemark(row["name"], row.geometry))
    body = "\n".join(placemarks)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    {body}
  </Document>
</kml>
"""
    return xml.encode()


def _coords(points) -> str:
    return " ".join(f"{x},{y},0" for x, y in points)


def _placemark(name: str, geom) -> str:
    if geom.geom_type == "Polygon":
        outer = _coords(geom.exterior.coords)
        holes = "".join(
            f"<innerBoundaryIs><LinearRing><coordinates>{_coords(ring.coords)}</coordinates></LinearRing></innerBoundaryIs>"
            for ring in geom.interiors
        )
        geometry = (
            f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{outer}</coordinates></LinearRing></outerBoundaryIs>{holes}</Polygon>"
        )
    elif geom.geom_type == "LineString":
        geometry = f"<LineString><coordinates>{_coords(geom.coords)}</coordinates></LineString>"
    elif geom.geom_type == "Point":
        geometry = f"<Point><coordinates>{geom.x},{geom.y},0</coordinates></Point>"
    else:
        raise AssertionError(geom.geom_type)
    return f"<Placemark><name>{name}</name>{geometry}</Placemark>"


def _upload(client, filename: str, content: bytes, content_type: str = "application/octet-stream"):
    return client.post("/api/files/", files={"file": (filename, io.BytesIO(content), content_type)})


def test_zipped_shapefile_measurements(client, tmp_path):
    archive = _zip_shapefile(_polygon_gdf(), tmp_path)
    response = _upload(client, "survey.zip", archive.read_bytes())
    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "survey.zip"
    assert body["feature_count"] == 1
    assert body["crs"] == "EPSG:32643"
    assert body["status"] == "COMPLETED"

    file_id = body["id"]
    info = client.get(f"/api/files/{file_id}/")
    assert info.status_code == 200
    assert info.json() == body

    measured = client.get(f"/api/files/{file_id}/measurements/")
    assert measured.status_code == 200
    payload = measured.json()
    assert len(payload["features"]) == 1
    parcel = payload["features"][0]

    assert parcel["id"] == 0
    assert parcel["geometry_type"] == "Polygon"
    assert parcel["crs"] == "EPSG:32643"
    assert parcel["properties"]["name"] == "parcel"
    assert parcel["geometry"]["type"] == "Polygon"
    assert parcel["measurement"]["area_m2"] == 990_000
    assert parcel["measurement"]["measurement_crs"] == "EPSG:32643"
    assert "length_m" not in parcel["measurement"]


def test_kml_uses_projected_crs_for_area_and_length(client):
    content = _kml_from_wgs84(_square_gdf())
    response = _upload(client, "survey.kml", content, "application/vnd.google-earth.kml+xml")
    assert response.status_code == 201
    body = response.json()
    assert body["crs"] == "EPSG:4326"
    assert body["feature_count"] == 3

    features = client.get(f"/api/files/{body['id']}/measurements/").json()["features"]
    assert features[0]["geometry_type"] == "Polygon"
    assert features[0]["measurement"]["area_m2"] == pytest.approx(990_000, rel=0.01)
    assert features[0]["measurement"]["measurement_crs"] == "EPSG:32643"
    assert features[1]["measurement"]["length_m"] == pytest.approx(1_000, rel=0.01)
    assert "measurement" not in features[2]
    assert features[0]["properties"]["Name"] == "parcel"
    assert features[1]["properties"]["Name"] == "road"
    assert features[2]["properties"]["Name"] == "pin"


def test_shapefile_without_prj_treats_lon_lat_as_wgs84(client, tmp_path):
    gdf = gpd.GeoDataFrame(geometry=[box(75, 27, 75.01, 27.01)], crs=4326)
    archive = _zip_shapefile(gdf, tmp_path, name="bare")
    with zipfile.ZipFile(archive, "r") as incoming:
        kept = {info.filename: incoming.read(info.filename) for info in incoming.infolist()}
    kept = {name: data for name, data in kept.items() if not name.lower().endswith(".prj")}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as outgoing:
        for name, data in kept.items():
            outgoing.writestr(name, data)

    response = _upload(client, "bare.zip", buffer.getvalue())
    assert response.status_code == 201
    assert response.json()["crs"] == "EPSG:4326"
    area = client.get(f"/api/files/{response.json()['id']}/measurements/").json()["features"][0]["measurement"]["area_m2"]
    assert area > 100_000
    assert area < 5_000_000


def test_shapefile_without_crs_or_geographic_coordinates_is_rejected(client, tmp_path):
    gdf = gpd.GeoDataFrame(geometry=[box(500000, 3000000, 501000, 3001000)], crs=4326)
    gdf = gdf.set_crs(4326, allow_override=True)
    # Write projected-looking numbers with the prj removed.
    gdf.geometry = [box(500000, 3000000, 501000, 3001000)]
    archive = _zip_shapefile(gdf, tmp_path, name="local")
    with zipfile.ZipFile(archive, "r") as incoming:
        kept = {
            info.filename: incoming.read(info.filename)
            for info in incoming.infolist()
            if not info.filename.lower().endswith(".prj")
        }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as outgoing:
        for name, data in kept.items():
            outgoing.writestr(name, data)

    response = _upload(client, "local.zip", buffer.getvalue())
    assert response.status_code == 400
    assert "prj" in response.json()["detail"].lower()


def test_empty_kml_is_a_completed_file_with_no_features(client):
    content = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document></Document></kml>
"""
    response = _upload(client, "empty.kml", content)
    assert response.status_code == 201
    body = response.json()
    assert body["feature_count"] == 0
    assert body["crs"] == "EPSG:4326"
    assert body["status"] == "COMPLETED"
    measured = client.get(f"/api/files/{body['id']}/measurements/")
    assert measured.status_code == 200
    assert measured.json()["features"] == []


def test_rejects_wrong_type_bad_zip_and_missing_file(client):
    rejected = _upload(client, "notes.txt", b"hello")
    assert rejected.status_code == 400

    empty = client.post("/api/files/", files={"file": ("empty.kml", io.BytesIO(b""), "application/xml")})
    assert empty.status_code == 400

    bogus = _upload(client, "nope.kml", b"<not-kml></not-kml>")
    assert bogus.status_code == 400

    missing_shp = io.BytesIO()
    with zipfile.ZipFile(missing_shp, "w") as archive:
        archive.writestr("readme.txt", "no shapefile here")
    response = _upload(client, "plain.zip", missing_shp.getvalue())
    assert response.status_code == 400

    slipped = io.BytesIO()
    with zipfile.ZipFile(slipped, "w") as archive:
        archive.writestr("../evil.shp", b"nope")
    slipped_response = _upload(client, "slip.zip", slipped.getvalue())
    assert slipped_response.status_code == 400

    assert client.get("/api/files/missing/").status_code == 404
    assert client.get("/api/files/missing/measurements/").status_code == 404


def test_upload_limit(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        data_dir=tmp_path / "data",
        max_upload_bytes=32,
    )
    with TestClient(create_app(settings)) as client:
        response = _upload(client, "survey.kml", b"x" * 64)
    assert response.status_code == 400
    assert "50 MB" not in response.json()["detail"]
    assert "limit" in response.json()["detail"].lower()

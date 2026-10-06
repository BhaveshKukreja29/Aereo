# Geospatial File Measurement API

A small API that takes a zipped shapefile or a KML file and returns the area or length of each feature.

If the coordinates are longitude/latitude, they get projected into a UTM zone first. Area and length come back in meters.

## Setup

Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open `http://127.0.0.1:8000/docs`.

`pyogrio` includes GDAL, so you don't have to install that separately.

```bash
pytest
```

You can change the database path, upload folder, or the 50 MB limit with `AEREO_DATABASE_URL`, `AEREO_DATA_DIR`, and `AEREO_MAX_UPLOAD_BYTES`.

## API

### Upload

`POST /api/files/`

Multipart field name is `file`.

- `.zip` with one shapefile (`.shp`, `.shx`, `.dbf`, and `.prj` if you have it)
- `.kml`

```bash
curl -F "file=@survey.zip" http://127.0.0.1:8000/api/files/
```

```json
{
  "id": "e729ec05005047c799d8c889eb48fea7",
  "filename": "survey.zip",
  "feature_count": 1,
  "crs": "EPSG:32643",
  "status": "COMPLETED"
}
```

The file is processed before this response is sent, so `status` is `COMPLETED`. A bad file returns `400`.

### File information

`GET /api/files/{id}/`

Same JSON as the upload response.

### Measurements

`GET /api/files/{id}/measurements/`

```json
{
  "file_id": "e729ec05005047c799d8c889eb48fea7",
  "features": [
    {
      "id": 0,
      "geometry_type": "Polygon",
      "geometry": {"type": "Polygon", "coordinates": [[[75.0, 27.12], [75.01, 27.12], [75.01, 27.13], [75.0, 27.12]]]},
      "crs": "EPSG:4326",
      "properties": {"Name": "parcel"},
      "measurement": {"area_m2": 990000.0, "measurement_crs": "EPSG:32643"}
    },
    {
      "id": 1,
      "geometry_type": "LineString",
      "geometry": {"type": "LineString", "coordinates": [[75.0, 27.12], [75.01, 27.12]]},
      "crs": "EPSG:4326",
      "properties": {"Name": "road"},
      "measurement": {"length_m": 1000.0, "measurement_crs": "EPSG:32643"}
    },
    {
      "id": 2,
      "geometry_type": "Point",
      "geometry": {"type": "Point", "coordinates": [75.0, 27.1]},
      "crs": "EPSG:4326",
      "properties": {"Name": "pin"}
    }
  ]
}
```

`id` is just the feature index. `geometry` is GeoJSON. `properties` are the attributes from the file. Coordinates in the example are shortened.

Polygons (including multipolygons) get `area_m2`. Lines get `length_m`. Points have no `measurement`. Anything else stays in the list with a `message`, and the rest of the file still comes back. Holes in a polygon are subtracted, because that's how the geometry area works.

KML names show up as `Name`. The reader also adds a few extra fields like `tessellate` and `visibility`.

## Architecture

```
app/
  main.py              starts the app
  api/files.py         the three endpoints
  services/archive.py  unzip and find the .shp
  services/reader.py   read the features
  services/measure.py  area and length
  services/crs.py      UTM zone and CRS name
  models.py            SQLite tables
```

### File processing

1. Save the upload (max 50 MB).
2. If it's a zip, reject paths with `..`, unzip it, and look for one `.shp` plus `.shx` and `.dbf`.
3. Read the features with `pyogrio`.
4. Measure them.
5. Save one row for the file and one row per feature. Geometry is stored as GeoJSON, next to the measurement.

### Measurement

Point: nothing. Line or MultiLineString: length. Polygon or MultiPolygon: area. Other types: a message, and we move on.

### CRS

If the file is already in a projected CRS, I measure it as-is and assume the units are meters.

If it's longitude/latitude, I take the middle of the file, pick a UTM zone from that, project the whole file into that zone, then measure. The zone is returned as `measurement_crs`, like `EPSG:32643`.

KML with no CRS is treated as EPSG:4326. A shapefile with no `.prj` is treated as EPSG:4326 only when the numbers look like longitude/latitude. Otherwise the upload is rejected.

## Design decisions

FastAPI, because this is three endpoints. SQLite, because I just needed to store the result and read it back.

I calculate the measurements on upload. The GET calls only read what was saved.

For the projection I use one UTM zone for the whole file, from the center. The zone number is `floor((longitude + 180) / 6) + 1`. Northern hemisphere codes are `32600 + zone`, southern are `32700 + zone`. This is fine when the file is a survey in one region. A file spread across a continent will be less accurate, since one zone can't cover that well.

## Learning

Longitude and latitude are degrees. If you calculate area on those numbers directly, a 1 by 1 degree square comes out as 1, which is nonsense. It's actually on the order of 10,000 square kilometers. So the projection step is required before calling area or length.

A shapefile is several files. `.shp` is the geometry, `.shx` is the index, `.dbf` is the attributes, `.prj` is the CRS. That's why the upload is a zip.

KML is longitude/latitude on WGS84, and one file can mix points, lines, and polygons. A shapefile layer can't.

## Future scope

- GeoJSON
- A background job for bigger files, and a real `PROCESSING` / `FAILED` status
- A better projection when the file covers a large area
- PostGIS, if we ever need to query by location

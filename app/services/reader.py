import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import geopandas as gpd
import pyogrio
from shapely.geometry import mapping

from app.services.crs import crs_label, looks_like_lon_lat, parse_crs
from app.services.errors import FileProcessingError
from app.services.measure import measure_geometries

@dataclass
class StoredFeature:
    feature_index: int
    geometry_type: str
    geometry: dict | None
    crs: str | None
    properties: dict
    area_m2: float | None = None
    length_m: float | None = None
    measurement_crs: str | None = None
    message: str | None = None


def read_and_measure(path: Path, *, kind: str) -> tuple[str | None, list[StoredFeature]]:
    frames = [_prepare(frame, kind) for frame in _read_layers(path)]
    features: list[StoredFeature] = []
    for frame in frames:
        features.extend(_features_from_frame(frame, start=len(features)))
    return _file_crs(frames), features


def _read_layers(path: Path) -> list[gpd.GeoDataFrame]:
    try:
        layers = pyogrio.list_layers(path)
    except Exception as exc:
        raise FileProcessingError(f"Could not read the geospatial file: {_short(exc)}") from exc

    if len(layers) == 0:
        return [gpd.GeoDataFrame(geometry=[], crs=None)]

    frames: list[gpd.GeoDataFrame] = []
    errors: list[str] = []
    for name in (str(row[0]) for row in layers):
        try:
            frames.append(pyogrio.read_dataframe(path, layer=name))
        except Exception as exc:
            errors.append(_short(exc))
    if not frames:
        detail = errors[0] if errors else "file has no layers"
        raise FileProcessingError(f"Could not read the geospatial file: {detail}")
    return frames


def _prepare(frame: gpd.GeoDataFrame, kind: str) -> gpd.GeoDataFrame:
    if frame.crs is not None:
        return frame.set_crs(parse_crs(frame.crs), allow_override=True)
    if len(frame) == 0:
        return frame.set_crs(4326) if kind == "kml" else frame
    if kind == "kml" or looks_like_lon_lat(tuple(frame.total_bounds)):
        return frame.set_crs(4326)
    raise FileProcessingError(
        "Shapefile has no .prj and coordinates do not look like longitude/latitude"
    )


def _features_from_frame(frame: gpd.GeoDataFrame, start: int) -> list[StoredFeature]:
    if len(frame) == 0:
        return []
    measured = measure_geometries(frame.geometry)
    label = crs_label(parse_crs(frame.crs)) if frame.crs is not None else None
    properties = _properties(frame)
    features: list[StoredFeature] = []
    for offset, (geom, item, props) in enumerate(zip(frame.geometry, measured, properties)):
        features.append(
            StoredFeature(
                feature_index=start + offset,
                geometry_type=_geom_type(geom),
                geometry=_geojson(geom),
                crs=label,
                properties=props,
                area_m2=item.area_m2,
                length_m=item.length_m,
                measurement_crs=item.measurement_crs,
                message=item.message,
            )
        )
    return features


def _properties(frame: gpd.GeoDataFrame) -> list[dict]:
    table = frame.drop(columns=[frame.geometry.name]).dropna(axis=1, how="all").reset_index(drop=True)
    rows = []
    for record in table.to_dict(orient="records"):
        cleaned = {}
        for key, value in record.items():
            safe = _json_safe(value)
            if safe is not None:
                cleaned[str(key)] = safe
        rows.append(cleaned)
    return rows


def _file_crs(frames: list[gpd.GeoDataFrame]) -> str | None:
    labels = [crs_label(parse_crs(frame.crs)) for frame in frames if frame.crs is not None]
    if not labels:
        return None
    if all(label == labels[0] for label in labels):
        return labels[0]
    return "MIXED"


def _geom_type(geom) -> str:
    if geom is None:
        return "Unknown"
    return geom.geom_type or "Unknown"


def _geojson(geom) -> dict | None:
    if geom is None or geom.is_empty:
        return None
    return _json_safe(mapping(geom))


def _json_safe(value):
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if type(value).__name__ in {"NAType", "NaTType"}:
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_safe(item())
        except Exception:
            return str(value)
    return str(value)


def _short(exc: Exception) -> str:
    text = str(exc).strip().splitlines()
    return (text[0] if text else "unknown error")[:300]

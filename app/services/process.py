from pathlib import Path

from app.models import Feature, GeoFile
from app.services.archive import extract_shapefile_zip
from app.services.errors import FileProcessingError
from app.services.reader import read_and_measure


def ingest_file(path: Path, *, file_id: str, filename: str) -> GeoFile:
    suffix = path.suffix.lower()
    if suffix == ".kml":
        source = path
        kind = "kml"
    elif suffix == ".zip":
        source = extract_shapefile_zip(path, path.parent / "extracted")
        kind = "shapefile"
    else:
        raise FileProcessingError("Only .zip (shapefile) and .kml files are accepted")

    crs, features = read_and_measure(source, kind=kind)
    return GeoFile(
        id=file_id,
        filename=filename,
        feature_count=len(features),
        crs=crs,
        status="COMPLETED",
        features=[Feature(**feature.__dict__) for feature in features],
    )

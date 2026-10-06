import asyncio
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Feature, GeoFile
from app.schemas import FeatureOut, FileOut, MeasurementOut, MeasurementsOut
from app.services.errors import FileProcessingError
from app.services.process import ingest_file

router = APIRouter(prefix="/files", tags=["files"])


def db_session(request: Request):
    yield from get_session(request.app.state.session_factory)


@router.post("/", status_code=201, response_model=FileOut)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(db_session),
) -> FileOut:
    """Upload a zipped shapefile or a KML file and measure its features."""
    settings = request.app.state.settings
    filename = _safe_filename(file.filename or "upload")
    if Path(filename).suffix.lower() not in {".zip", ".kml"}:
        raise HTTPException(status_code=400, detail="Only .zip (shapefile) and .kml files are accepted")

    file_id = uuid.uuid4().hex
    dest_dir = settings.data_dir / "uploads" / file_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    stored = dest_dir / filename
    try:
        await _write_upload(file, stored, settings.max_upload_bytes)
        record = await asyncio.to_thread(
            ingest_file,
            stored,
            file_id=file_id,
            filename=filename,
        )
        db.add(record)
        db.commit()
    except FileProcessingError as exc:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise
    return _file_out(record)


@router.get("/{file_id}/", response_model=FileOut)
def get_file(file_id: str, db: Session = Depends(db_session)) -> FileOut:
    return _file_out(_get_or_404(db, file_id))


@router.get("/{file_id}/measurements/", response_model=MeasurementsOut, response_model_exclude_none=True)
def get_measurements(file_id: str, db: Session = Depends(db_session)) -> MeasurementsOut:
    record = _get_or_404(db, file_id)
    rows = db.scalars(
        select(Feature).where(Feature.file_id == file_id).order_by(Feature.feature_index)
    ).all()
    return MeasurementsOut(file_id=record.id, features=[_feature_out(row) for row in rows])


def _get_or_404(db: Session, file_id: str) -> GeoFile:
    record = db.get(GeoFile, file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found")
    return record


def _file_out(record: GeoFile) -> FileOut:
    return FileOut(
        id=record.id,
        filename=record.filename,
        feature_count=record.feature_count,
        crs=record.crs,
        status=record.status,
    )


def _feature_out(row: Feature) -> FeatureOut:
    measurement = None
    if row.area_m2 is not None or row.length_m is not None:
        measurement = MeasurementOut(
            area_m2=row.area_m2,
            length_m=row.length_m,
            measurement_crs=row.measurement_crs,
        )
    return FeatureOut(
        id=row.feature_index,
        geometry_type=row.geometry_type,
        geometry=row.geometry,
        crs=row.crs,
        properties=row.properties or {},
        measurement=measurement,
        message=row.message,
    )


def _safe_filename(name: str) -> str:
    base = Path(name).name.replace("\x00", "").strip()
    if not base or base in {".", ".."}:
        return "upload"
    return base[:255]


async def _write_upload(upload: UploadFile, dest: Path, max_bytes: int) -> None:
    size = 0
    try:
        with dest.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise FileProcessingError("File exceeds the upload limit")
                handle.write(chunk)
    finally:
        await upload.close()
    if size == 0:
        raise FileProcessingError("Uploaded file is empty")

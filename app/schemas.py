from pydantic import BaseModel


class FileOut(BaseModel):
    id: str
    filename: str
    feature_count: int
    crs: str | None
    status: str


class MeasurementOut(BaseModel):
    area_m2: float | None = None
    length_m: float | None = None
    measurement_crs: str | None = None


class FeatureOut(BaseModel):
    id: int
    geometry_type: str
    geometry: dict | None
    crs: str | None
    properties: dict
    measurement: MeasurementOut | None = None
    message: str | None = None


class MeasurementsOut(BaseModel):
    file_id: str
    features: list[FeatureOut]

import zipfile
from pathlib import Path

from app.services.errors import FileProcessingError

def extract_shapefile_zip(zip_path: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            _reject_unsafe_paths(archive, dest)
            archive.extractall(dest)
    except zipfile.BadZipFile as exc:
        raise FileProcessingError("Uploaded .zip is not a valid zip archive") from exc

    shapefiles = _find_shapefiles(dest)
    if not shapefiles:
        raise FileProcessingError("Zip does not contain a .shp file")
    if len(shapefiles) > 1:
        raise FileProcessingError("Zip contains more than one shapefile")

    shapefile = shapefiles[0]
    missing = [suffix for suffix in (".shx", ".dbf") if not _has_sibling(shapefile, suffix)]
    if missing:
        raise FileProcessingError(
            f"Shapefile is missing required sidecar files: {', '.join(missing)}"
        )
    return shapefile


def _reject_unsafe_paths(archive: zipfile.ZipFile, dest: Path) -> None:
    root = dest.resolve()
    for info in archive.infolist():
        member = Path(info.filename)
        if "\x00" in info.filename or member.is_absolute() or ".." in member.parts:
            raise FileProcessingError("Zip contains an unsafe path")
        if not (dest / member).resolve().is_relative_to(root):
            raise FileProcessingError("Zip contains an unsafe path")


def _find_shapefiles(dest: Path) -> list[Path]:
    found = []
    for path in dest.rglob("*"):
        if not path.is_file() or path.suffix.lower() != ".shp":
            continue
        parts = path.relative_to(dest).parts
        if any(part == "__MACOSX" or part.startswith(".") for part in parts):
            continue
        found.append(path)
    return found


def _has_sibling(shapefile: Path, suffix: str) -> bool:
    expected = f"{shapefile.stem}{suffix}".lower()
    return any(path.is_file() and path.name.lower() == expected for path in shapefile.parent.iterdir())

from fastapi import FastAPI

from app.api.files import router
from app.config import Settings, get_settings
from app.db import init_db, make_engine, make_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    init_db(settings, engine)
    app = FastAPI(title="Geospatial File Measurement API", version="1.0.0")
    app.state.settings = settings
    app.state.session_factory = make_session_factory(engine)
    app.include_router(router, prefix="/api")
    return app


app = create_app()

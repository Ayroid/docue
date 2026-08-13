import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

logger = logging.getLogger("app.db")

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def masked_url() -> str:
    url = engine.url
    return f"{url.drivername}://{url.username}:***@{url.host}:{url.port}/{url.database}"


def check_db_connection() -> None:
    logger.info("Connecting to database %s ...", masked_url())
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Database connection FAILED at startup (%s)", masked_url())
        raise
    logger.info("Database connection OK (%s)", masked_url())

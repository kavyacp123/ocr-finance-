from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.config import settings
from app.database.models import Base
from app.utils.logging import logger

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """
    Initializes database tables.
    """
    logger.info(f"DATABASE_INIT: Connecting to database at '{settings.DATABASE_URL}'...")
    Base.metadata.create_all(bind=engine)
    logger.info("DATABASE_INIT: Database tables verified and ready.")


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a database session and ensures clean closure.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

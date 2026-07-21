from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

from app.config.tenant_session import TenantSession

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is required. Copy backend/.env.example to backend/.env "
        "or export DATABASE_URL before starting the API."
    )

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
TenantSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=TenantSession,
)

from app.models.base import Base

def get_unscoped_db():
    """Yield an unscoped Session for global tables only.

    Never use this dependency for tenant business data. Tenant-aware request
    dependencies must resolve trusted tenant context and open a TenantSession.
    """

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db():
    """Legacy unscoped dependency retained until tenant routes migrate."""

    yield from get_unscoped_db()

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.generate import router as generate_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.search import router as search_router
from app.api.v1.sessions import router as sessions_router
from app.api.v1.templates import router as templates_router
from app.api.v1.versions import router as versions_router
from app.core.config import settings
from app.db.session import check_db_connection

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_db_connection()
    yield


app = FastAPI(title="TemplateHub API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(templates_router, prefix="/api/v1")
app.include_router(search_router, prefix="/api/v1")
app.include_router(generate_router, prefix="/api/v1")
app.include_router(sessions_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
# After `templates_router`: both own paths under /templates/{id}, and the
# history route here must not shadow its `GET /templates/{template_id}`.
app.include_router(versions_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

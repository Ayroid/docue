import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.access import router as access_router
from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.documents import router as documents_router
from app.api.v1.generate import router as generate_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.search import router as search_router
from app.api.v1.sessions import router as sessions_router
from app.api.v1.templates import router as templates_router
from app.api.v1.versions import router as versions_router
from app.core.config import settings
from app.db.session import check_db_connection
from app.storage.s3 import ensure_bucket

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("app")


def check_llm_credentials() -> None:
    """Say at startup whether the model stages can run at all.

    Every stage catches `BedrockError` and degrades quietly on purpose -- an
    outage should cost a longer interview, not a 500. The cost of that design
    is that a *configuration* problem is indistinguishable from an outage. So
    the check happens once, here: no live call (a live request at startup
    would cost time/quota on every reload for no benefit), just whether an
    API key is present.
    """
    if not settings.llm_api_key:
        logger.error(
            "LLM proxy has NO credentials: LLM_API_KEY is unset. Every model "
            "stage will fail and the app will report itself as running "
            "without the language model -- questions grouped structurally, "
            "nothing extracted, nothing derived. Set LLM_API_KEY in .env and "
            "restart."
        )
        return
    logger.info("LLM proxy: using LLM_API_KEY against %s", settings.llm_base_url)


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_db_connection()
    try:
        ensure_bucket()
    except Exception:
        logger.exception("Could not ensure S3 bucket '%s' exists", settings.s3_bucket_name)
    check_llm_credentials()
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
app.include_router(documents_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
# Before nothing in particular, but kept next to `admin_router`: it owns
# /admin/templates/{id}/access and shares that router's admin-only contract.
app.include_router(access_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
# After `templates_router`: both own paths under /templates/{id}, and the
# history route here must not shadow its `GET /templates/{template_id}`.
app.include_router(versions_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

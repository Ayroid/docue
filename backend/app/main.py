import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("app")


def check_bedrock_credentials() -> None:
    """Say at startup whether the model stages can run at all.

    Every stage catches `BedrockError` and degrades quietly on purpose -- an
    outage should cost a longer interview, not a 500. The cost of that design is
    that a *configuration* problem is indistinguishable from an outage, and it
    surfaces one screen at a time: "the questions are grouped structurally",
    "the extractor was unavailable", "derivation was unavailable". Three
    messages, no cause named, nothing in the log but warnings.

    So the check happens once, here, where it can name the fix. It resolves
    credentials without calling Bedrock -- a live `InvokeModel` at startup would
    cost money on every reload and fail for reasons that are not configuration.
    """
    import boto3

    if settings.aws_bearer_token_bedrock:
        logger.info("Bedrock: using the API key from AWS_BEARER_TOKEN_BEDROCK")
        return
    if boto3.Session().get_credentials() is not None:
        logger.info(
            "Bedrock: no AWS_BEARER_TOKEN_BEDROCK; falling back to the default "
            "credential chain, which must hold bedrock:InvokeModel"
        )
        return
    logger.error(
        "Bedrock has NO credentials: AWS_BEARER_TOKEN_BEDROCK is unset and the "
        "default credential chain resolved nothing. Every model stage will fail "
        "and the app will report itself as running without the language model -- "
        "questions grouped structurally, nothing extracted, nothing derived. "
        "Set AWS_BEARER_TOKEN_BEDROCK in .env (the ABSK... key, not an "
        "access-key pair) and restart."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_db_connection()
    check_bedrock_credentials()
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
app.include_router(notifications_router, prefix="/api/v1")
# After `templates_router`: both own paths under /templates/{id}, and the
# history route here must not shadow its `GET /templates/{template_id}`.
app.include_router(versions_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

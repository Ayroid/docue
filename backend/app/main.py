from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.templates import router as templates_router
from app.core.config import settings

app = FastAPI(title="TemplateHub API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(templates_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

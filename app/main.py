import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config_store import ensure_self_host_schema
from .routes import auth as auth_routes
from .routes import threads as thread_routes
from .routes import senders as sender_routes
from .routes import config as config_routes
from .routes import stats as stats_routes
from .routes import folders as folder_routes
from .routes import contacts as contact_routes
from .routes import business as business_routes
from .routes import translate as translate_routes
from .routes import search as search_routes
from .routes import rules as rules_routes
from .routes import drafts as draft_routes
from .routes import templates as template_routes
from .routes import attachments as attachment_routes
from .routes import scheduled as scheduled_routes
from .routes import exports as export_routes
from .routes import setup as setup_routes

app = FastAPI(title="mailhub API", version="0.1.0")


@app.on_event("startup")
def startup_schema_check():
    ensure_self_host_schema()


def _cors_origins() -> list[str]:
    raw = os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:3024,http://127.0.0.1:3024",
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(thread_routes.router)
app.include_router(sender_routes.router)
app.include_router(config_routes.router)
app.include_router(stats_routes.router)
app.include_router(folder_routes.router)
app.include_router(contact_routes.router)
app.include_router(business_routes.router)
app.include_router(translate_routes.router)
app.include_router(search_routes.router)
app.include_router(rules_routes.router)
app.include_router(draft_routes.router)
app.include_router(template_routes.router)
app.include_router(attachment_routes.router)
app.include_router(scheduled_routes.router)
app.include_router(export_routes.router)
app.include_router(setup_routes.router)


@app.get("/api/healthz")
def healthz():
    return {"ok": True}

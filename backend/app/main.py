from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.graph import close_agent, init_agent
from app.core.config import settings
from app.core.logging import configure_logging, logger
from app.core.request_logging import RequestLoggingMiddleware
from app.routers import (
    agent,
    auth,
    customers,
    formulas,
    kanban,
    machines,
    orders,
    patterns,
    product_categories,
    production_tasks,
    products,
)

configure_logging()

if settings.SENTRY_DSN:
    sentry_sdk.init(dsn=settings.SENTRY_DSN, environment=settings.ENVIRONMENT, traces_sample_rate=0.1)
    logger.info("sentry_enabled", environment=settings.ENVIRONMENT)
else:
    logger.info("sentry_disabled", reason="SENTRY_DSN not set")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Bring up the LangGraph agent (checkpointer pool + compiled graph).
    try:
        await init_agent()
        logger.info("agent_initialized")
    except Exception as err:  # noqa: BLE001
        logger.error("agent_init_failed", error=str(err))
    yield
    await close_agent()


app = FastAPI(title="FilmOS Backend", lifespan=lifespan)

app.add_middleware(RequestLoggingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(auth.router, prefix="/api")

for router in (
    product_categories.router,
    patterns.router,
    customers.router,
    machines.router,
    products.router,
    formulas.router,
    orders.router,
    production_tasks.router,
    kanban.router,
    agent.router,
):
    app.include_router(router, prefix="/api")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from database import create_tables
from config import settings
from routes import auth, orders, services, payments, admin, developer, transactions, manual_payments

@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    if settings.ENVIRONMENT == "production" and (not settings.JWT_SECRET_KEY or not settings.JWT_REFRESH_SECRET):
        raise RuntimeError(
            "JWT_SECRET_KEY and JWT_REFRESH_SECRET must be set via environment variables in production — refusing to start "
            "with an auto-generated secret that would invalidate all sessions on every restart."
        )
    yield

app = FastAPI(
    title="BOASTLIB API",
    version="1.0.0",
    description="SMM Panel API — Cheapest prices, fastest delivery",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__}
    )

# Include all routers
app.include_router(auth.router)
app.include_router(orders.router)
app.include_router(services.router)
app.include_router(payments.router)
app.include_router(manual_payments.router)
app.include_router(manual_payments.admin_router)
app.include_router(admin.router)
app.include_router(developer.router)
app.include_router(transactions.router)

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": settings.APP_VERSION, "app": settings.APP_NAME}

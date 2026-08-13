import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from database import create_tables
from config import settings
from routes import auth, orders, services, payments, admin, developer, transactions, manual_payments, giveaway
from routes import tickets, webhooks
from services.order_sync import start_order_status_sync, stop_order_status_sync
import os
import traceback

@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    if settings.ENVIRONMENT == "production" and (not settings.JWT_SECRET_KEY or not settings.JWT_REFRESH_SECRET):
        raise RuntimeError(
            "JWT_SECRET_KEY and JWT_REFRESH_SECRET must be set via environment variables in production — refusing to start "
            "with an auto-generated secret that would invalidate all sessions on every restart."
        )
    
    # Log payment provider configuration
    if settings.PAYSTACK_SECRET_KEY:
        print(f"✓ Paystack configured (Card Payments)")
    else:
        print(f"✗ Paystack NOT configured — card payments will fail")
    
    if settings.PAWAPAY_API_KEY:
        print(f"✓ PawaPay configured (Mobile Money)")
    else:
        print(f"✗ PawaPay NOT configured — mobile money payments will fail")

    if settings.BREVO_API_KEY:
        print(f"✓ Brevo configured (sender: {settings.FROM_EMAIL})")
    else:
        print(f"✗ Brevo API key not configured — password reset and ticket email notifications will fail")

    # Start background status sync loop
    sync_task = start_order_status_sync()
    try:
        yield
    finally:
        stop_order_status_sync(sync_task)

app = FastAPI(
    title="BOASTLIB API",
    version="1.0.0",
    description="SMM Panel API — Cheapest prices, fastest delivery",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|(?:www\.)?boastlib\.space|.*\.vercel\.app|.*\.railway\.app)(?::\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Print full traceback to stdout so platform logs capture the stack trace for debugging
    try:
        print(f"Unhandled exception for request: {request.method} {request.url}")
        traceback.print_exc()
    except Exception:
        pass
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
app.include_router(giveaway.router)
app.include_router(tickets.router)
app.include_router(webhooks.router)

app.mount('/uploads', StaticFiles(directory=os.path.join(os.path.dirname(__file__), 'uploads')), name='uploads')

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": settings.APP_VERSION, "app": settings.APP_NAME}

@app.get("/api/version")
async def version():
    return {
        "version": settings.APP_VERSION,
        "app": settings.APP_NAME,
        "commit": os.environ.get("RAILWAY_GIT_COMMIT_SHA", "unknown"),
    }

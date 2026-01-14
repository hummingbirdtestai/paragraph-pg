# main_onlinembbs.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from payments import router as payments_router
import logging

from newchat_onlinembbs import router as mbbs_router

# ───────────────────────────────────────────────
# LOGGING (match old service)
# ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logging.getLogger("ask_paragraph").setLevel(logging.DEBUG)

# ───────────────────────────────────────────────
# FASTAPI APP
# ───────────────────────────────────────────────
app = FastAPI(
    title="Ask Paragraph MBBS API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten later if needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───────────────────────────────────────────────
# ROUTERS
# ───────────────────────────────────────────────
app.include_router(
    mbbs_router,
    prefix="/ask-paragraph-mbbs",
    tags=["MBBS Diagnostic Tutor"],
)

# Payments (Cashfree webhooks + initiate)
app.include_router(payments_router)

# ───────────────────────────────────────────────
# HEALTH
# ───────────────────────────────────────────────
@app.get("/")
def health():
    return {
        "service": "ask-paragraph-mbbs",
        "status": "running"
    }

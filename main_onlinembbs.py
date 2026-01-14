# main_onlinembbs.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

# ✅ IMPORTANT: import the MBBS-specific payments router
from payments_onlinembbs import router as payments_onlinembbs_router
from newchat_onlinembbs import router as mbbs_router

# ───────────────────────────────────────────────
# LOGGING
# ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logging.getLogger("ask_paragraph").setLevel(logging.DEBUG)
logging.getLogger("payments").setLevel(logging.INFO)

# ───────────────────────────────────────────────
# FASTAPI APP
# ───────────────────────────────────────────────
app = FastAPI(
    title="Ask Paragraph MBBS API",
    version="1.0.0",
)

# ───────────────────────────────────────────────
# CORS
# ───────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───────────────────────────────────────────────
# ROUTERS
# ───────────────────────────────────────────────

# MBBS Tutor / Chat
app.include_router(
    mbbs_router,
    prefix="/ask-paragraph-mbbs",
    tags=["MBBS Diagnostic Tutor"],
)

# ✅ MBBS Payments ONLY (Cashfree)
app.include_router(
    payments_onlinembbs_router,
    tags=["MBBS Payments"],
)

# ───────────────────────────────────────────────
# HEALTH CHECK
# ───────────────────────────────────────────────
@app.get("/")
def health():
    return {
        "service": "ask-paragraph-mbbs",
        "status": "running",
    }

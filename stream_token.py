# stream_token.py

import os
import traceback
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from getstream.video import StreamVideo

router = APIRouter()

# ───────────────────────────────────────────────
# 🔐 Environment Config
# ───────────────────────────────────────────────

STREAM_API_KEY = os.getenv("STREAM_API_KEY")
STREAM_API_SECRET = os.getenv("STREAM_API_SECRET")

if not STREAM_API_KEY or not STREAM_API_SECRET:
    raise RuntimeError("❌ STREAM_API_KEY or STREAM_API_SECRET not configured")

print("✅ Stream Video ENV Loaded")
print("🔑 STREAM_API_KEY:", STREAM_API_KEY)

video_client = StreamVideo(
    api_key=STREAM_API_KEY,
    api_secret=STREAM_API_SECRET,
)

print("✅ Stream Video client initialized")


# ───────────────────────────────────────────────
# 📦 Request Model
# ───────────────────────────────────────────────

class TokenRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: str = "student"  # used only for frontend UI logic
    battle_id: str = Field(..., min_length=1)


# ───────────────────────────────────────────────
# 🎟 Generate Stream Video Token
# ───────────────────────────────────────────────

@router.post("/stream/token")
def create_stream_token(payload: TokenRequest):

    print("\n🔥 ===== /stream/token HIT =====")
    print("🕒 Time:", datetime.now().isoformat())
    print("📥 Payload:", payload.dict())

    try:
        # ───────────────────────────────
        # Validate
        # ───────────────────────────────
        user_id = payload.user_id.strip()
        frontend_role = payload.role or "student"
        battle_id = payload.battle_id.strip()

        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required")

        if not battle_id:
            raise HTTPException(status_code=400, detail="battle_id is required")

        print("👤 User ID:", user_id)
        print("🎭 Frontend Role:", frontend_role)
        print("⚔️ Battle ID:", battle_id)

        # ───────────────────────────────
        # Generate Video Token (NO upsert needed)
        # ───────────────────────────────
        print("➡️ Generating Stream Video token...")

        expiration = int(
            (datetime.now(timezone.utc) + timedelta(hours=2)).timestamp()
        )

        token = video_client.create_token(
            user_id=user_id,
            exp=expiration,
        )

        print("✅ Token generated")
        print("⏳ Token expiry:", expiration)

        # ───────────────────────────────
        # Return Response
        # ───────────────────────────────
        response = {
            "token": token,
            "api_key": STREAM_API_KEY,
            "expires_at": expiration,
            "user": {
                "id": user_id,
                "role": frontend_role,
            }
        }

        print("📤 Sending response")
        print("🔥 ===== SUCCESS =====\n")

        return response

    except Exception as e:
        print("\n❌ STREAM TOKEN ERROR")
        traceback.print_exc()
        print("🔥 ===== FAILURE =====\n")
        raise HTTPException(status_code=500, detail=str(e))

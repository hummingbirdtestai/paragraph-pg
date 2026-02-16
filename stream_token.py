# stream_token.py

import os
import traceback
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from getstream import Stream
from getstream.models import UserRequest

router = APIRouter()

# ───────────────────────────────────────────────
# 🔐 Environment Config
# ───────────────────────────────────────────────

api_key = os.getenv("STREAM_API_KEY")
api_secret = os.getenv("STREAM_API_SECRET")

if not api_key or not api_secret:
    raise RuntimeError("❌ STREAM_API_KEY or STREAM_API_SECRET not configured")

print("✅ Stream ENV Loaded")
print("🔑 STREAM_API_KEY:", api_key)

client = Stream(
    api_key=api_key,
    api_secret=api_secret,
)

print("✅ Stream client initialized")


# ───────────────────────────────────────────────
# 📦 Request Model
# ───────────────────────────────────────────────

class TokenRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: str = "student"
    battle_id: str = Field(..., min_length=1)


# ───────────────────────────────────────────────
# 🎟 Generate Stream Token
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
        role = payload.role or "student"
        battle_id = payload.battle_id.strip()

        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required")

        if not battle_id:
            raise HTTPException(status_code=400, detail="battle_id is required")

        print("👤 User ID:", user_id)
        print("🎭 Role:", role)
        print("⚔️ Battle ID:", battle_id)

        # ───────────────────────────────
        # Upsert User
        # ───────────────────────────────
        print("➡️ Upserting user in Stream...")

        client.upsert_users(
            UserRequest(
                id=user_id,
                role=role,
                name=user_id,
            )
        )

        print("✅ User upserted successfully")

        # ───────────────────────────────
        # Create Token (1 hour expiry)
        # ───────────────────────────────
        print("➡️ Generating token...")

        expiration = int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
        )

        token = client.create_token(
            user_id=user_id,
            expiration=expiration
        )

        print("✅ Token generated")
        print("⏳ Token expiry:", expiration)

        # ───────────────────────────────
        # Return Response
        # ───────────────────────────────
        response = {
            "token": token,
            "api_key": api_key,
            "user": {
                "id": user_id,
                "role": role,
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

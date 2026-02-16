# stream_token.py

import os
import traceback
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from getstream import Stream
from getstream.models import UserRequest

router = APIRouter()

# ───────────────────────────────────────────────
# 🔐 Environment Config
# ───────────────────────────────────────────────
api_key = os.getenv("STREAM_API_KEY")
api_secret = os.getenv("STREAM_API_SECRET")

if not api_key or not api_secret:
    raise RuntimeError("STREAM_API_KEY or STREAM_API_SECRET not configured")

print("✅ Stream ENV Loaded")
print("API KEY:", api_key)

client = Stream(
    api_key=api_key,
    api_secret=api_secret,
)

print("✅ Stream client initialized")


# ───────────────────────────────────────────────
# 📦 Request Model
# ───────────────────────────────────────────────
class TokenRequest(BaseModel):
    user_id: str
    role: str = "student"
    battle_id: str


# ───────────────────────────────────────────────
# 🎟 Generate Stream Token
# ───────────────────────────────────────────────
@router.post("/stream/token")
def create_stream_token(payload: TokenRequest):

    print("🔥 /stream/token endpoint hit")
    print("Incoming payload:", payload.dict())

    if not payload.user_id.strip():
        raise HTTPException(status_code=400, detail="user_id is required")

    try:
        role = payload.role or "student"
        print("Using role:", role)

        # ────────────────
        # Upsert User
        # ────────────────
        print("➡️ Upserting user...")
        client.upsert_users(
            UserRequest(
                id=payload.user_id,
                role=role,
                name=payload.user_id,
            )
        )
        print("✅ User upserted")

        # ────────────────
        # Create Token
        # ────────────────
        print("➡️ Generating token...")
        token = client.create_token(payload.user_id, expiration=3600)
        print("✅ Token generated")

        return {
            "token": token,
            "api_key": api_key,
            "user": {
                "id": payload.user_id,
                "role": role,
            }
        }

    except Exception as e:
        print("❌ STREAM TOKEN ERROR")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# stream_token.py

import os
import traceback
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from stream_video import StreamVideo

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

video_client = StreamVideo(
    api_key=api_key,
    api_secret=api_secret,
)

print("✅ StreamVideo client initialized")

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
        print("❌ user_id missing")
        raise HTTPException(status_code=400, detail="user_id is required")

    try:
        role = payload.role or "student"
        print("Using role:", role)

        # ────────────────
        # Upsert User
        # ────────────────
        print("➡️ Upserting user...")
        video_client.upsert_users([
            {
                "id": payload.user_id,
                "role": role,
            }
        ])
        print("✅ User upserted")

        # ────────────────
        # Create Token
        # ────────────────
        print("➡️ Generating token...")
        token = video_client.create_token(payload.user_id)
        print("✅ Token generated")

        # ────────────────
        # Create / Get Call
        # ────────────────
        print("➡️ Creating / getting call...")
        call = video_client.call("audio_room", payload.battle_id)

        call.get_or_create(
            data={
                "created_by_id": payload.user_id,
                "custom": {
                    "battle_id": payload.battle_id,
                },
            }
        )
        print("✅ Call ready")

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

# stream_token.py

import os
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

video_client = StreamVideo(api_key=api_key, api_secret=api_secret)


# ───────────────────────────────────────────────
# 📦 Request Model
# ───────────────────────────────────────────────
class TokenRequest(BaseModel):
    user_id: str
    role: str = "listener"   # default role
    battle_id: str


# ───────────────────────────────────────────────
# 🎟 Generate Stream Token
# ───────────────────────────────────────────────
@router.post("/stream/token")
def create_stream_token(payload: TokenRequest):

    # Basic validation
    if not payload.user_id.strip():
        raise HTTPException(status_code=400, detail="user_id is required")

    if payload.role not in ["teacher", "speaker", "listener"]:
        raise HTTPException(status_code=400, detail="Invalid role")

    try:
        # 1️⃣ Create Stream user token
        token = video_client.create_token(payload.user_id)

        # 2️⃣ Optionally ensure call exists (safe for concurrency)
        call = video_client.call("audio_room", payload.battle_id)
        call.get_or_create(
            data={
                "created_by_id": payload.user_id,
                "custom": {
                    "battle_id": payload.battle_id,
                },
            }
        )

        return {
            "token": token,
            "api_key": api_key,
            "user": {
                "id": payload.user_id,
                "role": payload.role,
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

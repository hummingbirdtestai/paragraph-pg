# stream_token.py

import os
import traceback
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from getstream import Stream
from getstream.models import UserRequest, MemberRequest

router = APIRouter()

# ───────────────────────────────────────────────
# 🔐 Environment Config
# ───────────────────────────────────────────────

api_key = os.getenv("STREAM_API_KEY")
api_secret = os.getenv("STREAM_API_SECRET")

if not api_key or not api_secret:
    raise RuntimeError("❌ STREAM_API_KEY or STREAM_API_SECRET not configured")

client = Stream(
    api_key=api_key,
    api_secret=api_secret,
    timeout=3.0,
)

print("✅ Stream client initialized")


# ───────────────────────────────────────────────
# 📦 Request Model
# ───────────────────────────────────────────────

class TokenRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: str = "listener"   # teacher | speaker | listener
    battle_id: str = Field(..., min_length=1)


# ───────────────────────────────────────────────
# 🎟 Generate Stream Token + Ensure Call Exists
# ───────────────────────────────────────────────

@router.post("/stream/token")
def create_stream_token(payload: TokenRequest):

    try:
        user_id = payload.user_id.strip()
        frontend_role = payload.role or "listener"
        battle_id = payload.battle_id.strip()

        if not user_id:
            raise HTTPException(status_code=400, detail="user_id required")

        if not battle_id:
            raise HTTPException(status_code=400, detail="battle_id required")

        print(f"\n🔥 /stream/token | {user_id} | {frontend_role} | {battle_id}")

        # ───────────────────────────────
        # 1️⃣ Upsert User (Required)
        # ───────────────────────────────

        client.upsert_users(
            UserRequest(
                id=user_id,
                role="user",  # Stream internal role
                name=user_id,
                custom={
                    "frontend_role": frontend_role,
                    "battle_id": battle_id,
                },
            )
        )

        # ───────────────────────────────
        # 2️⃣ Ensure Audio Room Exists
        # ───────────────────────────────

        call = client.video.call("audio_room", battle_id)

        try:
            call.create(
                data={
                    "created_by_id": user_id,
                }
            )
            print("🎧 Audio room created")
        except Exception:
            # Call already exists (safe to ignore)
            pass

        # ───────────────────────────────
        # 3️⃣ Add Member To Call
        # ───────────────────────────────

        call.update(
            members=[
                MemberRequest(
                    user_id=user_id,
                    role="call_member",
                )
            ]
        )

        # ───────────────────────────────
        # 4️⃣ Generate Token
        # ───────────────────────────────

        expiration = int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
        )

        token = client.create_token(
            user_id=user_id,
            expiration=expiration
        )

        # ───────────────────────────────
        # 5️⃣ Response
        # ───────────────────────────────

        return {
            "token": token,
            "api_key": api_key,
            "user": {
                "id": user_id,
                "role": frontend_role,
            }
        }

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

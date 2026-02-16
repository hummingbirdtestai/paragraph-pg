# stream_token.py

import os
import traceback
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from getstream import Stream
from getstream.models import UserRequest, MemberRequest, CallRequest

router = APIRouter()

# ───────────────────────────────────────────────
# Environment Configuration
# ───────────────────────────────────────────────

api_key = os.getenv("STREAM_API_KEY")
api_secret = os.getenv("STREAM_API_SECRET")

if not api_key or not api_secret:
    raise RuntimeError("STREAM_API_KEY or STREAM_API_SECRET not configured")

client = Stream(
    api_key=api_key,
    api_secret=api_secret,
    timeout=5.0,  # slightly safer timeout
)

# ───────────────────────────────────────────────
# Request Model
# ───────────────────────────────────────────────

class TokenRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: str = "listener"
    battle_id: str = Field(..., min_length=1)

ALLOWED_ROLES = {"teacher", "speaker", "listener"}

# ───────────────────────────────────────────────
# Token Endpoint
# ───────────────────────────────────────────────

@router.post("/stream/token")
def create_stream_token(payload: TokenRequest):
    try:
        user_id = payload.user_id.strip()
        frontend_role = payload.role.strip().lower()
        battle_id = payload.battle_id.strip()

        if not user_id:
            raise HTTPException(status_code=400, detail="user_id required")

        if not battle_id:
            raise HTTPException(status_code=400, detail="battle_id required")

        if frontend_role not in ALLOWED_ROLES:
            frontend_role = "listener"

        # 1️⃣ Ensure user exists in Stream
        client.upsert_users(
            UserRequest(
                id=user_id,
                role="user",  # application-level role
                name=user_id,
                custom={
                    "frontend_role": frontend_role,
                    "battle_id": battle_id,
                },
            )
        )

        # 2️⃣ Ensure call exists (idempotent — safe for all users)
        call = client.video.call("audio_room", battle_id)
        call.get_or_create(
            data=CallRequest(
                created_by_id=user_id,
            )
        )

        # 3️⃣ Map frontend role → valid Stream call role
        if frontend_role == "teacher":
            call_role = "admin"
        elif frontend_role == "speaker":
            call_role = "moderator"
        else:
            call_role = "user"   # ✅ FIXED (was "call-member")

        # 4️⃣ Assign call-level role (idempotent)
        call.update_call_members(
            update_members=[
                MemberRequest(
                    user_id=user_id,
                    role=call_role,
                )
            ]
        )

        # 5️⃣ Generate token (1 hour validity)
        token = client.create_token(
            user_id=user_id,
            expiration=60 * 60
        )

        return {
            "token": token,
            "api_key": api_key,  # safe to expose (NOT the secret)
            "user": {
                "id": user_id,
                "role": frontend_role,
            }
        }

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Stream token generation failed"
        )

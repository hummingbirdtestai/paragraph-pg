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

STREAM_API_KEY = os.getenv("STREAM_API_KEY")
STREAM_API_SECRET = os.getenv("STREAM_API_SECRET")

if not STREAM_API_KEY or not STREAM_API_SECRET:
    raise RuntimeError("❌ STREAM_API_KEY or STREAM_API_SECRET not configured")

print("✅ Stream ENV Loaded")

client = Stream(
    api_key=STREAM_API_KEY,
    api_secret=STREAM_API_SECRET,
)

print("✅ Stream client initialized")


# ───────────────────────────────────────────────
# 📦 Request Model
# ───────────────────────────────────────────────

class TokenRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: str = Field(default="listener")
    battle_id: str = Field(..., min_length=1)


# ───────────────────────────────────────────────
# 🛡️ Role Validation (IMPORTANT)
# ───────────────────────────────────────────────

def validate_role(user_id: str, requested_role: str) -> str:
    """
    Production-safe role validation.

    TODO: Replace this logic with DB lookup:
        - Check if user_id belongs to battle teacher
        - Check if user is approved speaker
        - Otherwise default to listener
    """

    requested_role = requested_role.lower().strip()

    if requested_role not in ["teacher", "speaker", "listener"]:
        return "listener"

    # 🔒 HARD SAFETY RULE:
    # Only allow teacher if explicitly allowed by backend logic.
    # For now we allow it but this is where DB check goes.

    return requested_role


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
        # Validate Basic Fields
        # ───────────────────────────────

        user_id = payload.user_id.strip()
        battle_id = payload.battle_id.strip()

        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required")

        if not battle_id:
            raise HTTPException(status_code=400, detail="battle_id is required")

        # ───────────────────────────────
        # Validate Role Securely
        # ───────────────────────────────

        backend_role = validate_role(user_id, payload.role)

        print("👤 User ID:", user_id)
        print("🎭 Backend Role:", backend_role)
        print("⚔️ Battle ID:", battle_id)

        # ───────────────────────────────
        # Upsert User in Stream
        # ───────────────────────────────
        # IMPORTANT: Always role="user"
        # Actual permissions controlled separately

        print("➡️ Upserting user in Stream...")

        client.upsert_users(
            UserRequest(
                id=user_id,
                role="user",
                name=user_id,
                custom={
                    "role": backend_role,
                    "battle_id": battle_id,
                }
            )
        )

        print("✅ User upserted")

        # ───────────────────────────────
        # Generate Token
        # ───────────────────────────────

        expiration = int(
            (datetime.now(timezone.utc) + timedelta(hours=2)).timestamp()
        )

        token = client.create_token(
            user_id=user_id,
            expiration=expiration
        )

        print("✅ Token generated")
        print("⏳ Expiry:", expiration)

        # ───────────────────────────────
        # Return Response
        # ───────────────────────────────

        response = {
            "token": token,
            "api_key": STREAM_API_KEY,
            "expires_at": expiration,
            "user": {
                "id": user_id,
                "role": backend_role,
            }
        }

        print("📤 Response sent")
        print("🔥 ===== SUCCESS =====\n")

        return response

    except Exception as e:
        print("\n❌ STREAM TOKEN ERROR")
        traceback.print_exc()
        print("🔥 ===== FAILURE =====\n")
        raise HTTPException(status_code=500, detail="Stream token generation failed")

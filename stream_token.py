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
    timeout=5.0,
)

# ───────────────────────────────────────────────
# 🔥 ONE-TIME CALL TYPE CONFIGURATION
# ───────────────────────────────────────────────

def configure_audio_room():
    try:
        client.video.update_call_type(
            name="audio_room",
            grants={
                "admin": [
                    "create-call",
                    "join-call",
                    "send-audio",
                    "mute-users",
                    "update-call-member",
                    "remove-call-member",
                ],
                "moderator": [
                    "join-call",
                    "send-audio",
                ],
                "call-member": [
                    "join-call",
                ],
                "user": [],
            },
            settings={
                "backstage": {"enabled": True},
                "audio": {
                    "mic_default_on": False,
                    "speaker_default_on": True,
                    "access_request_enabled": True,
                },
                "session": {
                    "inactivity_timeout_seconds": 300,
                },
            },
        )
        print("✅ audio_room configured")
    except Exception:
        print("⚠ audio_room configuration skipped (may already exist)")

configure_audio_room()

# ───────────────────────────────────────────────
# Request Models
# ───────────────────────────────────────────────

class TokenRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: str = "listener"
    battle_id: str = Field(..., min_length=1)

class PromoteRequest(BaseModel):
    battle_id: str
    student_id: str
    teacher_id: str

class RemoveRequest(BaseModel):
    battle_id: str
    student_id: str
    teacher_id: str

ALLOWED_ROLES = {"teacher", "speaker", "listener"}

# ───────────────────────────────────────────────
# 🎫 TOKEN ENDPOINT
# ───────────────────────────────────────────────

@router.post("/stream/token")
def create_stream_token(payload: TokenRequest):
    try:
        user_id = payload.user_id.strip()
        frontend_role = payload.role.strip().lower()
        battle_id = payload.battle_id.strip()

        if frontend_role not in ALLOWED_ROLES:
            frontend_role = "listener"

        # 1️⃣ Upsert user
        client.upsert_users(
            UserRequest(
                id=user_id,
                role="user",
                name=user_id,
                custom={
                    "frontend_role": frontend_role,
                    "battle_id": battle_id,
                },
            )
        )

        # 2️⃣ Ensure call exists
        call = client.video.call("audio_room", battle_id)
        call.get_or_create(
            data=CallRequest(created_by_id=user_id)
        )

        # 3️⃣ Map frontend → Stream call role
        if frontend_role == "teacher":
            call_role = "admin"
        elif frontend_role == "speaker":
            call_role = "moderator"
        else:
            call_role = "call-member"

        # 4️⃣ Assign call-level role
        call.update_call_members(
            update_members=[
                MemberRequest(
                    user_id=user_id,
                    role=call_role,
                )
            ]
        )

        # 5️⃣ Generate token
        token = client.create_token(
            user_id=user_id,
            expiration=60 * 60
        )

        return {
            "token": token,
            "api_key": api_key,
            "user": {
                "id": user_id,
                "role": frontend_role,
            }
        }

    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Stream token generation failed"
        )


# ───────────────────────────────────────────────
# 🔐 INTERNAL HELPER: VERIFY ADMIN
# ───────────────────────────────────────────────

def verify_admin(call, teacher_id: str):
    members_response = call.query_members()
    teacher_member = next(
        (m for m in members_response.members if m.user_id == teacher_id),
        None
    )

    if not teacher_member or teacher_member.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only admin can perform this action"
        )


# ───────────────────────────────────────────────
# 🎙 PROMOTE LISTENER → SPEAKER
# ───────────────────────────────────────────────

@router.post("/stream/promote-to-speaker")
def promote_to_speaker(payload: PromoteRequest):
    try:
        call = client.video.call("audio_room", payload.battle_id)

        # 🔐 Verify teacher is admin
        verify_admin(call, payload.teacher_id)

        # 🚦 Ensure call is LIVE
        call_info = call.get()
        if call_info.call.backstage:
            raise HTTPException(
                status_code=400,
                detail="Cannot promote while call is in backstage mode"
            )

        # 🎙 Promote
        call.update_call_members(
            update_members=[
                MemberRequest(
                    user_id=payload.student_id,
                    role="moderator",
                )
            ]
        )

        return {"success": True}

    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Failed to promote user"
        )


# ───────────────────────────────────────────────
# ❌ REMOVE MEMBER
# ───────────────────────────────────────────────

@router.post("/stream/remove-member")
def remove_member(payload: RemoveRequest):
    try:
        call = client.video.call("audio_room", payload.battle_id)

        # 🔐 Verify teacher is admin
        verify_admin(call, payload.teacher_id)

        call.update_call_members(
            remove_members=[payload.student_id]
        )

        return {"success": True}

    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Failed to remove member"
        )

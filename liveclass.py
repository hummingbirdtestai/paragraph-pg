# -----------------------------------------------------
# LIVE CLASS ENGINE (FINAL PRODUCTION VERSION)
# -----------------------------------------------------

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
from dotenv import load_dotenv

import os
import asyncio
import logging
import jwt
import time
import requests
from datetime import datetime
import pytz

# -----------------------------------------------------
# Setup
# -----------------------------------------------------

load_dotenv()

app = FastAPI(title="Unified Live Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("live_engine")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

ist = pytz.timezone("Asia/Kolkata")

active_sessions = set()

# -----------------------------------------------------
# SESSION RUNNING CHECK
# -----------------------------------------------------

def is_session_running(battle_id):

    resp = supabase.table("live_class_state") \
        .select("is_running") \
        .eq("battle_id", battle_id) \
        .limit(1) \
        .execute()

    if not resp.data:
        return False

    return resp.data[0]["is_running"]

# -----------------------------------------------------
# Realtime JWT
# -----------------------------------------------------

def get_realtime_jwt():

    decoded = jwt.decode(SUPABASE_SERVICE_KEY, options={"verify_signature": False})
    project_ref = decoded.get("ref")

    payload = {
        "aud": "realtime",
        "role": "service_role",
        "iss": f"https://{project_ref}.supabase.co",
        "exp": int(time.time()) + 60,
    }

    return jwt.encode(payload, SUPABASE_JWT_SECRET, algorithm="HS256")

# -----------------------------------------------------
# Broadcast
# -----------------------------------------------------

def broadcast_event(battle_id, event, payload):

    try:

        logger.info(f"BROADCAST EVENT {event} for {battle_id}")

        realtime_url = f"{SUPABASE_URL}/realtime/v1/api/broadcast"

        body = {
            "messages": [
                {
                    "topic": f"battle:{battle_id}",
                    "event": "broadcast",
                    "payload": {
                        "type": event,
                        "data": payload,
                    },
                }
            ]
        }

        jwt_token = get_realtime_jwt()

        requests.post(
            realtime_url,
            headers={
                "apikey": SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {jwt_token}",
                "Content-Type": "application/json",
                "x-project-ref": SUPABASE_URL.split("//")[1].split(".")[0],
            },
            json=body,
            timeout=5
        )

    except Exception as e:
        logger.error(f"Broadcast failed: {e}")

# -----------------------------------------------------
# Update state
# -----------------------------------------------------

def update_state(battle_id, phase, seq=None, payload=None, stats=None, leaderboard=None, time_left=0):

    update = {
        "phase": phase,
        "time_left": time_left,
        "updated_at": datetime.now(ist).isoformat(),
    }

    if seq is not None:
        update["seq"] = seq

    if payload is not None:
        update["payload"] = payload

    if stats is not None:
        update["stats_payload"] = stats

    if leaderboard is not None:
        update["leaderboard_payload"] = leaderboard

    supabase.table("live_class_state").update(update).eq("battle_id", battle_id).execute()

# -----------------------------------------------------
# Pause guard
# -----------------------------------------------------

async def wait_if_paused(battle_id):

    while True:

        resp = supabase.table("live_class_state") \
            .select("is_paused") \
            .eq("battle_id", battle_id) \
            .limit(1) \
            .execute()

        state = resp.data[0] if resp.data else None

        if state and not state["is_paused"]:
            break

        await asyncio.sleep(1)

# -----------------------------------------------------
# Countdown
# -----------------------------------------------------

async def countdown(battle_id, phase, seconds, seq=None, payload=None):

    logger.info(f"COUNTDOWN START {battle_id} {phase}")

    for t in range(seconds, 0, -1):

        if not is_session_running(battle_id):
            logger.info(f"SESSION STOPPED {battle_id}")
            return "STOPPED"

        await wait_if_paused(battle_id)

        update_state(battle_id, phase, seq, payload, time_left=t)

        broadcast_event(
            battle_id,
            "timer",
            {"phase": phase, "time_left": t}
        )

        await asyncio.sleep(1)

    return "OK"

# -----------------------------------------------------
# SAFE RESULT HANDLER
# -----------------------------------------------------

async def handle_mcq_results(battle_id, seq, mcq):

    payload = None

    try:

        result = supabase.rpc(
            "finalize_live_class_mcq_and_get_resultsv5",
            {"p_battle_id": battle_id, "p_seq": seq}
        ).execute()

        payload = result.data

    except Exception as e:
        logger.warning(f"RPC FAILED seq={seq} {e}")

    if payload:

        stats = payload.get("distribution", {})
        leaderboard = payload.get("leaderboard", [])

        update_state(
            battle_id,
            "mcq_result",
            stats=stats,
            leaderboard=leaderboard
        )

        broadcast_event(battle_id, "mcq_result", payload)

        res = await countdown(battle_id, "mcq_result", 10)

        if res == "STOPPED":
            return "STOPPED"

    else:

        explanation_payload = {
            "correct_answer": mcq.get("correct_answer"),
            "learning_gap": mcq.get("learning_gap"),
            "high_yield_facts": mcq.get("high_yield_facts"),
            "image_description": mcq.get("image_description"),
            "image_url": mcq.get("image_url")
        }

        update_state(
            battle_id,
            "mcq_explanation",
            seq=seq,
            payload=explanation_payload
        )

        broadcast_event(battle_id, "mcq_explanation", explanation_payload)

        res = await countdown(battle_id, "mcq_explanation", 30)

        if res == "STOPPED":
            return "STOPPED"

    return "OK"

# -----------------------------------------------------
# Start session
# -----------------------------------------------------

@app.post("/session/start/{battle_id}")
async def start_session(battle_id: str, background_tasks: BackgroundTasks):

    if battle_id in active_sessions:
        return {"status": "already_running"}

    supabase.table("live_class_state").upsert({
        "battle_id": battle_id,
        "phase": "lobby",
        "is_running": True,
        "is_paused": False,
        "time_left": 0,
        "started_at": datetime.now(ist).isoformat(),
    }).execute()

    active_sessions.add(battle_id)

    broadcast_event(battle_id, "battle_start", {})

    background_tasks.add_task(run_live_class_engine, battle_id)

    return {"status": "started"}

# -----------------------------------------------------
# Pause
# -----------------------------------------------------

@app.post("/session/pause/{battle_id}")
async def pause_session(battle_id: str):

    supabase.table("live_class_state").update({
        "is_paused": True
    }).eq("battle_id", battle_id).execute()

    state_resp = supabase.table("live_class_state") \
        .select("*") \
        .eq("battle_id", battle_id) \
        .limit(1) \
        .execute()

    state = state_resp.data[0] if state_resp.data else {}

    broadcast_event(
        battle_id,
        "paused",
        {
            "phase": state.get("phase"),
            "seq": state.get("seq"),
            "payload": state.get("payload"),
            "time_left": state.get("time_left")
        }
    )

    return {"status": "paused"}

# -----------------------------------------------------
# Resume
# -----------------------------------------------------

@app.post("/session/resume/{battle_id}")
async def resume_session(battle_id: str):

    supabase.table("live_class_state").update({
        "is_paused": False
    }).eq("battle_id", battle_id).execute()

    state_resp = supabase.table("live_class_state") \
        .select("*") \
        .eq("battle_id", battle_id) \
        .limit(1) \
        .execute()

    state = state_resp.data[0] if state_resp.data else {}

    broadcast_event(
        battle_id,
        "resumed",
        {
            "phase": state.get("phase"),
            "seq": state.get("seq"),
            "payload": state.get("payload"),
            "time_left": state.get("time_left")
        }
    )

    return {"status": "resumed"}

# -----------------------------------------------------
# Stop session
# -----------------------------------------------------

@app.post("/session/stop/{battle_id}")
async def stop_session(battle_id: str):

    supabase.table("live_class_state").update({
        "is_running": False,
        "is_paused": False
    }).eq("battle_id", battle_id).execute()

    active_sessions.discard(battle_id)

    broadcast_event(battle_id, "battle_end", {})

    return {"status": "stopped"}

# -----------------------------------------------------
# Stop all sessions
# -----------------------------------------------------

@app.post("/session/stop-all")
async def stop_all_sessions():

    for battle_id in list(active_sessions):

        supabase.table("live_class_state").update({
            "is_running": False,
            "is_paused": False
        }).eq("battle_id", battle_id).execute()

        broadcast_event(battle_id, "battle_end", {})

    active_sessions.clear()

    return {"status": "all_sessions_stopped"}

# -----------------------------------------------------
# Fetch state
# -----------------------------------------------------

@app.get("/session/state/{battle_id}")
async def get_state(battle_id: str):

    resp = supabase.table("live_class_state") \
        .select("*") \
        .eq("battle_id", battle_id) \
        .limit(1) \
        .execute()

    if not resp.data:
        raise HTTPException(status_code=404, detail="No session state")

    return resp.data[0]

# -----------------------------------------------------
# LIVE CLASS ENGINE
# -----------------------------------------------------

async def run_live_class_engine(battle_id):

    try:

        logger.info(f"ENGINE BOOT {battle_id}")

        row_resp = supabase.table("live_class_schedule") \
            .select("*") \
            .eq("battle_id", battle_id) \
            .limit(1) \
            .execute()

        if not row_resp.data:
            logger.error("SCHEDULE NOT FOUND")
            return

        row = row_resp.data[0]

        session_type = row.get("type")

        if session_type == "mock":

            questions = row["topics_per_day"]

            for i, mcq in enumerate(questions, start=1):

                if not is_session_running(battle_id):
                    return

                update_state(battle_id, "mcq", i, payload=mcq)

                broadcast_event(battle_id, "mcq", mcq)

                res = await countdown(battle_id, "mcq", 30, i, mcq)

                if res == "STOPPED":
                    return

                res = await handle_mcq_results(battle_id, i, mcq)

                if res == "STOPPED":
                    return

            broadcast_event(battle_id, "battle_end", {})
            return

    except Exception as e:

        logger.error(f"ENGINE CRASHED {battle_id}: {e}")

    finally:

        active_sessions.discard(battle_id)

        supabase.table("live_class_state").update({
            "is_running": False
        }).eq("battle_id", battle_id).execute()

        logger.info(f"LIVE CLASS COMPLETED {battle_id}")

# -----------------------------------------------------
# BATTLE.PY
# -----------------------------------------------------
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

import os, asyncio, logging, requests, time, jwt
from datetime import datetime
import pytz

# -----------------------------------------------------
# 🔧 Setup
# -----------------------------------------------------
load_dotenv()
app = FastAPI(title="Battle API (Production AutoStart + State Sync)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("battle_api")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
active_battles = set()

# -----------------------------------------------------
# ⏱️ Scheduler Setup (IST)
# -----------------------------------------------------
ist = pytz.timezone("Asia/Kolkata")
scheduler = BackgroundScheduler(timezone=ist)
scheduler.start()

# -----------------------------------------------------
# 🔹 Realtime JWT Helper
# -----------------------------------------------------
def get_realtime_jwt():
    try:
        decoded = jwt.decode(SUPABASE_SERVICE_KEY, options={"verify_signature": False})
        project_ref = decoded.get("ref")
        payload = {
            "aud": "realtime",
            "role": "service_role",
            "iss": f"https://{project_ref}.supabase.co",
            "exp": int(time.time()) + 60,
        }
        return jwt.encode(payload, SUPABASE_JWT_SECRET, algorithm="HS256")
    except:
        return SUPABASE_SERVICE_KEY

# -----------------------------------------------------
# 🔹 Realtime Broadcast
# -----------------------------------------------------
def broadcast_event(battle_id: str, event: str, payload: dict):
    try:
        body = {
            "messages": [
                {
                    "topic": f"battle:{battle_id}",
                    "event": "broadcast",
                    "payload": {"type": event, "data": payload},
                }
            ]
        }

        realtime_url = f"{SUPABASE_URL}/realtime/v1/api/broadcast"
        realtime_jwt = get_realtime_jwt()

        res = requests.post(
            realtime_url,
            headers={
                "apikey": SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {realtime_jwt}",
                "Content-Type": "application/json",
                "x-project-ref": SUPABASE_URL.split("//")[1].split(".")[0],
            },
            json=body,
            timeout=5,
        )

        ok = res.status_code in (200, 202)
        if ok:
            logger.info(f"📡 Broadcasted [{event}] → battle:{battle_id}")
        else:
            logger.warning(f"⚠️ Broadcast Failed {res.status_code} → {res.text}")
        return ok

    except Exception as e:
        logger.error(f"💥 Broadcast Error ({event}): {e}")
        return False

# -----------------------------------------------------
# 🔹 Health Check
# -----------------------------------------------------
@app.get("/")
async def root():
    return {"status": "Battle API running (AutoStart + State Sync) 🚀"}

# -----------------------------------------------------
# 🔹 Fetch Battle State
# -----------------------------------------------------
@app.get("/battle/state/{battle_id}")
async def get_battle_state(battle_id: str):
    resp = supabase.table("battle_state").select("*").eq("battle_id", battle_id).single().execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="No state found for this battle")
    return resp.data

# -----------------------------------------------------
# ❌ Manual Start Disabled
# -----------------------------------------------------
@app.post("/battle/start/{battle_id}")
async def start_battle(battle_id: str):
    return {
        "success": False,
        "message": "Manual start disabled. Battle starts automatically."
    }

# -----------------------------------------------------
# 🤖 Auto-Start (Internal)
# -----------------------------------------------------
@app.post("/battle/auto_start/{battle_id}")
async def auto_start_battle(battle_id: str, background_tasks: BackgroundTasks):
    logger.info(f"🤖 Auto-start triggered → {battle_id}")

    supabase.table("battle_schedule").update({"status": "Active"}).eq("battle_id", battle_id).execute()

    active_battles.add(battle_id)
    background_tasks.add_task(run_battle_sequence, battle_id)

    broadcast_event(battle_id, "battle_start", {"message": "🤖 Auto Battle Started"})
    return {"success": True}

# -----------------------------------------------------
# 🔍 Minute-wise AutoStart Checker (FIXED)
# -----------------------------------------------------
def minute_check_auto_starter():
    now = datetime.now(ist)
    today = now.date().isoformat()
    time_str = now.strftime("%H:%M:00")

    logger.info(f"⏱️ Checking for battles at {time_str}")

    resp = supabase.table("battle_schedule") \
        .select("battle_id,status") \
        .eq("scheduled_date", today) \
        .eq("scheduled_time", time_str) \
        .execute()

    rows = resp.data or []

    if len(rows) == 0:
        logger.info("⛔ No battle scheduled at this time")
        return

    if len(rows) > 1:
        logger.error("🚨 Multiple battles scheduled at same time! Check DB.")
        return

    row = rows[0]
    battle_id = row["battle_id"]
    status = row["status"]

    if status.lower() == "upcoming":
        logger.info(f"🤖 Auto-starting battle → {battle_id}")
        try:
            requests.post(f"http://localhost:8003/battle/auto_start/{battle_id}")
        except Exception as e:
            logger.error(f"⚠️ Auto-start trigger failed: {e}")

scheduler.add_job(minute_check_auto_starter, CronTrigger(second="0"))

# -----------------------------------------------------
# 🔥 Update Battle State Helper
# -----------------------------------------------------
def update_battle_state(
    battle_id: str,
    phase: str,
    question=None,
    stats=None,
    leaderboard=None,
    time_left=0,
    index=None
):
    payload = {
        "battle_id": battle_id,
        "phase": phase,
        "time_left": time_left,
        "updated_at": datetime.now(ist).isoformat(),
    }

    if index is not None:
        payload["current_question_index"] = index
    if question is not None:
        payload["question_payload"] = question
    if stats is not None:
        payload["stats_payload"] = stats
    if leaderboard is not None:
        payload["leaderboard_payload"] = leaderboard

    # 🔍 ADD THIS LOG — EXACT PLACE
    logger.info(
        f"🧠 BATTLE_STATE WRITE → {battle_id} | "
        f"phase={phase} | "
        f"Q={'Y' if question is not None else '—'} | "
        f"S={'Y' if stats is not None else '—'} | "
        f"L={'Y' if leaderboard is not None else '—'} | "
        f"time_left={time_left}"
    )

    supabase.table("battle_state").upsert(payload).execute()

# -----------------------------------------------------
# 🔹 Battle Review Endpoint (ADDED)
# -----------------------------------------------------
@app.post("/battle/review")
async def get_battle_review(data: dict):

    title = data.get("title")
    date = data.get("scheduled_date")
    student_id = data.get("student_id")

    if not (title and date and student_id):
        raise HTTPException(
            status_code=400,
            detail="Missing title, scheduled_date, or student_id"
        )

    try:
        resp = supabase.rpc(
            "get_battle_mcqs_with_attempts",
            {
                "title_input": title,
                "date_input": date,
                "student_id_input": student_id,
            },
        ).execute()

        if not resp.data:
            raise HTTPException(status_code=404, detail="No MCQs found for this battle")

        return {"success": True, "mcqs": resp.data}

    except Exception as e:
        logger.error(f"💥 get_battle_review failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------
# 🔹 Main Orchestrator (unchanged)
# -----------------------------------------------------
async def run_battle_sequence(battle_id: str):
    logger.info(f"🏁 Orchestrator started → {battle_id}")

    try:
        current = supabase.rpc("get_first_mcq", {"battle_id_input": battle_id}).execute()

        if not current.data:
            broadcast_event(battle_id, "battle_end", {"message": "No MCQs found"})
            return

        while current.data:
            mcq = current.data[0]
            react_order = mcq.get("react_order", 0)
            mcq_id = mcq["mcq_id"]

            broadcast_event(battle_id, "new_question", mcq)
            update_battle_state(battle_id, "question", question=mcq, index=react_order, time_left=20)

            for r in range(20, 0, -1):
                update_battle_state(battle_id, "question", question=mcq, time_left=r, index=react_order)
                await asyncio.sleep(1)

            bar = supabase.rpc("get_battle_stats", {"mcq_id_input": mcq_id}).execute().data or []
            bar_payload = bar[0] if bar else {}
            broadcast_event(battle_id, "show_stats", bar_payload)
            update_battle_state(battle_id, "stats", stats=bar_payload, time_left=10)

            for r in range(10, 0, -1):
                update_battle_state(battle_id, "stats", stats=bar_payload, time_left=r)
                await asyncio.sleep(1)

            lead = supabase.rpc(
                "get_leader_board",
                {"battle_id_input": battle_id, "mcq_id_input": mcq_id}
            ).execute().data or []
            lead_payload = lead
            broadcast_event(battle_id, "update_leaderboard", lead_payload)
            update_battle_state(battle_id, "leaderboard", leaderboard=lead_payload, time_left=10)

            for r in range(10, 0, -1):
                update_battle_state(battle_id, "leaderboard", leaderboard=lead_payload, time_left=r)
                await asyncio.sleep(1)

            next_q = supabase.rpc(
                "get_next_mcq",
                {"battle_id_input": battle_id, "react_order_input": react_order}
            ).execute()

            if next_q.data:
                current = next_q
                continue

            supabase.table("battle_schedule").update({"status": "Completed"}).eq("battle_id", battle_id).execute()
            update_battle_state(battle_id, "ended", time_left=0)
            broadcast_event(battle_id, "battle_end", {"message": "🏁 Battle Completed"})
            break

    except Exception as e:
        logger.error(f"💥 Orchestrator error ({battle_id}): {e}")

    finally:
        active_battles.discard(battle_id)
        logger.info(f"🧹 Orchestrator stopped → {battle_id}")

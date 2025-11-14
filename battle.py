from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from dotenv import load_dotenv
import os, asyncio, logging, requests, time, jwt, json

# -----------------------------------------------------
# 🔧 Setup
# -----------------------------------------------------
load_dotenv()
app = FastAPI(title="Battle API")

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
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

if not SUPABASE_SERVICE_KEY:
    logger.error("🚨 SUPABASE_SERVICE_ROLE_KEY not found in environment!")
else:
    logger.info(f"🔑 Loaded Supabase key length: {len(SUPABASE_SERVICE_KEY)}")
    try:
        decoded = jwt.decode(SUPABASE_SERVICE_KEY, options={"verify_signature": False})
        logger.info(f"🧩 Key decoded → role={decoded.get('role')}, ref={decoded.get('ref')}")
    except Exception as e:
        logger.error(f"❌ Failed to decode Supabase key: {e}")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
active_battles = set()

# -----------------------------------------------------
# 🔹 Helper: Generate Realtime JWT (aud = realtime)
# -----------------------------------------------------
def get_realtime_jwt():
    """Generate short-lived JWT accepted by Supabase Realtime REST API."""
    try:
        decoded = jwt.decode(SUPABASE_SERVICE_KEY, options={"verify_signature": False})
        project_ref = decoded.get("ref")
        payload = {
            "aud": "realtime",
            "role": "service_role",
            "iss": f"https://{project_ref}.supabase.co",
            "exp": int(time.time()) + 60,
        }

        signing_key = SUPABASE_JWT_SECRET
        token = jwt.encode(payload, signing_key, algorithm="HS256")
        return token
    except Exception as e:
        logger.error(f"❌ Failed to create realtime JWT: {e}")
        return SUPABASE_SERVICE_KEY

# -----------------------------------------------------
# 🔹 Broadcast Helper
# -----------------------------------------------------
def broadcast_event(battle_id: str, event: str, payload: dict):
    """Send broadcast event to Supabase Realtime channel."""
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
                "x-client-info": "supabase-py-broadcast",
            },
            json=body,
            timeout=5,
        )

        if res.status_code not in (200, 202):
            logger.warning(f"❌ Broadcast failed ({res.status_code}) → {res.text}")
        else:
            logger.info(f"✅ Broadcasted {event} to battle:{battle_id}")
        return res.ok

    except Exception as e:
        logger.error(f"💥 Broadcast failed ({event}): {e}")
        return False

# -----------------------------------------------------
# 🔹 Root Endpoint
# -----------------------------------------------------
@app.get("/")
async def root():
    logger.info("🌐 Health check hit: /")
    return {"status": "Battle API running ✅"}

# -----------------------------------------------------
# 🔹 Utility Endpoints
# -----------------------------------------------------
@app.post("/battle/get_stats")
async def get_battle_stats(mcq_id: str):
    logger.info(f"📊 get_battle_stats called with mcq_id={mcq_id}")
    try:
        resp = supabase.rpc("get_battle_stats", {"mcq_id_input": mcq_id}).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail="No stats found")
        return {"success": True, "data": resp.data}
    except Exception as e:
        logger.error(f"💥 get_battle_stats failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/battle/leaderboard")
async def get_leaderboard(battle_id: str):
    logger.info(f"🏆 get_leaderboard called with battle_id={battle_id}")
    try:
        resp = supabase.rpc("get_leader_board", {"battle_id_input": battle_id}).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail="No leaderboard found")
        return {"success": True, "data": resp.data}
    except Exception as e:
        logger.error(f"💥 get_leaderboard failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------
# 🔹 Battle Start Endpoint
# -----------------------------------------------------
@app.post("/battle/start/{battle_id}")
async def start_battle(battle_id: str, background_tasks: BackgroundTasks):
    logger.info(f"🚀 /battle/start called for battle_id={battle_id}")
    try:
        participants_resp = (
            supabase.table("battle_participants")
            .select("id,user_id,username,status")
            .eq("battle_id", battle_id)
            .eq("status", "joined")
            .execute()
        )
        participants = participants_resp.data or []

        status_resp = (
            supabase.table("battle_schedule")
            .select("status")
            .eq("battle_id", battle_id)
            .single()
            .execute()
        )
        current_status = status_resp.data.get("status") if status_resp.data else None

        if current_status and current_status.lower() == "active" and battle_id in active_battles:
            broadcast_event(battle_id, "battle_resume", {"message": "Joined ongoing battle"})
            return {"success": True, "message": "Already active — joined ongoing battle"}

        if current_status and current_status.lower() == "active" and battle_id not in active_battles:
            active_battles.add(battle_id)
            background_tasks.add_task(run_battle_sequence, battle_id)
            broadcast_event(battle_id, "battle_resume", {"message": "Resumed orchestrator"})
            return {"success": True, "message": "Battle resumed"}

        if current_status and current_status.lower() == "completed":
            return {"success": False, "message": "Battle already finished"}

        supabase.table("battle_schedule").update({"status": "Active"}).eq("battle_id", battle_id).execute()
        active_battles.add(battle_id)
        broadcast_event(battle_id, "battle_start_pending", {"message": "⚔️ Starting soon"})

        await asyncio.sleep(5)
        broadcast_event(battle_id, "battle_start", {"message": "🚀 Battle started"})
        background_tasks.add_task(run_battle_sequence, battle_id)
        return {"success": True, "message": "Battle starting after buffer"}

    except Exception as e:
        logger.error(f"💥 start_battle failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------
# 🔹 Battle Review Endpoint (NEW)
# -----------------------------------------------------
@app.post("/battle/review")
async def get_battle_review(data: dict):
    """
    Expected JSON body:
    {
      "title": "Patho Premier League 🔬🏆",
      "scheduled_date": "2025-11-12",
      "student_id": "uuid-of-student"
    }
    """
    title = data.get("title")
    date = data.get("scheduled_date")
    student_id = data.get("student_id")

    if not (title and date and student_id):
        raise HTTPException(status_code=400, detail="Missing title, date, or student_id")

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
# 🔹 Main Orchestrator Loop
# -----------------------------------------------------
async def run_battle_sequence(battle_id: str):
    """start_orchestra → +20s get_bar_graph → +10s get_leader_board → +10s get_next_mcq → repeat"""
    logger.info(f"🏁 Orchestrator started for battle_id={battle_id}")
    try:
        current = supabase.rpc("get_first_mcq", {"battle_id_input": battle_id}).execute()
        if not current.data:
            broadcast_event(battle_id, "battle_end", {"message": "No MCQs found"})
            return

        while current.data:
            mcq = current.data[0]
            react_order = mcq.get("react_order", 0)
            total_mcqs = mcq.get("total_mcqs", 0)
            mcq_id = mcq["mcq_id"]

            broadcast_event(battle_id, "new_question", mcq)
            await asyncio.sleep(20)

            bar = supabase.rpc("get_battle_stats", {"mcq_id_input": mcq_id}).execute().data or []
            payload_bar = bar[0] if isinstance(bar, list) and bar else {}
            broadcast_event(battle_id, "show_stats", payload_bar)

            await asyncio.sleep(10)
            lead = supabase.rpc("get_leader_board", {"battle_id_input": battle_id}).execute().data or []
            payload_lead = lead[0] if isinstance(lead, list) and lead else {}
            broadcast_event(battle_id, "update_leaderboard", payload_lead)

            await asyncio.sleep(10)
            next_q = supabase.rpc("get_next_mcq", {"battle_id_input": battle_id, "react_order_input": react_order}).execute()

            if next_q.data:
                current = next_q
                continue

            supabase.table("battle_schedule").update({"status": "Completed"}).eq("battle_id", battle_id).execute()
            broadcast_event(battle_id, "battle_end", {"message": "Battle completed 🏁"})
            break

    except Exception as e:
        logger.error(f"💥 Orchestrator error for {battle_id}: {e}")
    finally:
        active_battles.discard(battle_id)
        logger.info(f"🧹 Orchestrator stopped for {battle_id}")

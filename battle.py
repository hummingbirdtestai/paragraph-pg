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
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")  # ✅ NEW — from “Legacy JWT Secret”

# 🔍 Sanity check
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
            "exp": int(time.time()) + 60,  # valid 60s
        }

        # ⚙️ TEMPORARY DEBUG LOGS
        signing_key = SUPABASE_JWT_SECRET  # or change manually to SUPABASE_JWT_SECRET when testing
        token = jwt.encode(payload, signing_key, algorithm="HS256")

        logger.info("🔐 Generated Realtime JWT payload:")
        logger.info(json.dumps(payload, indent=2))
        logger.info(f"🔏 Using key: {'SERVICE_ROLE_KEY' if signing_key == SUPABASE_SERVICE_KEY else 'JWT_SECRET'}")
        logger.info(f"🔑 JWT sample (first 80 chars): {token[:80]}...")

        try:
            # 🔧 CHANGE: Ignore audience validation (to avoid harmless warning)
            decoded_check = jwt.decode(
                token, signing_key, algorithms=["HS256"], options={"verify_aud": False}
            )
            logger.info(f"🧩 Local verify → OK, aud={decoded_check.get('aud')}")
        except Exception as verify_err:
            logger.error(f"❌ Local verification failed → {verify_err}")

        return token
    except Exception as e:
        logger.error(f"❌ Failed to create realtime JWT: {e}")
        return SUPABASE_SERVICE_KEY

# -----------------------------------------------------
# 🔹 Broadcast Helper (✅ Realtime v2 REST schema)
# -----------------------------------------------------
def broadcast_event(battle_id: str, event: str, payload: dict):
    """Send broadcast event to Supabase Realtime channel (v2 format, normalized)."""
    try:
        # ✅ NORMALIZED BODY STRUCTURE — matches client .on('broadcast')
        body = {
            "messages": [
                {
                    "topic": f"battle:{battle_id}",
                    "event": "broadcast",   # <— always “broadcast” (NOT the event name)
                    "payload": {
                        "type": event,      # <— your actual event type (new_question, show_stats, etc.)
                        "data": payload     # <— event data goes inside “data”
                    },
                }
            ]
        }


        realtime_url = f"{SUPABASE_URL}/realtime/v1/api/broadcast"
        realtime_jwt = get_realtime_jwt()  # ✅ Use correct JWT

        logger.info(f"🌍 Realtime URL = {realtime_url}")
        logger.info(f"📡 Broadcasting {event} → battle:{battle_id}")
        logger.info(f"🧠 Payload = {json.dumps(body, indent=2)}")
        logger.info(f"🔧 Headers preview:")
        logger.info(json.dumps({
            "apikey": "SERVICE_ROLE_KEY...",
            "Authorization": f"Bearer {realtime_jwt[:40]}...",
            "Content-Type": "application/json"
        }, indent=2))

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

        logger.info(f"📡 [{battle_id}] Broadcast → {event} (status={res.status_code})")
        logger.warning(f"🧾 Response body: {res.text}")
        if res.status_code != 200 and res.status_code != 202:
            logger.warning(f"❌ Broadcast failed → {res.text}")
        else:
            logger.info(f"✅ Broadcast succeeded for {event}")
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
        logger.info(f"🧾 Supabase RPC get_battle_stats → data={resp.data}")
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
        logger.info(f"🧾 Supabase RPC get_leader_board → data={resp.data}")
        if not resp.data:
            raise HTTPException(status_code=404, detail="No leaderboard found")
        return {"success": True, "data": resp.data}
    except Exception as e:
        logger.error(f"💥 get_leaderboard failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------
# 🔹 Battle Start Endpoint (improved with resume logic)
# -----------------------------------------------------
@app.post("/battle/start/{battle_id}")
async def start_battle(battle_id: str, background_tasks: BackgroundTasks):
    logger.info(f"🚀 /battle/start called for battle_id={battle_id}")
    try:
        # 1️⃣ Fetch current participants
        logger.info(f"🔍 Fetching participants from Supabase for {battle_id}")
        participants_resp = (
            supabase.table("battle_participants")
            .select("id,user_id,username,status")
            .eq("battle_id", battle_id)
            .eq("status", "joined")
            .execute()
        )
        participants = participants_resp.data or []
        logger.info(f"👥 Joined players count = {len(participants)}")

        # 2️⃣ Fetch current battle status
        status_resp = (
            supabase.table("battle_schedule")
            .select("status")
            .eq("battle_id", battle_id)
            .single()
            .execute()
        )
        current_status = status_resp.data.get("status") if status_resp.data else None
        logger.info(f"📋 Current battle status for {battle_id} = {current_status}")

        # -----------------------------------------------------
        # 🧩 CASE 1 — Battle is already Active but orchestrator alive
        # -----------------------------------------------------
        if current_status and current_status.lower() == "active" and battle_id in active_battles:
            logger.info(f"🔁 Battle {battle_id} already running — user can join ongoing flow.")
            broadcast_event(
                battle_id,
                "battle_resume",
                {"message": "🔁 A new player joined an active battle — continuing broadcast."},
            )
            return {"success": True, "message": "Joined ongoing battle successfully"}

        # -----------------------------------------------------
        # 🧩 CASE 2 — Battle is Active in DB but orchestrator missing (zombie)
        # -----------------------------------------------------
        if current_status and current_status.lower() == "active" and battle_id not in active_battles:
            logger.warning(f"⚠ Battle {battle_id} marked Active in DB but orchestrator not running — restarting.")
            active_battles.add(battle_id)
            background_tasks.add_task(run_battle_sequence, battle_id)
            broadcast_event(
                battle_id,
                "battle_resume",
                {"message": "♻️ Orchestrator resumed automatically"},
            )
            return {"success": True, "message": "Battle resumed successfully"}

        # -----------------------------------------------------
        # 🧩 CASE 3 — Battle is Completed
        # -----------------------------------------------------
        if current_status and current_status.lower() == "completed":
            logger.info(f"🏁 Battle {battle_id} already completed — skipping orchestrator")
            return {"success": False, "message": "Battle already finished"}

        # -----------------------------------------------------
        # 🧩 CASE 4 — Normal fresh start
        # -----------------------------------------------------
        supabase.table("battle_schedule").update(
            {"status": "Active"}
        ).eq("battle_id", battle_id).execute()

        active_battles.add(battle_id)
        broadcast_event(
            battle_id,
            "battle_start_pending",
            {"message": "⚔️ Battle will begin shortly (5 s buffer for late joiners)"},
        )
        
        # 🕔 Backend buffer — allow all clients to subscribe
        logger.info(f"⏳ Delaying orchestrator start by 5 seconds for {battle_id}...")
        await asyncio.sleep(5)
        logger.info(f"🕒 Buffer window active — waiting for all participants to subscribe before launch.")
        
        broadcast_event(battle_id, "battle_start", {"message": "🚀 Battle officially started"})
        background_tasks.add_task(run_battle_sequence, battle_id)
        logger.info(f"✅ Buffered start triggered for battle_id={battle_id}")
        
        return {"success": True, "message": f"Battle {battle_id} will start after 5 s buffer"}

    except Exception as e:
        logger.error(f"💥 start_battle failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------
# 🔹 Main Orchestrator Loop
# -----------------------------------------------------
async def run_battle_sequence(battle_id: str):
    """start_orchestra → +20s get_bar_graph → +10s get_leader_board → +10s get_next_mcq → repeat"""
    logger.info(f"🏁 Orchestrator started for battle_id={battle_id}")
    try:
        current = supabase.rpc("get_first_mcq", {"battle_id_input": battle_id}).execute()
        logger.info(f"🧾 RPC get_first_mcq → {current.data}")

        if not current.data:
            logger.warning(f"⚠ No questions found for {battle_id}")
            broadcast_event(battle_id, "battle_end", {"message": "No MCQs found"})
            return

        while current.data:
            mcq = current.data[0]
            react_order = mcq.get("react_order", 0)
            total_mcqs = mcq.get("total_mcqs", 0)
            mcq_id = mcq["mcq_id"]

            broadcast_event(battle_id, "new_question", mcq)
            logger.info(f"🧩 Battle {battle_id} → Q{react_order}/{total_mcqs} started")

            await asyncio.sleep(20)
            # 🔧 CHANGE: flatten payload from list to object
            bar = supabase.rpc("get_battle_stats", {"mcq_id_input": mcq_id}).execute().data or []
            payload_bar = bar[0] if isinstance(bar, list) and len(bar) > 0 else {}
            logger.info(f"📊 Q{react_order}: get_bar_graph → {payload_bar}")
            broadcast_event(battle_id, "show_stats", payload_bar)

            await asyncio.sleep(10)
            # 🔧 CHANGE: flatten payload from list to object
            lead = supabase.rpc("get_leader_board", {"battle_id_input": battle_id}).execute().data or []
            payload_lead = lead[0] if isinstance(lead, list) and len(lead) > 0 else {}
            logger.info(f"🏆 Q{react_order}: get_leader_board → {payload_lead}")
            broadcast_event(battle_id, "update_leaderboard", payload_lead)

            await asyncio.sleep(10)
            logger.info(f"➡ Q{react_order}: fetching next MCQ")
            next_q = supabase.rpc(
                "get_next_mcq",
                {"battle_id_input": battle_id, "react_order_input": react_order},
            ).execute()

            if next_q.data:
                next_mcq = next_q.data[0]
                total_mcqs = next_mcq.get("total_mcqs", 0)   # ✅ NEW
                react_order_next = next_mcq.get("react_order", 0)
                mcq_id_next = next_mcq["mcq_id"]
            
                broadcast_event(battle_id, "new_question", next_mcq)
                logger.info(f"🧩 Next question → Q{react_order_next}/{total_mcqs}")
                current = next_q
                continue  # optional safety, explicit loop continue

            if not next_q.data:
                supabase.table("battle_schedule").update(
                    {"status": "Completed"}
                ).eq("battle_id", battle_id).execute()
                broadcast_event(battle_id, "battle_end", {"message": "Battle completed 🏁"})
                logger.info(f"✅ Battle {battle_id} completed.")
                break

    except Exception as e:
        logger.error(f"💥 Orchestrator error for {battle_id}: {e}")
    finally:
        active_battles.discard(battle_id)
        logger.info(f"🧹 Orchestrator stopped for {battle_id}")

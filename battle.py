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
            decoded_check = jwt.decode(token, signing_key, algorithms=["HS256"])
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
    """Send broadcast event to Supabase Realtime channel (v2 format)."""
    try:
        body = {
            "messages": [
                {
                    "topic": f"battle_{battle_id}",
                    "event": event,
                    "payload": payload,
                }
            ]
        }

        realtime_url = f"{SUPABASE_URL}/realtime/v1/broadcast"
        realtime_jwt = get_realtime_jwt()  # ✅ Use correct JWT

        logger.info(f"🌍 Realtime URL = {realtime_url}")
        logger.info(f"📡 Broadcasting {event} → battle_{battle_id}")
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
                "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                "Content-Type": "application/json",
                "x-project-ref": SUPABASE_URL.split("//")[1].split(".")[0],
                "x-client-info": "supabase-py-broadcast",
            },
            json=body,
            timeout=5,
        )

        logger.info(f"📡 [{battle_id}] Broadcast → {event} (status={res.status_code})")
        logger.warning(f"🧾 Response body: {res.text}")
        if res.status_code != 200:
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
# 🔹 Battle Start Endpoint
# -----------------------------------------------------
@app.post("/battle/start/{battle_id}")
async def start_battle(battle_id: str, background_tasks: BackgroundTasks):
    """Starts orchestrator if players exist; else waits 30-min grace."""
    logger.info(f"🚀 /battle/start called for battle_id={battle_id}")
    try:
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

        if not participants:
            logger.info(f"⏸ No participants found. Marking Active & entering grace period.")
            supabase.table("battle_schedule").update(
                {"status": "Active"}
            ).eq("battle_id", battle_id).execute()
            background_tasks.add_task(expire_battle_if_empty, battle_id)
            broadcast_event(battle_id, "waiting_period", {"message": "⌛ Waiting for players to join..."})
            logger.info(f"⏳ Grace period started for {battle_id}")
            return {"success": False, "message": "Waiting for players (30-min grace window)"}

        if battle_id in active_battles:
            logger.warning(f"⚠ Battle {battle_id} already running")
            return {"success": False, "message": "Already running"}

        active_battles.add(battle_id)
        supabase.table("battle_schedule").update(
            {"status": "Active"}
        ).eq("battle_id", battle_id).execute()

        logger.info(f"✅ Starting orchestrator for battle_id={battle_id} with {len(participants)} players")
        background_tasks.add_task(run_battle_sequence, battle_id)
        return {"success": True, "message": f"Battle {battle_id} orchestrator launched"}

    except Exception as e:
        logger.error(f"💥 start_battle failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------
# 🔹 Grace Expiry Handler
# -----------------------------------------------------
def expire_battle_if_empty(battle_id: str):
    """Marks battle Completed after 30-min grace if no players joined."""
    logger.info(f"🕒 Starting grace expiry timer for battle_id={battle_id}")
    time.sleep(30 * 60)
    participants = (
        supabase.table("battle_participants")
        .select("id")
        .eq("battle_id", battle_id)
        .eq("status", "joined")
        .execute()
        .data
        or []
    )
    if not participants:
        logger.info(f"💤 No players joined in grace window. Completing battle {battle_id}")
        supabase.table("battle_schedule").update(
            {"status": "Completed"}
        ).eq("battle_id", battle_id).execute()
        broadcast_event(battle_id, "battle_end", {"message": "No players joined. Battle expired."})
    else:
        logger.info(f"🎮 Players joined during grace period → {len(participants)} participants")

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
            mcq_id = mcq["mcq_id"]

            broadcast_event(battle_id, "new_question", mcq)
            logger.info(f"🧩 Battle {battle_id} → Q{react_order} started")

            await asyncio.sleep(20)
            bar = supabase.rpc("get_battle_stats", {"mcq_id_input": mcq_id}).execute().data or []
            logger.info(f"📊 Q{react_order}: get_bar_graph → {bar}")
            broadcast_event(battle_id, "show_stats", bar)

            await asyncio.sleep(10)
            lead = supabase.rpc("get_leader_board", {"battle_id_input": battle_id}).execute().data or []
            logger.info(f"🏆 Q{react_order}: get_leader_board → {lead}")
            broadcast_event(battle_id, "update_leaderboard", lead)

            await asyncio.sleep(10)
            logger.info(f"➡ Q{react_order}: fetching next MCQ")
            next_q = supabase.rpc(
                "get_next_mcq",
                {"battle_id_input": battle_id, "react_order_input": react_order},
            ).execute()

            if not next_q.data:
                supabase.table("battle_schedule").update(
                    {"status": "Completed"}
                ).eq("battle_id", battle_id).execute()
                broadcast_event(battle_id, "battle_end", {"message": "Battle completed 🏁"})
                logger.info(f"✅ Battle {battle_id} completed.")
                break

            current = next_q

    except Exception as e:
        logger.error(f"💥 Orchestrator error for {battle_id}: {e}")
    finally:
        active_battles.discard(battle_id)
        logger.info(f"🧹 Orchestrator stopped for {battle_id}")

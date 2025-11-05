# battle_api.py  ✅ FINAL PRODUCTION BUILD
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from dotenv import load_dotenv
import os, asyncio, logging, requests, time

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
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

active_battles = set()

# -----------------------------------------------------
# 🔹 Broadcast Helper
# -----------------------------------------------------
def broadcast_event(battle_id: str, event: str, payload: dict):
    """Send broadcast event to Supabase Realtime channel."""
    try:
        res = requests.post(
            f"{SUPABASE_URL}/realtime/v1/api/broadcast",
            headers={
                "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "channel": f"battle_{battle_id}",
                "event": event,
                "payload": payload,
            },
            timeout=5,
        )
        logger.info(f"📡 [{battle_id}] Broadcast → {event} ({res.status_code})")
        return res.ok
    except Exception as e:
        logger.error(f"❌ Broadcast failed ({event}): {e}")
        return False


# -----------------------------------------------------
# 🔹 Root Endpoint
# -----------------------------------------------------
@app.get("/")
async def root():
    return {"status": "Battle API running ✅"}


# -----------------------------------------------------
# 🔹 Utility Endpoints
# -----------------------------------------------------
@app.post("/battle/get_stats")
async def get_battle_stats(mcq_id: str):
    try:
        resp = supabase.rpc("get_battle_stats", {"mcq_id_input": mcq_id}).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail="No stats found")
        return {"success": True, "data": resp.data}
    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/battle/leaderboard")
async def get_leaderboard(battle_id: str):
    try:
        resp = supabase.rpc("get_leader_board", {"battle_id_input": battle_id}).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail="No leaderboard found")
        return {"success": True, "data": resp.data}
    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------
# 🔹 Battle Start Endpoint
# -----------------------------------------------------
@app.post("/battle/start/{battle_id}")
async def start_battle(battle_id: str, background_tasks: BackgroundTasks):
    """Starts orchestrator if players exist; else waits 30-min grace."""
    try:
        participants = (
            supabase.table("battle_participants")
            .select("id")
            .eq("battle_id", battle_id)
            .eq("status", "joined")
            .execute()
            .data
            or []
        )

        logger.info(f"🔍 [{battle_id}] Joined players: {len(participants)}")

        if not participants:
            supabase.table("battle_schedule").update(
                {"status": "Active"}
            ).eq("battle_id", battle_id).execute()
            background_tasks.add_task(expire_battle_if_empty, battle_id)
            broadcast_event(
                battle_id, "waiting_period", {"message": "⌛ Waiting for players to join..."}
            )
            logger.info(f"⏳ Grace period started for {battle_id}")
            return {"success": False, "message": "Waiting for players (30-min grace window)"}

        if battle_id in active_battles:
            logger.warning(f"⚠ Battle {battle_id} already running")
            return {"success": False, "message": "Already running"}

        active_battles.add(battle_id)
        supabase.table("battle_schedule").update(
            {"status": "Active"}
        ).eq("battle_id", battle_id).execute()

        logger.info(f"🚀 Battle {battle_id} started with {len(participants)} players")
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
        supabase.table("battle_schedule").update(
            {"status": "Completed"}
        ).eq("battle_id", battle_id).execute()
        broadcast_event(battle_id, "battle_end", {"message": "No players joined. Battle expired."})
        logger.warning(f"🕒 Battle {battle_id} expired due to inactivity.")


# -----------------------------------------------------
# 🔹 Main Orchestrator Loop
# -----------------------------------------------------
async def run_battle_sequence(battle_id: str):
    """start_orchestra → +20s get_bar_graph → +10s get_leader_board → +10s get_next_mcq → repeat"""
    try:
        logger.info(f"🏁 Orchestrator started for {battle_id}")

        current = supabase.rpc("get_first_mcq", {"battle_id_input": battle_id}).execute()
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

            # 20 s → get_bar_graph
            await asyncio.sleep(20)
            bar = supabase.rpc("get_bar_graph", {"mcq_id_input": mcq_id}).execute().data or []
            broadcast_event(battle_id, "show_stats", bar)
            logger.info(f"📊 Q{react_order}: get_bar_graph fired (+20 s)")

            # 10 s → get_leader_board
            await asyncio.sleep(10)
            lead = supabase.rpc("get_leader_board", {"battle_id_input": battle_id}).execute().data or []
            broadcast_event(battle_id, "update_leaderboard", lead)
            logger.info(f"🏆 Q{react_order}: get_leader_board fired (+30 s)")

            # 10 s → get_next_mcq
            await asyncio.sleep(10)
            logger.info(f"➡ Q{react_order}: get_next_mcq fired (+40 s)")
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

            current = next_q  # move to next MCQ

    except Exception as e:
        logger.error(f"💥 Orchestrator error for {battle_id}: {e}")
    finally:
        active_battles.discard(battle_id)
        logger.info(f"🧹 Orchestrator stopped for {battle_id}")

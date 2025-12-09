require("dotenv").config();
const { createClient } = require("@supabase/supabase-js");
const { Client } = require("pg");

// ---------------------------------------------
// 1. Supabase client (service role)
// ---------------------------------------------
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);

// ---------------------------------------------
// 2. Connect to Postgres to listen for NOTIFY
// ---------------------------------------------
const pgClient = new Client({
  connectionString: process.env.DATABASE_URL,
});

async function startWorker() {
  await pgClient.connect();
  console.log("📡 Connected to PostgreSQL LISTEN channel");

  // subscribe to notifications
  await pgClient.query(`LISTEN student_notifications_channel`);
  console.log("👂 Listening for student notifications...");

  pgClient.on("notification", async (msg) => {
    if (!msg.payload) return;

    // Convert payload to JSON
    const data = JSON.parse(msg.payload);
    console.log("🔔 New Notification from DB:", data);

    // -----------------------------------------
    // 3. Broadcast notification via Supabase
    // -----------------------------------------
    const channel = supabase.channel("student_notifications");

    await channel.send({
      type: "broadcast",
      event: `notif_for_${data.student_id}`,
      payload: data,
    });

    console.log("📤 Delivered to Realtime:", data.student_id);
  });
}

startWorker().catch(console.error);

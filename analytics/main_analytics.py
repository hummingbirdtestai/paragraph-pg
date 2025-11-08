from fastapi import FastAPI
from fastapi.responses import JSONResponse
from analytics.analytics_tasks import router as analytics_router

app = FastAPI(title="Paragraph Analytics Service")

# Register routes
app.include_router(analytics_router)

@app.get("/")
def root():
    return {"message": "Analytics service is live ✅"}


# --- 🔍 Diagnostic Route to Test LangChain + DB ---
@app.get("/test-db")
async def test_db():
    try:
        from analytics.langchain_engine import db, llm

        # Run a basic SQL test query
        result = db.run("SELECT NOW();")

        return JSONResponse({
            "status": "✅ Connected Successfully",
            "timestamp": result,
            "llm_model": getattr(llm, "model_name", "unknown")
        })

    except Exception as e:
        # Capture and return full error details
        import traceback
        error_details = traceback.format_exc()
        print("❌ /test-db error:", error_details)

        return JSONResponse({
            "status": "❌ Connection Failed",
            "error": str(e),
            "traceback": error_details
        }, status_code=500)

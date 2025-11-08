from fastapi import FastAPI
from analytics.analytics_tasks import router as analytics_router

app = FastAPI(title="Paragraph Analytics Service")

# Register routes
app.include_router(analytics_router)

@app.get("/")
def root():
    return {"message": "Analytics service is live ✅"}

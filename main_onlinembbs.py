from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from newchat_onlinembbs import router as mbbs_router

app = FastAPI(title="Paragraph MBBS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(mbbs_router, prefix="/ask-paragraph-mbbs")

@app.get("/")
def health():
    return {"status": "MBBS service running"}

from fastapi import FastAPI

app = FastAPI(title="OrderlyFoods AI-OS", version="4.0.0")


@app.get("/health", tags=["platform"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}

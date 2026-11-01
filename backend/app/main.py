from fastapi import FastAPI

from app.routers import contact, tickets

app = FastAPI(title="IntentGrid API")

app.include_router(contact.router)
app.include_router(tickets.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}

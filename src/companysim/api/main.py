"""FastAPI app — the webapp's backend.

Run with:

    uvicorn companysim.api.main:app --reload

Swagger UI at /docs.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from companysim.api.database import init_db
from companysim.api.routers import departments, diagnose, employees, orgs, simulate, teams


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="companysim API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(orgs.router)
app.include_router(departments.router)
app.include_router(teams.router)
app.include_router(employees.router)
app.include_router(simulate.router)
app.include_router(diagnose.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"docs": "/docs"}

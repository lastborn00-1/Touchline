"""Touchline API: FastAPI + SSE streaming of the synthetic match with agent insights.

Endpoints:
  GET  /health                      -> liveness
  POST /api/match/new {seed:int}    -> create a match, returns id + metadata
  GET  /api/match/{mid}             -> full metadata
  GET  /api/match/{mid}/stream      -> text/event-stream: event, metrics, insights
Static frontend is served from / (frontend/ directory).
"""
from __future__ import annotations

import asyncio
import json
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.agents.agents import Orchestrator
from backend.analytics.metrics import MetricsEngine
from backend.simulator.generator import generate_match

app = FastAPI(title="Touchline", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

MATCHES: dict[str, dict] = {}
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")


@app.get("/health")
def health():
    return {"status": "ok", "service": "touchline"}


@app.post("/api/match/new")
async def new_match(body: dict | None = None):
    seed = int((body or {}).get("seed", 7))
    meta, events = generate_match(seed)
    mid = f"m{seed}"
    MATCHES[mid] = {"meta": meta, "events": events}
    return {"id": mid, "meta": meta, "event_count": len(events)}


@app.get("/api/match/{mid}")
def get_match(mid: str):
    if mid not in MATCHES:
        raise HTTPException(404, "match not found")
    return MATCHES[mid]["meta"]


@app.get("/api/match/{mid}/stream")
def stream(mid: str, speed: float = 8.0):
    """SSE stream: each tick = one event + metrics + agent insights."""
    if mid not in MATCHES:
        raise HTTPException(404, "match not found")
    meta = MATCHES[mid]["meta"]
    events = MATCHES[mid]["events"]
    home, away = meta["home"]["short"], meta["away"]["short"]
    eng = MetricsEngine(home, away)
    orch = Orchestrator(home, away)

    async def gen():
        yield f"data: {json.dumps({'kind': 'meta', 'meta': meta})}\n\n"
        for ev in events:
            m = eng.process(ev)
            insights = orch.tick(ev, m)
            payload = {"kind": "tick", "event": ev, "metrics": m, "insights": insights}
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(max(0.02, 1.0 / speed))
        yield f"data: {json.dumps({'kind': 'summary', 'summary': eng.summary()})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

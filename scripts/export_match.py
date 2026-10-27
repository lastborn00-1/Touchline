"""Offline match export: precompute events + metrics + agent insights to
frontend/demo/match.json so the hosted frontend can replay a full match
standalone (static-hosting friendly, no backend needed)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.simulator.generator import generate_match
from backend.analytics.metrics import MetricsEngine
from backend.agents.agents import Orchestrator

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 7
meta, events = generate_match(seed)
home, away = meta["home"]["short"], meta["away"]["short"]
eng = MetricsEngine(home, away)
orch = Orchestrator(home, away)
ticks = []
for ev in events:
    m = eng.process(ev)
    ins = orch.tick(ev, m)
    ticks.append({"event": ev, "metrics": m, "insights": ins})
out = {"meta": meta, "summary": eng.summary(), "ticks": ticks}
os.makedirs(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "demo"), exist_ok=True)
path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "demo", "match.json")
with open(path, "w") as f:
    json.dump(out, f)
print("ticks:", len(ticks), "bytes:", os.path.getsize(path))

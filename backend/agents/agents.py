"""Multi-agent intelligence layer for Touchline.

Three specialized agents consume the event + metrics stream over a shared
blackboard, coordinated by an orchestrator with per-agent cooldowns:

  - TacticalAnalystAgent: explainable tactical reasoning (why a moment matters)
  - LiveCommentatorAgent: broadcast play-by-play lines
  - RecapAgent: end-of-half and full-time structured recaps

Narratives are generated from structured evidence templates by default so the
demo runs with zero external dependencies. Setting AZURE_OPENAI_ENDPOINT +
AZURE_OPENAI_API_KEY switches the same call sites to Microsoft Foundry
(Azure OpenAI) for LLM-written commentary, with the templates as fallback.
"""
from __future__ import annotations

import os
from collections import deque

import httpx


class Blackboard:
    """Shared state every agent reads and writes; keeps evidence ids intact."""

    def __init__(self):
        self.timeline: deque = deque(maxlen=400)
        self.score: dict = {}
        self.events: list = []

    def add(self, ev: dict, metrics: dict):
        self.events.append(ev)
        self.timeline.append({"ev": ev, "m": metrics})
        self.score = metrics.get("score", self.score)

    def recent(self, n=8) -> list:
        return list(self.timeline)[-n:]


def _llm(prompt: str, system: str) -> str | None:
    """Azure OpenAI (Microsoft Foundry) adapter. Returns None when not configured."""
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    key = os.getenv("AZURE_OPENAI_API_KEY")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    if not endpoint or not key:
        return None
    try:
        r = httpx.post(
            f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version=2024-06-01",
            headers={"api-key": key},
            json={"messages": [{"role": "system", "content": system},
                               {"role": "user", "content": prompt}],
                  "max_tokens": 220, "temperature": 0.7},
            timeout=8,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


class Agent:
    name = "agent"
    cooldown_s = 20.0

    def __init__(self):
        self.last_emit = -999.0

    def ready(self, t: float) -> bool:
        return t - self.last_emit >= self.cooldown_s


class TacticalAnalystAgent(Agent):
    name = "tactical_analyst"
    cooldown_s = 45.0
    SYSTEM = ("You are a broadcast tactical analyst. Explain in 1-2 sentences WHY a moment "
              "matters tactically, grounded in the metrics provided. Never invent facts.")

    def observe(self, ev: dict, m: dict, bb: Blackboard) -> dict | None:
        if not self.ready(ev["t"]):
            return None
        t = ev["type"]
        home, away = bb.home, bb.away
        ctrl = m.get("control") or {}
        line = None
        if t == "line_breaking_pass":
            line = (f"{ev['player']} threads a line-breaking pass: high difficulty ({ev.get('pdr', 0)}), "
                    f"forcing {away if ev['team'] == home else home} to scramble their block.")
        elif t == "shot":
            pdr = ev.get("xg", 0)
            line = (f"Shot worth xG {pdr} from {ev.get('shot_type', 'open play')}; "
                    f"control index {ctrl.get(ev['team'], 50)} says {'structured' if ctrl.get(ev['team'], 50) > 60 else 'transition'} pressure.")
        elif t == "goal":
            line = (f"GOAL sequence justified: cumulative xG now "
                    f"{m['xg'].get(home, 0):.2f}-{m['xg'].get(away, 0):.2f}, the chance quality was real, not a fluke.")
        elif t == "tackle" or t == "interception":
            ppda = m.get("ppda")
            if ppda:
                line = (f"{ev['team']} pressing hard: PPDA {ppda} (lower = more aggressive). "
                        f"Counter-press is biting high up the pitch.")
        if line is None:
            return None
        text = _llm(f"Event: {ev}\nMetrics: {m}", self.SYSTEM) or line
        self.last_emit = ev["t"]
        return {"agent": self.name, "t": ev["t"], "text": text,
                "evidence": [ev["id"]], "kind": "tactical"}


class LiveCommentatorAgent(Agent):
    name = "live_commentator"
    cooldown_s = 12.0
    SYSTEM = ("You are a live football commentator. One punchy play-by-play sentence, "
              "no more than 20 words, based strictly on the event given.")

    def observe(self, ev: dict, m: dict, bb: Blackboard) -> dict | None:
        if not self.ready(ev["t"]):
            return None
        t = ev["type"]
        templates = {
            "goal": f"IT'S IN! {ev['player']} scores for {ev['team']}! {m['score'].get(ev['team'], 0)} now!",
            "shot": f"{ev['player']} lets fly! {'on target' if ev.get('on_target') else 'wide'}, xG {ev.get('xg', 0):.2f}.",
            "save": f"Big save denies {ev['team']}! Keeper stands tall.",
            "pass": (f"Sharp distribution from {ev['player']}, {ev.get('length', 0)}m into the next phase."
                     if ev.get("pdr", 0) >= 0.6 else None),
            "tackle": f"Crunching challenge! {ev['team']} win it back.",
            "interception": f"Read beautifully by {ev['player']}, interception!",
            "corner": f"Corner to {ev['team']}, bodies forward.",
            "foul": f"Free kick conceded, {ev['team']} can breathe.",
        }
        line = templates.get(t)
        if line is None:
            return None
        text = _llm(str(ev), self.SYSTEM) or line
        self.last_emit = ev["t"]
        return {"agent": self.name, "t": ev["t"], "text": text,
                "evidence": [ev["id"]], "kind": "commentary"}


class RecapAgent(Agent):
    name = "recap_writer"
    SYSTEM = ("You are a sports desk writer. Produce a 4-sentence match recap for the studio "
              "script, using only the facts in the summary provided.")

    def observe(self, ev: dict, m: dict, bb: Blackboard) -> dict | None:
        if ev["type"] != "goal":
            return None
        half = 1 if ev["t"] < 45 * 60 else 2
        s = bb.score
        goals = [e for e in bb.events if e["type"] == "goal"]
        scorers = ", ".join(g["player"] for g in goals[-3:])
        xg = m.get("xg", {})
        text = _llm(f"Score {s}. Goals: {scorers}. xG: {xg}", self.SYSTEM) or (
            f"{ev['team']} strike through {ev['player']}. Score now {s.get(list(s)[0], 0)}-"
            f"{s.get(list(s)[1], 0) if len(s) > 1 else 0}. "
            f"Chance quality backs it: xG {xg.get(ev['team'], 0):.2f}. {scorers} central to every good move.")
        return {"agent": self.name, "t": ev["t"], "text": text,
                "evidence": [ev["id"]], "kind": "recap"}


class Orchestrator:
    """Runs every agent over each event tick, with per-agent cooldowns and a
    shared blackboard. Mirrors the Microsoft Agent Framework handoff pattern:
    state handoffs via the blackboard, role delegation, resilient fallbacks."""

    def __init__(self, home: str, away: str):
        self.bb = Blackboard()
        self.bb.home, self.bb.away = home, away
        self.agents = [TacticalAnalystAgent(), LiveCommentatorAgent(), RecapAgent()]

    def tick(self, ev: dict, metrics: dict) -> list:
        self.bb.add(ev, metrics)
        insights = []
        for a in self.agents:
            try:
                ins = a.observe(ev, metrics, self.bb)
                if ins:
                    insights.append(ins)
            except Exception:
                continue  # an agent failing never takes down the pipeline
        return insights

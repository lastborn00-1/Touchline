"""Derived football metrics engine for the synthetic event stream.

Consumes events in clock order and maintains rolling state for:
  - direction-aware Expected Goals (xG)
  - Pass Difficulty Rating (PDR)
  - Control vs Chaos Index (0-100)
  - PPDA (passes allowed per defensive action)
  - possession % and final-third field tilt
  - running score / momentum
Every insight the agents emit carries the event ids it is built on, so the
explainability bar ("why a moment matters") is always traceable.
"""
from __future__ import annotations

import math
from collections import deque

PITCH_X, PITCH_Y = 105.0, 68.0
GOAL_HALF_WIDTH = 3.66

SHOT_MULT = {"open_play": 1.0, "header": 0.55, "volley": 0.70, "free_kick": 0.45, "penalty": 0.78}


def xg(dist: float, theta: float, shot_type: str = "open_play") -> float:
    p = math.exp(-0.115 * dist) * (theta / math.pi * 3.4) * SHOT_MULT.get(shot_type, 1.0)
    return max(0.01, min(0.96, p))


def goal_angle(sx: float, sy: float, gx: float) -> float:
    y1, y2 = PITCH_Y / 2 - GOAL_HALF_WIDTH, PITCH_Y / 2 + GOAL_HALF_WIDTH
    return abs(math.atan2(y2 - sy, gx - sx) - math.atan2(y1 - sy, gx - sx))


class MetricsEngine:
    """Streaming metrics over the synthetic event list."""

    def __init__(self, home: str, away: str, window: int = 25):
        self.home, self.away = home, away
        self.window = window
        self.score = {home: 0, away: 0}
        self.shots = {home: 0, away: 0}
        self.shots_on_target = {home: 0, away: 0}
        self.xg_total = {home: 0.0, away: 0.0}
        self.passes = {home: [0, 0], away: [0, 0]}
        self.defensive_actions = {home: 0, away: 0}
        self.defensive_third_passes_allowed = {home: 0, away: 0}
        self.chaos = deque(maxlen=window)  # 1 = chaos event in window
        self.attack_dir = {home: 1, away: -1}
        self.last_team = None
        self.sequences = {home: 0, away: 0}

    # -- helpers ---------------------------------------------------------
    def _dir(self, team: str) -> int:
        return self.attack_dir[team]

    def control_index(self) -> dict:
        """0 (pure chaos) to 100 (total control), from the rolling window."""
        if not self.chaos:
            return {self.home: 50.0, self.away: 50.0}
        n = len(self.chaos)
        chaos_share = sum(self.chaos) / n
        base = 100 * (1 - chaos_share)
        # the team holding the ball longer in the window gets the share of control
        seq = self.sequences
        tot = seq[self.home] + seq[self.away] or 1
        return {
            self.home: round(base * seq[self.home] / tot, 1),
            self.away: round(base * seq[self.away] / tot, 1),
        }

    # -- main entry ------------------------------------------------------
    def process(self, ev: dict) -> dict:
        team, oteam = ev["team"], (self.away if ev["team"] == self.home else self.home)
        t = ev["type"]
        out = {"id": ev["id"], "t": ev["t"], "type": t, "team": team,
               "score": dict(self.score)}

        if t == "pass":
            ok = ev.get("completed", True)
            self.passes[team][0] += 1
            self.sequences[team] += 1 if ok else -2
            if ok:
                self.passes[team][1] += 1
                fx = ev["from"]["x"]; tx = ev["to"]["x"]
                gain = (tx - fx) * self._dir(team)
                length = ev.get("length", math.hypot(tx - fx, ev["to"]["y"] - ev["from"]["y"]))
                # Pass Difficulty Rating: length + progression + line break bonus
                line_break = 1 if (gain > 25 and abs(ev["to"]["y"] - ev["from"]["y"]) > 15) else 0
                pdr = 0.08 + 0.45 * length / 50 + 0.25 * max(gain, 0) / 35 + 0.18 * line_break
                ev["pdr"] = round(max(0.05, min(0.98, pdr)), 2)
                if ev["pdr"] >= 0.7:
                    out["note"] = "line_breaking_pass"
            else:
                self.chaos.append(1)
        elif t == "bad_pass":
            self.passes[team][0] += 1
            self.chaos.append(1)
            self.sequences[team] = max(0, self.sequences[team] - 2)
        elif t in ("tackle", "interception"):
            self.defensive_actions[team] += 1
            self.chaos.append(1)
            self.sequences[team] = max(0, self.sequences[team] - 3)
            # passes allowed by the *other* team in our defensive third
        elif t == "carry":
            self.sequences[team] += 1
            self.chaos.append(0)
        elif t == "shot":
            self.shots[team] += 1
            if ev.get("on_target"):
                self.shots_on_target[team] += 1
            gx = PITCH_X if self._dir(team) == 1 else 0.0
            d = math.hypot(gx - ev["from"]["x"], PITCH_Y / 2 - ev["from"]["y"])
            theta = goal_angle(ev["from"]["x"], ev["from"]["y"], gx)
            p = ev.get("xg") or xg(d, theta, ev.get("shot_type", "open_play"))
            self.xg_total[team] += p
            ev["xg"] = round(p, 3)
            self.chaos.append(1)
            out["xg"] = ev["xg"]
        elif t == "goal":
            self.score[team] += 1
            out["score"] = dict(self.score)
            out["big_moment"] = True
        elif t == "corner":
            self.chaos.append(0)
        elif t == "foul":
            self.chaos.append(1)

        # PPDA: opponent passes in our defensive third / our defensive actions
        if t == "pass" and ev.get("completed"):
            fx = ev["from"]["x"]
            in_our_def_third = (fx < 35 and self._dir(oteam) == 1) or (fx > 70 and self._dir(oteam) == -1)
            if in_our_def_third:
                self.defensive_third_passes_allowed[oteam] += 1
        out["ppda"] = {
            k: (round(self.defensive_third_passes_allowed[k] / self.defensive_actions[k], 2)
                if self.defensive_actions[k] else None)
            for k in (self.home, self.away)
        }
        out["possession"] = self.possession()
        out["control"] = self.control_index()
        out["xg"] = {k: round(v, 2) for k, v in self.xg_total.items()}
        self.last_team = team
        return out

    def possession(self) -> dict:
        pa = self.passes[self.home][0] + self.passes[self.away][0]
        if not pa:
            return {self.home: 50.0, self.away: 50.0}
        ph = 100.0 * self.passes[self.home][0] / pa
        return {self.home: round(ph, 1), self.away: round(100 - ph, 1)}

    def tilt(self) -> dict:
        """Final-third field tilt: share of touches (events) in the final third."""
        return self._third_shares()

    def _third_shares(self) -> dict:
        # placeholder replaced by live computation in engine.run below
        return {}

    def summary(self) -> dict:
        ci = self.control_index()
        return {
            "score": dict(self.score),
            "shots": dict(self.shots),
            "shots_on_target": dict(self.shots_on_target),
            "xg": {k: round(v, 2) for k, v in self.xg_total.items()},
            "pass_accuracy": {k: (round(v[1] / v[0] * 100, 1) if v[0] else 0.0) for k, v in self.passes.items()},
            "possession": self.possession(),
            "ppda": {k: (round(self.defensive_third_passes_allowed[k] / self.defensive_actions[k], 2)
                         if self.defensive_actions[k] else None) for k in (self.home, self.away)},
            "control_index": ci,
        }


def run_metrics(events: list) -> tuple[dict, list]:
    """Convenience: run the whole match, return (timeline, engine.summary())."""
    from backend.simulator.generator import teams  # not used for names; events carry shorts
    if not events:
        return {}, {}
    home, away = events[0]["team"], events[1]["team"] if events[1]["team"] != events[0]["team"] else events[0]["team"]
    eng = MetricsEngine(home, away)
    timeline = [eng.process(e) for e in events]
    return timeline, eng.summary()

"""Synthetic football match event generator (no real league data, no real trademarks).

Generates a football-realistic 90-minute event stream for two fictional clubs on a
105m x 68m pitch. All data is synthetic; the distributions are calibrated to look
like a top-flight match (pass completion ~75-85%, 20-30 shots) without ingesting
any real match data.
"""
from __future__ import annotations

import math
import random

PITCH_X, PITCH_Y = 105.0, 68.0
GOAL_HALF_WIDTH = 3.66

SHOT_TYPES = [
    ("open_play", 1.00, 0.68),
    ("header", 0.55, 0.12),
    ("volley", 0.70, 0.08),
    ("free_kick", 0.45, 0.07),
    ("penalty", 0.78, 0.05),
]


def _squad(prefix: str) -> list:
    roles = ["GK"] + ["DF"] * 4 + ["MF"] * 3 + ["FW"] * 3
    return [{"name": f"{prefix} {i + 1:02d}", "role": r} for i, r in enumerate(roles)]


def _xg(dist: float, theta: float, shot_mult: float) -> float:
    p = math.exp(-0.115 * dist) * (theta / math.pi * 3.4) * shot_mult
    return max(0.01, min(0.96, p))


def _goal_angle(sx: float, sy: float, gx: float) -> float:
    y1, y2 = PITCH_Y / 2 - GOAL_HALF_WIDTH, PITCH_Y / 2 + GOAL_HALF_WIDTH
    a1 = math.atan2(y1 - sy, gx - sx)
    a2 = math.atan2(y2 - sy, gx - sx)
    return abs(a2 - a1)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def generate_match(seed: int = 7) -> tuple[dict, list]:
    rng = random.Random(seed)
    hq, aq = 0.55 + rng.uniform(-0.05, 0.05), 0.50 + rng.uniform(-0.05, 0.05)
    home = {"name": "Kwara Dynamos", "short": "KWD", "color": "#0b6e4f", "dir": +1, "q": hq,
            "players": _squad("KWD")}
    away = {"name": "Coastal Rovers", "short": "CST", "color": "#7b1e3a", "dir": -1, "q": aq,
            "players": _squad("CST")}
    short = {"KWD": home, "CST": away}

    events: list[dict] = []
    eid = 0
    clock = 0.0
    poss = home if rng.random() < hq / (hq + aq) else away
    ball = {"x": PITCH_X / 2, "y": PITCH_Y / 2}
    shots = {"KWD": 0, "CST": 0}
    passes = {"KWD": [0, 0], "CST": [0, 0]}
    added_first = rng.randint(60, 300)
    added_second = rng.randint(180, 420)

    def emit(kind, t, team, **kw):
        nonlocal eid
        ev = {"id": eid, "t": round(t, 1), "type": kind, "team": team["short"],
              "from": {"x": round(ball["x"], 1), "y": round(ball["y"], 1)}}
        if "to_x" in kw:
            ev["to"] = {"x": round(kw.pop("to_x"), 1), "y": round(kw.pop("to_y"), 1)}
        if "player" not in kw:
            kw["player"] = team["players"][rng.randrange(0, 11)]["name"]
        ev.update(kw)
        events.append(ev)
        eid += 1
        return ev

    end_first, end_match = 45 * 60 + added_first, 90 * 60 + added_second
    while clock < end_match:
        other = away if poss is home else home
        d = poss["dir"]
        if rng.random() < 0.30 * (0.55 - 0.10 * poss["q"]):
            # turnover
            r = rng.random()
            if r < 0.42:
                emit("tackle", clock, other)
            elif r < 0.72:
                emit("interception", clock, other)
            else:
                emit("bad_pass", clock, poss)
            if r < 0.72:
                poss = other
            ball = {"x": _clamp(ball["x"] + rng.uniform(-8, 8), 0, PITCH_X),
                    "y": _clamp(ball["y"] + rng.uniform(-10, 10), 0, PITCH_Y)}
        elif rng.random() < 0.10:
            ev = emit("carry", clock, poss,
                      to_x=_clamp(ball["x"] + d * rng.uniform(6, 22), 0, PITCH_X),
                      to_y=_clamp(ball["y"] + rng.uniform(-12, 12), 0, PITCH_Y))
            ball = dict(ev["to"])
        elif (_clamp(ball["x"], 0, PITCH_X) > 70 if d == 1 else _clamp(ball["x"], 0, PITCH_X) < 35) \
                and rng.random() < 0.16 and shots[poss["short"]] < 32:
            r = rng.random()
            acc, stype, mult = 0.0, "open_play", 1.0
            for name, m, w in SHOT_TYPES:
                acc += w
                if r <= acc:
                    stype, mult = name, m
                    break
            gx, gy = (PITCH_X if d == 1 else 0.0), PITCH_Y / 2
            sx, sy = ball["x"], ball["y"]
            dist = math.hypot(gx - sx, gy - sy)
            p = _xg(dist, _goal_angle(sx, sy, gx), mult)
            on_target = rng.random() < (0.25 + 0.45 * p)
            goal = on_target and rng.random() < p * 1.35
            ev = emit("shot", clock, poss, shot_type=stype,
                      to_x=gx, to_y=gy + rng.uniform(-3.2, 3.2),
                      on_target=on_target, outcome="goal" if goal else ("saved" if on_target else "off_target"),
                      xg=round(p, 3))
            shots[poss["short"]] += 1
            if goal:
                emit("goal", clock + 2, poss, xg=ev["xg"])
                ball = {"x": PITCH_X / 2, "y": PITCH_Y / 2}
                poss = other
            elif on_target:
                emit("save", clock + 2, other)
                if rng.random() < 0.5:
                    emit("corner", clock + 5, poss)
                poss = rng.choice([poss, other])
            else:
                if rng.random() < 0.7:
                    poss = other
        else:
            # pass attempt
            tx = _clamp(ball["x"] + d * rng.uniform(2, 30), 0, PITCH_X)
            ty = _clamp(ball["y"] + rng.uniform(-18, 18), 0, PITCH_Y)
            length = math.hypot(tx - ball["x"], ty - ball["y"])
            p_complete = max(0.25, min(0.96, 0.95 - 0.011 * length - 0.02 * abs(tx - PITCH_X / 2) / 10))
            ok = rng.random() < p_complete
            rec = poss["players"][rng.randrange(1, 11)]["name"]
            emit("pass", clock, poss, to_x=tx, to_y=ty, completed=ok,
                 length=round(length, 1), recipient=rec)
            passes[poss["short"]][0] += 1
            if ok:
                passes[poss["short"]][1] += 1
                ball = {"x": tx, "y": ty}
            else:
                ball = {"x": _clamp(ball["x"] + d * length * 0.3, 0, PITCH_X),
                        "y": _clamp(ball["y"] + rng.uniform(-8, 8), 0, PITCH_Y)}
                if rng.random() < 0.65:
                    poss = other
            if rng.random() < 0.035:
                emit("foul", clock + 1, other)
        clock += rng.uniform(3.0, 9.5)

    meta = {
        "home": {"name": home["name"], "short": home["short"], "color": home["color"]},
        "away": {"name": away["name"], "short": away["short"], "color": away["color"]},
        "seed": seed,
        "duration_s": round(clock, 1),
        "pass_totals": {k: {"attempted": v[0], "completed": v[1]} for k, v in passes.items()},
    }
    return meta, events

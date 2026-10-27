import math

from backend.analytics.metrics import MetricsEngine, goal_angle, xg


def _ev(i, t, team, **kw):
    e = {"id": i, "t": i * 5.0, "type": t, "team": team,
         "from": {"x": kw.pop("fx", 50.0), "y": kw.pop("fy", 34.0)}}
    if "tx" in kw:
        e["to"] = {"x": kw.pop("tx"), "y": kw.pop("ty", 34.0)}
    e.update(kw)
    return e


def test_xg_bounds_and_distance_decay():
    close = xg(6.0, goal_angle(99, 34, 105))
    far = xg(30.0, goal_angle(75, 34, 105))
    assert 0.01 <= close <= 0.96 and 0.01 <= far <= 0.96
    assert close > far


def test_pass_difficulty_rises_with_length_and_progression():
    eng = MetricsEngine("H", "A")
    short = _ev(0, "pass", "H", fx=40, tx=50, completed=True, length=10)
    long_break = _ev(1, "pass", "H", fx=30, tx=80, completed=True, length=52)
    m1, m2 = eng.process(short), eng.process(long_break)
    assert m1 and "pdr" in short and "pdr" in long_break
    assert long_break["pdr"] > short["pdr"]


def test_control_index_drops_on_turnovers():
    eng = MetricsEngine("H", "A")
    for i in range(8):
        eng.process(_ev(i, "pass", "H", fx=40, tx=48, completed=True, length=8))
    calm = eng.control_index()["H"]
    eng.process(_ev(99, "interception", "A"))
    after = eng.control_index()["H"]
    assert after < calm


def test_score_and_xg_on_goal():
    eng = MetricsEngine("H", "A")
    eng.process(_ev(0, "shot", "H", fx=95, fy=32, on_target=True, xg=0.45))
    out = eng.process(_ev(1, "goal", "H", fx=99, fy=34))
    assert out["score"] == {"H": 1, "A": 0}
    assert eng.xg_total["H"] >= 0.45


def test_ppda_shape():
    eng = MetricsEngine("H", "A")
    eng.process(_ev(0, "interception", "H"))
    out = eng.process(_ev(1, "pass", "A", fx=20, tx=40, completed=True, length=20))
    assert out["ppda"]["H"] is not None and out["ppda"]["H"] >= 0

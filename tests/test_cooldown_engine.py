"""Isolated full-Python-engine regression for RUBY Smart Chip #07, #06 and #99."""
import json
import re
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
html = (root / "index.html").read_text(encoding="utf-8")
sources = re.findall(r'<script type="text/plain" id="py-src-([^"]+)">([\s\S]*?)</script>', html)
assert len(sources) == 8, f"expected 8 Python modules, got {len(sources)}"
folder = tempfile.TemporaryDirectory()
for name, source in sources:
    dest = Path(folder.name) / name
    dest.write_text(source, encoding="utf-8")
    compile(source, str(dest), "exec")
sys.path.insert(0, folder.name)
import web_engine

def call(action, **kwargs):
    result = json.loads(web_engine.web_call(action, json.dumps(kwargs, ensure_ascii=False)))
    assert result["ok"], f"{action}: {result.get('error')}"
    return result["result"]

def state():
    return call("status")

BASE = dict(operation=6000, market="單球", count=1, parts=2, maxSteps=6,
            planned=35, minBet=1, maxBet=20000, profitPct=1000, lossPct=100)

def begin(code, **kwargs):
    return call("start", **dict(BASE, strategy=code, **kwargs))

def ledger_signature(s):
    return (s["wins"], s["losses"], s["pnl"], s["total_bet"], len(s["ledger"]))

print("CASE 1 #07 3 losses to cooldown")
r = begin(7, cooldownLossCount=3, cooldownResumeWins=2)
initial = r["quote"]["per"]
assert initial > 0 and r["state"]["session_status"] == "active"
for i in range(3):
    r = call("settle", outcome="loss", actionId=f"loss-{i}")
    print(" loss", i+1, r["state"]["session_status"], r["quote"])
assert r["state"]["session_status"] == "paused_cooldown" and r["quote"] is None
before_observe = ledger_signature(r["state"])

print("CASE 2 #07 manual observe win loss win win, exclude ledger")
for outcome, count, status in [("win", 1, "paused_cooldown"),
                               ("loss", 0, "paused_cooldown"),
                               ("win", 1, "paused_cooldown"),
                               ("win", 2, "active")]:
    r = call("observe_cooldown", outcome=outcome)
    assert r["state"]["session_status"] == status, (outcome, r["status"])
    assert r["state"]["cooldown_observe_streak"] == count
    assert ledger_signature(r["state"]) == before_observe
assert r["state"]["plan_state"]["step"] == 0
assert r["quote"] and 0 < r["quote"]["per"] < initial
print(" resumed amount",r["quote"]["per"],"initial",initial)

print("CASE 3 undo observed last win and re-win")
r = call("undo")
assert r["state"]["session_status"] == "paused_cooldown"
assert r["state"]["cooldown_observe_streak"] == 1
assert ledger_signature(r["state"]) == before_observe
r = call("observe_cooldown", outcome="win")
assert r["state"]["session_status"] == "active"
assert ledger_signature(r["state"]) == before_observe

print("CASE 4 stop loss wins over resume")
r = begin(7, cooldownLossCount=3, cooldownResumeWins=2)
for i in range(3):
    r = call("settle", outcome="loss", actionId=f"stop-{i}")
web_engine.STATE["loss_limit"] = -web_engine.STATE["pnl"]
call("observe_cooldown", outcome="win")
r = call("observe_cooldown", outcome="win")
assert r["state"]["session_status"] == "paused_loss" and r["quote"] is None

print("CASE 5 limit blocks resumption")
r = begin(7, cooldownLossCount=3, cooldownResumeWins=2)
for i in range(3):
    r = call("settle", outcome="loss", actionId=f"limit-{i}")
web_engine.STATE["table_min_bet"] = 20000
call("observe_cooldown", outcome="win")
r = call("observe_cooldown", outcome="win")
assert r["state"]["session_status"] == "paused_funds" and r["quote"] is None

print("CASE 6 #07 invalid parameter rejected")
for value in (0, 101, 2.5):
    result = json.loads(web_engine.web_call("validate", json.dumps(dict(BASE, strategy=7,
                                cooldownLossCount=value, cooldownResumeWins=2))))
    assert not result["ok"], (value, result)

print("CASE 7 #99 win/loss branch regression")
r = begin(99, custom_win_sequence=[1,2,3])
assert r["quote"] is not None
r = call("settle", outcome="win", actionId="win-99")
assert r["state"]["wins"] == 1
r = call("settle", outcome="loss", actionId="loss-99")
assert r["state"]["losses"] == 1

print("CASE 8 #06 dual pools win/loss branch regression")
r = begin(6, dualSequence=[1,2])
assert r["quote"] is not None
r = call("settle", outcome="win", actionId="win-06")
assert r["state"]["wins"] == 1
assert r["state"]["dual_cycle_count"] >= 1
r = call("settle", outcome="loss", actionId="loss-06")
assert r["state"]["losses"] == 1

print("ALL ENGINE TESTS PASS")

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


print("CASE 9 #08 1000 reference -> 800/1440/2592 win progression")
r = begin(8, operation=10000, parts=10, givebackLockPercent=20,
          givebackWinMultiplier=1.8, givebackWinSteps=5)
assert r["state"].get("giveback_step_v3") is True
assert r["quote"]["per"] == 800, r["quote"]
assert r["state"]["locked_profit"] == 0
r = call("settle", outcome="win", actionId="8-win-1")
assert r["quote"]["per"] == 1440, r["quote"]
r = call("settle", outcome="win", actionId="8-win-2")
assert r["quote"]["per"] == 2592, r["quote"]
assert r["state"]["locked_profit"] == 0, "new bottom line is not profit locking"

print("CASE 10 #08 any loss -> first stage with progressive 20% reduction")
r = call("settle", outcome="loss", actionId="8-loss-1")
assert r["quote"]["per"] == 640, r["quote"]
assert r["state"]["plan_state"]["step"] == 0
assert r["state"]["giveback_loss_steps"] == 1
r = call("settle", outcome="loss", actionId="8-loss-2")
assert r["quote"]["per"] == 512, r["quote"]
assert r["state"]["giveback_loss_steps"] == 2
r = call("settle", outcome="win", actionId="8-win-3")
assert r["quote"]["per"] == 921, r["quote"]  # floor(512 * 1.8)
r = call("settle", outcome="loss", actionId="8-loss-3")
assert r["quote"]["per"] == 409, r["quote"]  # floor(1000 * 0.8^4)
assert r["state"]["giveback_loss_steps"] == 3

print("CASE 11 #08 max win stages resets step but keeps reduction level")
r = begin(8, operation=10000, parts=10, givebackLockPercent=20,
          givebackWinMultiplier=1.8, givebackWinSteps=3)
for i in range(3):
    r = call("settle", outcome="win", actionId=f"8-cycle-{i}")
assert r["state"]["giveback_cycles"] == 1
assert r["state"]["plan_state"]["step"] == 0
assert r["quote"]["per"] == 800, r["quote"]

print("CASE 12 #08 table min blocks post-loss stage; no fabricated minimum bet")
r = begin(8, operation=10000, parts=10, givebackLockPercent=20,
          givebackWinMultiplier=1.8, givebackWinSteps=5, minBet=700)
assert r["quote"]["per"] == 800
r = call("settle", outcome="loss", actionId="8-table-loss")
assert r["state"]["session_status"] == "paused_funds" and r["quote"] is None
assert r["state"]["losses"] == 1

print("CASE 13 #08 invalid parameters rejected")
for field,value in (("givebackLockPercent",100),("givebackLockPercent",-1),
                    ("givebackWinMultiplier",0.9),("givebackWinMultiplier",21),
                    ("givebackWinSteps",0),("givebackWinSteps",21)):
    cfg = dict(BASE, strategy=8, operation=10000, parts=10, givebackLockPercent=20,
               givebackWinMultiplier=1.8, givebackWinSteps=5)
    cfg[field] = value
    result = json.loads(web_engine.web_call("validate", json.dumps(cfg)))
    assert not result["ok"], (field, value, result)

print("CASE 14 #08 legacy v2 state is unchanged and still locks profit")
r = begin(8, operation=10000, parts=10, givebackLockPercent=20,
          givebackWinMultiplier=1.8, givebackWinSteps=5)
web_engine.STATE.pop("giveback_step_v3", None)
legacy = call("status")
assert legacy["quote"]["per"] == 1000, legacy["quote"]
legacy = call("settle", outcome="win", actionId="8-legacy-win")
assert legacy["state"]["locked_profit"] > 0
assert legacy["state"]["giveback_roll_pool"] > 0
assert legacy["state"].get("giveback_step_v3") is None

print("CASE 15 #07 still resumes; #06 and #99 stayed verified above")
print("ALL ENGINE TESTS PASS INCLUDING #08")


print("CASE 16 #09 fixed-horizon progressive losses and independent UI breakdown")
r=begin(9, operation=10000, parts=2, count=1, planned=5, profitPct=1000)
assert r["state"].get("rounds_budget_v3") is True
assert r["quote"]["per"]==1000, r["quote"]
assert r["roundsBreakdown"]["divisor"]==5 and r["roundsBreakdown"]["completed"]==0
assert r["roundsBreakdown"]["quotedPer"]==r["quote"]["per"]==r["roundsBreakdown"]["theoreticalPer"]
r=call("settle",outcome="loss",actionId="rounds-loss-1")
assert r["quote"]["per"]==800, r["quote"]
assert r["roundsBreakdown"]["localPnl"]==-1000
assert r["roundsBreakdown"]["remaining"]==4
assert r["roundsBreakdown"]["divisor"]==5, "fixed denominator must not shrink"
assert r["roundsBreakdown"]["quotedPer"]==r["quote"]["per"]
r=call("settle",outcome="loss",actionId="rounds-loss-2")
assert r["quote"]["per"]==640, r["quote"]
assert r["roundsBreakdown"]["localPnl"]==-1800
r=call("settle",outcome="win",actionId="rounds-win-3")
assert r["quote"] and r["quote"]["per"]>640, r["quote"]
assert r["roundsBreakdown"]["quotedPer"]==r["quote"]["per"]
assert r["state"]["wins"]==1 and r["state"]["losses"]==2

print("CASE 17 #09 round boundary resets ONLY local pnl/counter")
r=begin(9, operation=6000, parts=2, count=1, planned=3, profitPct=1000)
assert r["quote"]["per"]==1000
for i,expected in enumerate((666,444,1000)):
    r=call("settle",outcome="loss",actionId=f"round-boundary-{i}")
    assert r["quote"] and r["quote"]["per"]==expected,(i,r["quote"],r["status"])
assert r["state"]["round_id"]==2
assert r["roundsBreakdown"]["completed"]==0
assert r["roundsBreakdown"]["localPnl"]==0
assert r["roundsBreakdown"]["referenceShare"]==3000
assert r["state"]["losses"]==3 and r["state"]["wins"]==0
assert r["state"]["pnl"]==-2110
assert r["state"]["total_bet"]==2110
assert r["state"]["round_start_pnl"]==-2110
assert len(r["state"]["ledger"])==3
assert r["state"]["web_batch_total_cap"]>=6, "round cap must not stop next round"
r=call("settle",outcome="loss",actionId="second-round-loss")
assert r["quote"]["per"]==666
assert r["roundsBreakdown"]["completed"]==1
assert r["roundsBreakdown"]["localPnl"]==-1000
assert r["state"]["pnl"]==-3110
assert len(r["state"]["ledger"])==4

print("CASE 18 #09 undo restores first stake and round metadata")
r=begin(9, operation=10000, parts=2, count=1, planned=5, profitPct=1000)
r=call("settle",outcome="loss",actionId="undo09")
assert r["quote"]["per"]==800
r=call("undo")
assert r["quote"]["per"]==1000
assert r["roundsBreakdown"]["localPnl"]==0 and r["roundsBreakdown"]["completed"]==0
assert r["state"]["pnl"]==0 and r["state"]["total_bet"]==0

print("CASE 19 #09 limit and stop loss precedence")
r=begin(9, operation=10000, parts=2, count=1, planned=5, profitPct=1000, minBet=900)
assert r["quote"]["per"]==1000
r=call("settle",outcome="loss",actionId="min-limit09")
assert r["quote"] is None and r["state"]["session_status"]=="paused_funds"
assert r["roundsBreakdown"]["theoreticalPer"]==800
assert r["roundsBreakdown"]["quotedPer"] is None
r=begin(9, operation=10000, parts=2, count=1, planned=5, profitPct=1000, lossPct=10)
r=call("settle",outcome="loss",actionId="stop-loss09")
assert r["quote"] is None and r["state"]["session_status"]=="paused_loss"

print("CASE 20 #09 loaded V2 behavior stays unchanged")
r=begin(9, operation=10000, parts=2, count=1, planned=5, profitPct=1000)
web_engine.STATE.pop("rounds_budget_v3",None)
r=call("status")
assert r["roundsBreakdown"]["formulaVersion"]==2
assert r["quote"]["per"]==1000
r=call("settle",outcome="loss",actionId="legacy09")
assert r["quote"]["per"]==1000, r["quote"]
assert r["roundsBreakdown"]["divisor"]==4
assert r["roundsBreakdown"]["quotedPer"]==1000

print("ALL ENGINE REGRESSIONS PASS INCLUDING #09")

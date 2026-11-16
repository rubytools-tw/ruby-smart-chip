"""One-time read-only audit: all 26 live RUBY Smart Chip embedded Python strategies.

Run against the UNMODIFIED index.html of the audited branch. No web source changes.
Every scenario starts from a clean plan; failures accumulate in audit_result.json.
"""
import copy
import json
import math
import re
import sys
import tempfile
import traceback
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/"index.html").read_text(encoding="utf-8")
MODULES=re.findall(r'<script type="text/plain" id="py-src-([^"]+)">([\s\S]*?)</script>',HTML)
assert len(MODULES)==8,f"Expected 8 embedded modules, got {len(MODULES)}"
TEMP=tempfile.TemporaryDirectory()
for name,code in MODULES:
    file=Path(TEMP.name)/name
    file.write_text(code,encoding="utf-8")
    compile(code,str(file),"exec")
sys.path.insert(0,TEMP.name)
import web_engine as web
import sizing_v180 as sizing
import strategy_engine as strategies

CODES=sorted(strategies.MENU_CODES)
assert len(CODES)==26 and len(set(CODES))==26,CODES
RESULTS=[]
BASE=dict(operation=1000000,market="單球",count=1,parts=10,maxSteps=4,
          planned=8,minBet=1,maxBet=10000000,profitPct=10000,lossPct=100)

def config(code,**changes):
    cfg=dict(BASE,strategy=code)
    extra={
        0:dict(loss_sequence=[1,2,3]),
        99:dict(custom_win_sequence=[1,2,3]),
        66:dict(layerStakes=[[6,12,0,0],[12,36,0,0],[36,180,0,0],[0,0,0,0]]),
        1:dict(peakLockPercent=50,peakLockCount=3),
        6:dict(dualSequence=[1,2]),
        7:dict(cooldownLossCount=3,cooldownResumeWins=2),
        8:dict(givebackLockPercent=20,givebackWinMultiplier=1.8,givebackWinSteps=4),
        9:dict(planned=4),
        10:dict(consensusActivatePercent=10,consensusDrawdownPercent=20,consensusLockPercent=50),
        14:dict(sprintStart=3,sprintMinPct=80,sprintMaxPct=80,maxSteps=4),
        17:dict(maxSteps=5),
        20:dict(attack_sequence=[1,1.6,2,2.6],retreat_sequence=[2,3,5,8],maxSteps=4),
        23:dict(probability=75),
        24:dict(cancel_list=[1,2]),
        26:dict(partsMin=10,partsMax=10),
    }.get(code,{})
    cfg.update(extra)
    cfg.update(changes)
    return cfg

def api(action,**args):
    raw=json.loads(web.web_call(action,json.dumps(args,ensure_ascii=False,allow_nan=False)))
    if not raw["ok"]:raise RuntimeError(f"{action}: {raw.get('error')}")
    return raw["result"]

def raw_api(action,**args):
    return json.loads(web.web_call(action,json.dumps(args,ensure_ascii=False,allow_nan=False)))

def start(code,**kwargs):
    return api("start",**config(code,**kwargs))

def valid_quote(data):
    q=data["quote"]
    assert q is not None,f"Missing quote: {data['status']}"
    s=data["state"]
    assert type(q["per"]) is int and q["per"]>=1,q
    assert q["total"]==q["per"]*q["count"] and q["count"]==s["number_count"],q
    assert q["total"]<=data["available"]+0.01,(q,data["available"])
    assert q["per"]<=s["table_max_bet"] and q["per"]>=s["table_min_bet"],(q,s["table_min_bet"])
    assert q["total"]<=max(0,s["loss_limit"]+s["pnl"])+0.01,(q,s["pnl"],s["loss_limit"])
    # Profit-funded sprint plans (#14/#99) may legally exceed the original
    # allocation budget while staying within current wallet and stop-loss.
    if not (sizing.sid(s) in ("winner","custom_win") and s.get("win_mode_version")==2):
        assert q["total"]<=data["operationBudget"]+0.01,(q,data["operationBudget"])
    return q

def check_ledger(data):
    s=data["state"]; rows=s["ledger"]
    assert len(rows)==s["wins"]+s["losses"],(len(rows),s["wins"],s["losses"])
    assert abs(s["total_bet"]-round(sum(float(x["cost"]) for x in rows),2))<0.02
    assert abs(s["total_return"]-round(sum(float(x["return"]) for x in rows),2))<0.02
    assert abs(s["pnl"]-round(sum(float(x["delta"]) for x in rows),2))<0.02
    assert s["locked_profit"]>=-0.01,s["locked_profit"]
    assert len(rows)==0 or rows[-1]["sequence"]==len(rows)

def mark(code,case,fn):
    name=strategies.BY_CODE[code]["name"] if code in strategies.BY_CODE else "common"
    try:
        detail=fn()
        tag="SKIP" if str(detail or "").startswith("N/A") else "PASS"
        RESULTS.append(dict(code=code,strategy=name,case=case,status=tag,detail=str(detail or "")[:400]))
        print(f"{tag} #{code:02} {case} {str(detail or '')[:100]}",flush=True)
    except Exception as err:
        detail=f"{type(err).__name__}: {err}"
        RESULTS.append(dict(code=code,strategy=name,case=case,status="FAIL",detail=detail,
                            traceback=traceback.format_exc(limit=4)))
        print(f"FAIL #{code:02} {case}: {detail}",flush=True)

def maybe_kelly(code):
    if code==23 and web.STATE.get("kelly_probability") is None:
        api("probability",value=75)

def smoke(code):
    r=start(code)
    assert r["code"]==code,(code,r["code"])
    first=valid_quote(r)
    pre=copy.deepcopy(r["state"])
    id_=f"audit-win-{code}"
    win=api("settle",outcome="win",actionId=id_)
    check_ledger(win)
    assert win["state"]["wins"]==1 and win["state"]["losses"]==0
    assert win["state"]["ledger"][-1]["stake"]==first["per"]
    assert win["state"]["ledger"][-1]["cost"]==first["total"]
    dup=api("settle",outcome="win",actionId=id_)
    assert len(dup["state"]["ledger"])==1,"same actionId recorded twice"
    undone=api("undo")
    assert undone["state"]["wins"]==0 and len(undone["state"]["ledger"])==0
    assert undone["state"]["pnl"]==pre["pnl"] and undone["state"]["total_bet"]==0
    assert undone["state"]["plan_state"]==pre["plan_state"],"undo did not restore plan stage"
    maybe_kelly(code)
    lost=api("settle",outcome="loss",actionId=f"audit-loss-{code}")
    check_ledger(lost)
    assert lost["state"]["losses"]==1
    assert lost["state"]["ledger"][-1]["cost"]==first["total"]
    return f"first={first['per']}, win/idempotent/undo/loss OK"

def sequence(code):
    r=start(code)
    applied=0; terminal=None; progress=[]
    for index,outcome in enumerate(("loss","loss","win","win","loss","win","loss","win")):
        if r["state"]["session_status"]=="paused_cooldown":
            for o in ("win","win"):
                r=api("observe_cooldown",outcome=o)
            assert r["state"]["session_status"] in ("active","paused_funds")
        if r["state"]["session_status"]!="active":
            terminal=r["state"]["session_status"];break
        maybe_kelly(code)
        r=api("status")
        if r["quote"] is None:
            terminal=r["status"];break
        valid_quote(r)
        r=api("settle",outcome=outcome,actionId=f"seq-{code}-{index}")
        check_ledger(r)
        applied+=1
        progress.append((outcome,r["state"]["pnl"],r["state"]["round_id"]))
        if r["state"]["session_status"]=="paused_cooldown":
            before=(r["state"]["wins"],r["state"]["losses"],r["state"]["total_bet"],r["state"]["pnl"])
            for o in ("win","win"):
                r=api("observe_cooldown",outcome=o)
            after=(r["state"]["wins"],r["state"]["losses"],r["state"]["total_bet"],r["state"]["pnl"])
            assert before==after,"observing altered wager ledger"
        if r["state"]["session_status"].startswith("paused"):
            terminal=r["state"]["session_status"];break
    assert applied>=1,(applied,terminal)
    return f"settled={applied}, terminal={terminal}, final={progress[-1] if progress else ''}"

def hard_cap(code):
    r=start(code,planned=2)
    for index in range(2):
        maybe_kelly(code)
        r=api("status")
        valid_quote(r)
        r=api("settle",outcome="loss",actionId=f"cap-{code}-{index}")
    check_ledger(r)
    if code==9:
        assert r["state"]["round_id"]==2 and r["roundsBreakdown"]["completed"]==0
        return "per-round 2-ply rollover allowed as designed"
    assert r["quote"] is None and r["state"]["session_status"]=="paused_round_limit",(
        "plan total limit auto-extended",r["state"]["web_batch_total_cap"],r["state"]["session_status"],
        r["quote"] and r["quote"]["per"])
    return "hard overall plan cap enforced"

def stop_loss(code):
    r=start(code)
    cost=valid_quote(r)["total"]
    web.STATE["loss_limit"]=cost
    # Loss equal to the remaining hard-stop allowance must pause immediately.
    r=api("settle",outcome="loss",actionId=f"stop-{code}")
    assert r["state"]["session_status"]=="paused_loss",r["state"]["session_status"]
    assert r["quote"] is None
    n=len(r["state"]["ledger"])
    e=raw_api("settle",outcome="loss",actionId=f"stop-repeat-{code}")
    assert not e["ok"] and len(web.STATE["ledger"])==n
    return f"cost={cost} blocked further settlement"

def table_limit(code):
    r=start(code)
    stake=valid_quote(r)["per"]
    web.STATE["table_min_bet"]=stake+1
    r=api("status")
    assert r["quote"] is None,(code,stake,r["quote"])
    n=len(r["state"]["ledger"])
    resp=raw_api("settle",outcome="loss",actionId=f"limit-{code}")
    assert not resp["ok"] and len(web.STATE["ledger"])==n
    return f"minimum={stake+1} rejected per={stake}"

def allocation(code,choice):
    r=start(code)
    r=api("settle",outcome="win",actionId=f"{choice}-{code}")
    check_ledger(r)
    if choice=="lock" and not r["canLock"]:return "N/A: strategy disallows manual lock"
    if choice=="roll" and not r["canRoll"]:return "N/A: strategy disallows manual roll"
    if r["allocatable"]<=0 and (choice!="roll" or r["pendingRoll"]<=0):
        return "N/A: no allocatable profit under strategy"
    before=r["state"]; b=r["operationBudget"]
    result=api("choose",choice=choice,percent=25)
    assert result["state"]["pnl"]==before["pnl"],"allocation changed PnL"
    assert result["state"]["wins"]==before["wins"]
    assert len(result["state"]["ledger"])==len(before["ledger"])
    if choice=="lock":
        assert result["state"]["locked_profit"]>before["locked_profit"]
        assert result["operationBudget"]<b
    else:
        assert result["operationBudget"]>b
    # Same round profit must not be allocated repeatedly.
    second=raw_api("choose",choice=choice,percent=25)
    assert not second["ok"],"duplicate allocation on the same profit was accepted"
    return f"{choice} 25%, budget {b}->{result['operationBudget']}"

def finish(code):
    r=start(code)
    api("finish")
    r=api("status")
    assert r["state"]["session_status"]=="settled" and r["quote"] is None
    error=raw_api("settle",outcome="loss",actionId="postfinish-"+str(code))
    assert not error["ok"]
    assert not r["state"]["ledger"]
    return "finish blocks further settlement"

def terminal(code):
    if code not in (0,99,66,14,16,17,18,19,20,22,24,26):
        return "N/A no finite progression or custom lifecycle"
    r=start(code,maxSteps=3 if code not in (14,17,66,26) else 5)
    executed=0
    direction="win" if code in (99,14,24,26) else "loss"
    if code==24:direction="win"
    for k in range(6):
        if r["state"]["session_status"]!="active":break
        maybe_kelly(code)
        r=api("status")
        if not r["quote"]:break
        r=api("settle",outcome=direction,actionId=f"stage-{code}-{k}")
        check_ledger(r);executed+=1
        if r["state"].get("plan_state",{}).get("exhausted") or r["state"].get("plan_state",{}).get("done"):break
        if code==26 and r["state"].get("cycle_number",1)>=2:break
        if code==24 and r["state"].get("round_complete_count",0):break
        if code==14 and r["state"].get("round_complete_count",0):break
    assert executed>=1
    s=r["state"]; pos=s["plan_state"]
    if code==66:
        assert s["session_status"]=="paused_strategy" and pos["exhausted"],s["session_status"]
    if code in (16,17,18,19,22) and pos.get("exhausted"):
        # Mark as blocked, do not synthesize a new bet on the exhausted stage.
        assert r["quote"] is None,(code,r["quote"])
    if code==99 and executed>=3:
        assert pos["step"]==0,"custom_win should return to first stage"
    if code==26 and s.get("cycle_number",1)>=2:
        assert s["locked_profit"]>0 and len(s["cycle_history"])>=1
    return f"action={direction}, played={executed}, status={s['session_status']}, step={pos.get('step')}"

# Real exception injection into a settled-result callback: should leave no partial ledger.
def atomic_failure():
    r=start(11)
    prior=copy.deepcopy(web.STATE)
    old=sizing.after_result
    def failed_after_mutation(s,win,delta):
        raise RuntimeError("AUDIT_FORCED_AFTER_RESULT_EXCEPTION")
    sizing.after_result=failed_after_mutation
    try:
        result=raw_api("settle",outcome="win",actionId="forced-rollback")
    finally:
        sizing.after_result=old
    assert not result["ok"],result
    assert web.STATE==prior,("P0: unsuccessful settlement mutated ledger/pnl/plan",{
        "pnl_before":prior["pnl"],"pnl_after":web.STATE["pnl"],
        "ledger_before":len(prior["ledger"]),"ledger_after":len(web.STATE["ledger"])})
    return "exception rolled back all state"


def legacy_load_cap(code):
    """An old serialized batch may never resurrect a capped 25-strategy plan."""
    r=start(code,planned=2)
    for index in range(2):
        maybe_kelly(code)
        r=api("status")
        valid_quote(r)
        r=api("settle",outcome="loss",actionId=f"backup-{code}-{index}")
    record=copy.deepcopy(r["state"])
    # Simulate an unpatched V0-era backup that stored an auto-extended cap.
    record.update(web_batch_mode=True,web_batch_size=2,web_batch_total_cap=4,
                  round_limit=4,session_status="active",strategy_pause_reason="")
    got=api("load",state=record)
    check_ledger(got)
    assert got["state"]["wins"]+got["state"]["losses"]==2
    if code==9:
        assert got["state"]["web_batch_mode"] is True
        assert got["state"]["web_batch_total_cap"]==4
        assert got["state"]["session_status"]=="active"
        valid_quote(got)
        return "saved #09 2-ply plan continued into next round"
    assert got["state"]["web_batch_mode"] is False
    assert got["state"]["web_batch_total_cap"]==2
    assert got["state"]["session_status"]=="paused_round_limit",got["state"]["session_status"]
    assert got["quote"] is None
    err=raw_api("settle",outcome="loss",actionId=f"backed-up-{code}")
    assert not err["ok"] and len(web.STATE["ledger"])==2
    err=raw_api("resume")
    assert not err["ok"],"restore must not bypass the plan cap"
    return "loaded old auto-extended batch was stopped without deleting ledger"

def evaluation_failure():
    """Even failure after tentative commit must restore exact prior global state."""
    start(11)
    old_state=copy.deepcopy(web.STATE)
    old_undo=copy.deepcopy(web.UNDO)
    old_id=web.LAST_ACTION_ID
    old_eval=web.evaluate_state
    def forced_failure():
        raise RuntimeError("AUDIT_POST_COMMIT_EVALUATION_FAIL")
    web.evaluate_state=forced_failure
    try:
        result=raw_api("settle",outcome="win",actionId="eval-crash")
    finally:
        web.evaluate_state=old_eval
    assert not result["ok"] and "AUDIT_POST_COMMIT" in result["error"],result
    assert web.STATE==old_state and web.UNDO==old_undo and web.LAST_ACTION_ID==old_id
    return "commit/evaluate exception restores state, undo and action ID"

def serialize_failure():
    """The HTTP/JS response boundary must not commit if JSON encoding fails."""
    start(11)
    old_state=copy.deepcopy(web.STATE)
    old_undo=copy.deepcopy(web.UNDO)
    old_id=web.LAST_ACTION_ID
    original_dumps=web.json.dumps
    def fail_on_success(*args,**kwargs):
        payload=args[0] if args else None
        if isinstance(payload,dict) and payload.get("ok") is True:
            raise RuntimeError("AUDIT_RESPONSE_SERIALIZATION_FAIL")
        return original_dumps(*args,**kwargs)
    web.json.dumps=fail_on_success
    try:
        result=json.loads(web.web_call("settle",original_dumps({"outcome":"win","actionId":"serialize-crash"})))
    finally:
        web.json.dumps=original_dumps
    assert not result["ok"] and "AUDIT_RESPONSE" in result["error"],result
    assert web.STATE==old_state and web.UNDO==old_undo and web.LAST_ACTION_ID==old_id
    return "JSON/bridge failure cannot leave committed ledger entries"

def main():
    for code in CODES:
        for label,fn in (
          ("start_win_loss_idempotency_undo",lambda c=code:smoke(c)),
          ("consecutive_results",lambda c=code:sequence(c)),
          ("terminal_stage_or_cycle",lambda c=code:terminal(c)),
          ("configured_round_limit",lambda c=code:hard_cap(c)),
          ("stop_loss_protection",lambda c=code:stop_loss(c)),
          ("table_minimum",lambda c=code:table_limit(c)),
          ("lock_25pct",lambda c=code:allocation(c,"lock")),
          ("roll_25pct",lambda c=code:allocation(c,"roll")),
          ("finish_blocks_settlement",lambda c=code:finish(c)),
          ("restore_old_batch_cap",lambda c=code:legacy_load_cap(c)),
        ):
            mark(code,label,fn)
    mark(-1,"atomic_settlement_failure_injection",atomic_failure)
    mark(-1,"post_commit_evaluation_failure",evaluation_failure)
    mark(-1,"web_json_serialization_failure",serialize_failure)
    totals=dict(Counter(x["status"] for x in RESULTS))
    issues=[x for x in RESULTS if x["status"]=="FAIL"]
    data=dict(base_sha="read from GitHub main at test setup",strategies=len(CODES),
              test_count=len(RESULTS),summary=totals,failures=issues,results=RESULTS)
    out=ROOT/"audit_result.json"
    out.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    print("FULL26 SUMMARY",json.dumps({**totals,"unique_failed_strategies":sorted(set(x["code"] for x in issues))},ensure_ascii=False),flush=True)
    print("FULL26 REPORT",out,flush=True)
    if issues:
        raise SystemExit(f"Found {len(issues)} audit failures; see audit_result.json")
if __name__=="__main__":main()

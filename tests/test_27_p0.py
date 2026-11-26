#!/usr/bin/env python3
"""RUBY Smart Chip #27 P0 — isolated full-engine regression tests."""
import copy
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
PY_FILES = ["strategy_engine.py", "progression.py", "sizing_v180.py", "strategy26.py",
            "stake_guard.py", "stage_limits.py", "release_rules.py", "web_engine.py"]
TEMP = tempfile.TemporaryDirectory(prefix="ruby27_test_")
for name in PY_FILES:
    match = re.search(r'<script type="text/plain" id="py-src-' + re.escape(name) + r'">([\s\S]*?)</script>', HTML)
    if match is None:
        raise AssertionError("Missing embedded Python: " + name)
    code = match.group(1)
    compile(code, name, "exec")
    (Path(TEMP.name) / name).write_text(code, encoding="utf-8")
sys.path.insert(0, TEMP.name)
import web_engine as web
import sizing_v180 as sizing
import progression

def call(name, payload=None):
    result = json.loads(web.web_call(name, json.dumps(payload or {}, ensure_ascii=False)))
    if not result["ok"]:
        raise AssertionError(name + " failed: " + result.get("error", ""))
    return result["result"]

def config(strategy=27, win=None, chase=None, **kw):
    result = {
        "strategy": strategy, "operation": 1000, "parts": 10, "count": 5,
        "maxSteps": len(win or [1, 2, 4, 8, 16, 2, 4, 8]),
        "planned": 35, "market": "單球", "profitPct": 10000, "lossPct": 100,
        "minBet": 1, "maxBet": 20000
    }
    if strategy == 27:
        result["dual_win_sequence"] = win or [1, 2, 4, 8, 16, 2, 4, 8]
        result["dual_loss_sequence"] = chase or [1, 2, 4]
    if strategy == 99:
        result["custom_win_sequence"] = win or [1, 2, 4]
    result.update(kw)
    return result

def begin(cfg=None, *, odds=9.6):
    r = call("start", cfg or config())
    if odds is not None:
        web.STATE["payout_multiplier"] = odds
        web.STATE["payout_cycle_enabled"] = False
    return call("status")

def settle(outcome):
    return call("settle", {"outcome": outcome})

class Test27P0(unittest.TestCase):
    def setUp(self):
        web.STATE = None
        web.UNDO = None
        web.LAST_ACTION_ID = None

    def test_catalog_27_at_bottom(self):
        match = re.search(r'<script type="application/json" id="ruby-strategies-json">([\s\S]*?)</script>', HTML)
        data = json.loads(match.group(1))
        self.assertEqual(len(data), 27)
        self.assertEqual(len({x["code"] for x in data}), 27)
        self.assertEqual(data[-1]["code"], 27)
        self.assertIn("27 套策略中心", HTML)
        self.assertNotIn("26 套策略中心", HTML)

    def test_reference_8_winning_stages(self):
        result = begin()
        expected = [100, 190, 365, 700, 1345, 200, 400, 800]
        pnl_by_win = [92, 266.8, 602.6, 1246.6, 2484, 2668, 3036, 3772]
        total_bet = 0
        for index, amount in enumerate(expected):
            result = call("status")
            quote = result["quote"]
            self.assertEqual(quote["total"], amount, (index, quote))
            self.assertEqual(quote["per"] * 5, amount)
            self.assertLessEqual(amount, quote["dualProtection"]["maxTotal"] + 1e-8)
            self.assertEqual(quote["dualProtection"]["firstTotal"], 100)
            self.assertEqual(quote["multiplier"], [1, 2, 4, 8, 16, 2, 4, 8][index])
            total_bet += amount
            result = settle("win")
            self.assertAlmostEqual(result["state"]["pnl"], pnl_by_win[index], places=2)
        self.assertEqual(result["state"]["total_bet"], 4100)
        self.assertEqual(total_bet, 4100)
        self.assertEqual(result["state"]["pnl"], 3772)
        self.assertEqual(call("status")["quote"]["total"], 100)
        self.assertEqual(result["state"]["plan_state"]["step"], 0)
        self.assertEqual(result["state"]["plan_state"]["dual_cycle_start_pnl"], 3772)

    def test_no_stage_reset_when_reduced(self):
        begin()
        settle("win")
        s=call("status")
        self.assertEqual(s["quote"]["total"], 190)
        self.assertEqual(s["state"]["plan_state"]["step"], 1)
        self.assertEqual(s["state"]["round_id"], 1)

    def test_loss_after_second_wager_preserves_only_100_exposure(self):
        begin()
        settle("win")
        r=settle("loss")
        self.assertEqual(r["state"]["pnl"], -98)
        self.assertEqual(r["state"]["plan_state"]["mode"], "win")
        self.assertEqual(r["state"]["plan_state"]["step"], 0)
        self.assertEqual(r["state"]["plan_state"]["dual_cycle_start_pnl"], -98)
        self.assertEqual(r["quote"]["total"], 100)
        self.assertEqual(r["state"]["wins"],1)
        self.assertEqual(r["state"]["losses"],1)

    def test_all_win_stages_losing_exit_no_breach(self):
        for losing_index in range(1, 8):
            self.setUp()
            begin()
            for _ in range(losing_index):
                settle("win")
            current = call("status")
            start = current["state"]["plan_state"]["dual_cycle_start_pnl"]
            wager = current["quote"]["total"]
            self.assertLessEqual(wager, 100 + current["state"]["pnl"] - start + 1e-8)
            ended = settle("loss")
            self.assertGreaterEqual(ended["state"]["pnl"] - start, -100-1e-8)
            self.assertEqual(ended["state"]["plan_state"]["step"], 0)

    def test_first_loss_switches_to_chase_then_pause_and_resume(self):
        begin()
        self.assertEqual(settle("loss")["state"]["plan_state"]["mode"], "chase")
        second=call("status")
        self.assertEqual(second["quote"]["total"],200)
        self.assertIsNone(second["quote"].get("dualProtection"))
        settle("loss")
        third=call("status")
        self.assertEqual(third["quote"]["total"],400)
        result=settle("loss")
        self.assertEqual(result["state"]["pnl"],-700)
        self.assertEqual(result["state"]["session_status"],"paused_strategy")
        self.assertTrue(result["canResume"])
        restored=call("resume")
        self.assertEqual(restored["state"]["session_status"],"active")
        self.assertEqual(restored["state"]["pnl"],-700)
        self.assertEqual(restored["quote"]["total"],100)
        self.assertEqual(restored["state"]["plan_state"]["mode"],"win")
        self.assertEqual(restored["state"]["plan_state"]["dual_cycle_start_pnl"],-700)

    def test_chase_win_starts_new_profit_baseline(self):
        begin()
        settle("loss")
        self.assertEqual(call("status")["quote"]["total"],200)
        r=settle("win")
        self.assertEqual(r["state"]["plan_state"]["mode"],"win")
        self.assertEqual(r["state"]["plan_state"]["step"],0)
        self.assertEqual(r["state"]["plan_state"]["dual_cycle_start_pnl"],r["state"]["pnl"])
        self.assertEqual(r["quote"]["total"],100)

    def test_lock_profit_reduces_current_cycle_cap(self):
        begin()
        settle("win")
        self.assertEqual(call("status")["quote"]["total"],190)
        after=call("choose",{"choice":"lock","percent":50})
        self.assertEqual(after["state"]["locked_profit"],46)
        q=call("status")["quote"]
        self.assertEqual(q["dualProtection"]["usableGain"],46)
        self.assertEqual(q["dualProtection"]["maxTotal"],146)
        self.assertEqual(q["total"],145)

    def test_rolling_does_not_double_count_profit(self):
        begin()
        settle("win")
        call("choose",{"choice":"roll","percent":100})
        q=call("status")["quote"]
        self.assertEqual(q["dualProtection"]["usableGain"],92)
        self.assertEqual(q["total"],190)

    def test_undo_restores_exact_cycle_and_ledger(self):
        begin()
        settle("win")
        self.assertEqual(call("status")["quote"]["total"],190)
        undone=call("undo")
        self.assertEqual(undone["state"]["pnl"],0)
        self.assertEqual(len(undone["state"]["ledger"]),0)
        self.assertEqual(undone["state"]["plan_state"]["dual_cycle_start_pnl"],0)
        self.assertEqual(undone["quote"]["total"],100)

    def test_restore_round_trip_preserves_cycle(self):
        begin()
        settle("win")
        archived=copy.deepcopy(web.STATE)
        web.STATE=None
        loaded=call("load",{"state":archived,"undo":None})
        self.assertEqual(loaded["quote"]["total"],190)
        self.assertEqual(loaded["state"]["plan_state"]["step"],1)
        self.assertEqual(loaded["state"]["plan_state"]["dual_cycle_start_pnl"],0)

    def test_old_27_backup_uses_conservative_fallback(self):
        begin()
        settle("win")
        legacy=copy.deepcopy(web.STATE)
        del legacy["plan_state"]["dual_cycle_start_pnl"]
        del legacy["plan_state"]["dual_cycle_start_locked"]
        resumed=call("load",{"state":legacy,"undo":None})
        self.assertEqual(resumed["quote"]["total"],190)
        self.assertEqual(resumed["state"]["plan_state"]["step"],1)

    def test_quote_ignores_legacy_cached_overstake(self):
        begin()
        settle("win")
        web.STATE["open_quote"]={"total":9999,"per":1999,"count":5,"rate":9.6}
        q=call("status")["quote"]
        self.assertEqual(q["total"],190)

    def test_batch_change_does_not_reset_cycle(self):
        begin(config(planned=2))
        settle("win")
        after=settle("win")
        self.assertEqual(after["state"]["wins"],2)
        self.assertEqual(after["state"]["web_batch_total_cap"],4)
        self.assertEqual(after["state"]["plan_state"]["step"],2)
        self.assertEqual(after["state"]["plan_state"]["dual_cycle_start_pnl"],0)
        self.assertEqual(after["quote"]["total"],365)

    def test_custom_win_length_1(self):
        begin(config(win=[1]))
        self.assertEqual(call("status")["quote"]["total"],100)
        after=settle("win")
        self.assertEqual(after["state"]["plan_state"]["step"],0)
        self.assertEqual(after["state"]["plan_state"]["dual_cycle_start_pnl"],92)

    def test_custom_win_length_50(self):
        begin(config(win=[1]*50))
        self.assertEqual(web.STATE["max_steps"],50)
        self.assertEqual(call("status")["quote"]["total"],100)
        self.assertEqual(len(web.STATE["dual_win_sequence"]),50)

    def test_custom_chase_length_and_resume(self):
        begin(config(win=[1,3,5],chase=[1,2]))
        settle("loss")
        self.assertEqual(call("status")["quote"]["total"],200)
        r=settle("loss")
        self.assertEqual(r["state"]["session_status"],"paused_strategy")

    def test_win_stage_market_limit_shrinks(self):
        begin()
        settle("win")
        web.STATE["table_max_bet"]=25
        self.assertEqual(call("status")["quote"]["total"],125)

    def test_win_stage_user_extra_cap_shrinks(self):
        begin()
        settle("win")
        web.STATE["extra_caps_enabled"]=True
        web.STATE["stake_cap"]=30
        web.STATE["total_cap"]=130
        self.assertEqual(call("status")["quote"]["total"],130)

    def test_win_stage_stoploss_limit_shrinks(self):
        begin()
        settle("win")
        web.STATE["loss_limit"]=100
        self.assertEqual(call("status")["quote"]["total"],190)
        web.STATE["loss_limit"]=0
        self.assertEqual(call("status")["quote"]["total"],90)

    def test_win_stage_available_balance_shrinks(self):
        begin()
        settle("win")
        web.STATE["session_operation_origin"]=50
        self.assertEqual(call("status")["quote"]["total"],140)

    def test_no_bet_below_integer_minimum(self):
        begin()
        settle("win")
        web.STATE["table_max_bet"]=0
        q=call("status")
        self.assertIsNone(q["quote"])
        self.assertIn("不足每碼1元",q["status"])

    def test_first_quote_not_win_shrunk(self):
        begin()
        self.assertEqual(call("status")["quote"]["total"],100)
        self.assertEqual(call("status")["quote"]["dualProtection"]["maxTotal"],100)

    def test_first_stage_loss_respects_chase_risk_limits(self):
        begin()
        settle("loss")
        web.STATE["table_max_bet"]=20
        response=call("status")
        self.assertIsNone(response["quote"])
        self.assertIn("限紅",response["status"])

    def test_unrelated_99_not_win_shrunk(self):
        cfg=config(strategy=99,win=[1,2,4])
        begin(cfg)
        self.assertEqual(call("status")["quote"]["total"],100)
        settle("win")
        self.assertEqual(call("status")["quote"]["total"],200)

    def test_26_smoke(self):
        begin(config(strategy=26,planned=35),odds=None)
        self.assertIsNotNone(call("status")["quote"])
        self.assertEqual(call("status")["state"]["strategy"],"等分倍盈歸本法")

    def test_engine_python_catalog_27_last(self):
        self.assertEqual(len(__import__("strategy_engine").CATALOG),27)
        self.assertEqual([x["code"] for x in __import__("strategy_engine").CATALOG][-1],27)

if __name__ == "__main__":
    unittest.main(verbosity=2)

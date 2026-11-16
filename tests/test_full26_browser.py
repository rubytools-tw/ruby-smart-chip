"""Playwright smoke test of the real page, form, Pyodide bridge and #07 controls."""
import functools
import http.server
import socketserver
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass
handler = functools.partial(QuietHandler, directory=str(ROOT))
class Server(socketserver.TCPServer):
    allow_reuse_address = True
server = Server(("127.0.0.1", 0), handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
errors = []
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1350, "height": 950}, locale="zh-TW")
    page.on("pageerror", lambda error: errors.append(str(error)))
    print("BROWSER", url, flush=True)
    page.goto(url, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_function("document.querySelector('#engine-status')?.textContent?.includes('已就緒')", timeout=150000)
    page.locator("#create-plan").click()
    page.select_option("#strategy-select", "7")
    page.locator('input[name="operation"]').fill("6000")
    page.locator('input[name="parts"]').fill("2")
    page.locator('input[name="count"]').fill("1")
    page.locator('input[name="planned"]').fill("35")
    page.locator('input[name="profitPct"]').evaluate("(el) => { el.closest('details').open = true; }")
    page.locator('input[name="profitPct"]').fill("1000")
    page.locator('input[name="lossPct"]').fill("100")
    page.locator('input[name="cooldownLossCount"]').fill("3")
    page.locator('input[name="cooldownResumeWins"]').fill("2")
    page.locator("#start-button").click()
    page.wait_for_function("snapshot?.state?.strategy === '連掛冷卻檢核法' && snapshot?.quote?.per > 0", timeout=15000)
    initial = page.evaluate("snapshot.quote.per")
    print("INITIAL",initial,flush=True)
    for i in range(3):
        page.locator("#loss-button").click()
        print("LOSS",i+1,page.evaluate("snapshot.state.session_status"),flush=True)
    assert page.evaluate("snapshot.state.session_status") == "paused_cooldown"
    assert page.locator("#cooldown-observe").is_visible()
    assert page.locator("#loss-button").is_disabled()
    before=page.evaluate("({pnl:snapshot.state.pnl,bet:snapshot.state.total_bet,wins:snapshot.state.wins,losses:snapshot.state.losses,ledger:snapshot.state.ledger.length})")
    for outcome,count in [("win",1),("loss",0),("win",1),("win",2)]:
        page.locator("#cooldown-observe-"+outcome).click()
        assert page.evaluate("snapshot.state.cooldown_observe_streak") == count
        assert page.evaluate("({pnl:snapshot.state.pnl,bet:snapshot.state.total_bet,wins:snapshot.state.wins,losses:snapshot.state.losses,ledger:snapshot.state.ledger.length})") == before
    assert page.evaluate("snapshot.state.session_status")=="active"
    assert not page.locator("#cooldown-observe").is_visible()
    assert page.locator("#loss-button").is_enabled()
    assert page.evaluate("snapshot.state.plan_state.step") == 0
    assert 0 < page.evaluate("snapshot.quote.per") < initial
    print("RECOVERED",page.evaluate("snapshot.quote.per"),flush=True)
    page.locator("#undo-button").click()
    assert page.evaluate("snapshot.state.session_status")=="paused_cooldown"
    assert page.locator("#cooldown-observe").is_visible()
    assert page.evaluate("snapshot.state.cooldown_observe_streak")==1
    page.locator("#cooldown-observe-win").click()
    assert page.evaluate("snapshot.state.session_status")=="active"
    print("BROWSER CASE #08 form/preview and winning/losing sequence",flush=True)
    page.goto(url, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_function("document.querySelector('#engine-status')?.textContent?.includes('已就緒')",timeout=150000)
    page.locator("#create-plan").click()
    page.select_option("#strategy-select", "8")
    page.locator('input[name="operation"]').fill("10000")
    page.locator('input[name="parts"]').fill("10")
    page.locator('input[name="count"]').fill("1")
    page.locator('input[name="planned"]').fill("35")
    page.locator('input[name="profitPct"]').evaluate("(el) => { el.closest('details').open = true; }")
    page.locator('input[name="profitPct"]').fill("1000")
    page.locator('input[name="lossPct"]').fill("100")
    page.locator("#giveback-lock-pct").fill("20")
    page.locator("#giveback-win-mult").fill("1.8")
    page.locator("#giveback-win-steps").fill("5")
    assert page.locator("#giveback-preview").is_visible()
    assert page.locator("#giveback-first-per").text_content() == "800"
    amounts = [row.text_content() for row in page.locator("#giveback-stage-preview .giveback-stage-row").all()]
    assert "800／碼" in amounts[0] and "1,440／碼" in amounts[1] and "2,592／碼" in amounts[2], amounts
    page.locator("#start-button").click()
    page.wait_for_function("snapshot?.state?.giveback_step_v3 === true && snapshot?.quote?.per === 800",timeout=15000)
    for outcome,expected in [("win",1440),("win",2592),("loss",640),("loss",512)]:
        button="#win-button" if outcome=="win" else "#loss-button"
        page.locator(button).click()
        actual=page.evaluate("snapshot?.quote?.per")
        print("08",outcome,actual,flush=True)
        assert actual==expected,(outcome,actual,expected,page.locator("#notice").text_content())
    assert page.evaluate("snapshot.state.plan_state.step")==0
    assert page.evaluate("snapshot.state.giveback_loss_steps")==2
    assert page.evaluate("snapshot.state.locked_profit")==0
    assert page.locator("#giveback-live").is_visible()
    assert "掛後退階 2次" in page.locator("#giveback-live").text_content()
    page.locator("#undo-button").click()
    assert page.evaluate("snapshot.quote.per")==640
    assert page.evaluate("snapshot.state.giveback_loss_steps")==1
    print("BROWSER CASE #09 decline after losses and Python quote-linked formula",flush=True)
    page.goto(url, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_function("document.querySelector('#engine-status')?.textContent?.includes('已就緒')", timeout=150000)
    page.locator("#create-plan").click()
    page.select_option("#strategy-select", "9")
    page.locator('input[name="operation"]').fill("10000")
    page.locator('input[name="parts"]').fill("2")
    page.locator('input[name="count"]').fill("1")
    page.locator('input[name="planned"]').fill("5")
    page.locator('input[name="profitPct"]').evaluate("(el) => { el.closest('details').open = true; }")
    page.locator('input[name="profitPct"]').fill("1000")
    page.locator("#start-button").click()
    page.wait_for_function("snapshot?.state?.rounds_budget_v3 === true && snapshot?.quote?.per === 1000",timeout=15000)
    assert page.locator("#rounds-live").is_visible()
    for outcome,expected,local_pnl,completed in (("loss",800,-1000,1),("loss",640,-1800,2)):
        page.locator("#loss-button").click()
        assert page.evaluate("snapshot?.quote?.per")==expected
        assert page.evaluate("snapshot.roundsBreakdown.localPnl")==local_pnl
        assert page.evaluate("snapshot.roundsBreakdown.completed")==completed
        assert page.evaluate("snapshot.roundsBreakdown.divisor")==5
        assert page.evaluate("snapshot.roundsBreakdown.quotedPer")==expected
        actual_text=page.locator("#rounds-live").text_content()
        assert "floor(" in actual_text and f"{expected}元／碼" in actual_text,actual_text
        print("09 LOSS",completed,expected,actual_text[:130],flush=True)
    page.locator("#undo-button").click()
    assert page.evaluate("snapshot?.quote?.per")==800
    assert page.evaluate("snapshot.roundsBreakdown.completed")==1
    print("BROWSER CASE #09 new round leaves full ledger untouched",flush=True)
    page.goto(url,wait_until="domcontentloaded",timeout=120000)
    page.wait_for_function("document.querySelector('#engine-status')?.textContent?.includes('已就緒')",timeout=150000)
    page.locator("#create-plan").click()
    page.select_option("#strategy-select","9")
    page.locator('input[name="operation"]').fill("6000")
    page.locator('input[name="parts"]').fill("2")
    page.locator('input[name="count"]').fill("1")
    page.locator('input[name="planned"]').fill("3")
    page.locator('input[name="profitPct"]').evaluate("(el) => { el.closest('details').open = true; }")
    page.locator('input[name="profitPct"]').fill("1000")
    page.locator("#start-button").click()
    page.wait_for_function("snapshot?.state?.rounds_budget_v3 === true && snapshot?.quote?.per === 1000",timeout=15000)
    for expected in (666,444,1000):
        page.locator("#loss-button").click()
        assert page.evaluate("snapshot?.quote?.per")==expected
    assert page.evaluate("snapshot.state.round_id")==2
    assert page.evaluate("snapshot.roundsBreakdown.completed")==0
    assert page.evaluate("snapshot.roundsBreakdown.localPnl")==0
    assert page.evaluate("snapshot.state.pnl")==-2110
    assert page.evaluate("snapshot.state.total_bet")==2110
    assert page.evaluate("snapshot.state.ledger.length")==3
    assert "第 2 輪" in page.locator("#strategy-round-count").text_content()
    assert "第2輪" in page.locator("#rounds-live").text_content()
    print("BROWSER CASE #10 activated high-water lock and real A B C bars",flush=True)
    page.goto(url,wait_until="domcontentloaded",timeout=120000)
    page.wait_for_function("document.querySelector('#engine-status')?.textContent?.includes('已就緒')",timeout=150000)
    page.locator("#create-plan").click()
    page.select_option("#strategy-select","10")
    page.locator('input[name="operation"]').fill("10000")
    page.locator('input[name="parts"]').fill("10")
    page.locator('input[name="count"]').fill("1")
    page.locator('input[name="planned"]').fill("35")
    page.locator('input[name="profitPct"]').evaluate("(el) => { el.closest('details').open = true; }")
    page.locator('input[name="profitPct"]').fill("1000")
    page.locator('input[name="lossPct"]').fill("100")
    page.locator('input[name="consensusActivatePercent"]').fill("10")
    page.locator('input[name="consensusDrawdownPercent"]').fill("20")
    page.locator('input[name="consensusLockPercent"]').fill("50")
    page.locator("#start-button").click()
    page.wait_for_function("snapshot?.state?.consensus_v3 === true && snapshot?.quote?.per > 0",timeout=15000)
    assert page.locator("#consensus-live").is_visible()
    def assert_live_bars():
        info=page.evaluate("snapshot.consensusBreakdown")
        actual=page.evaluate("snapshot.quote?.per")
        assert len(info["perCode"])==3
        if actual is not None:
            assert min(info["perCode"])==actual,(info["perCode"],actual)
        biggest=max(1,*info["perCode"])
        for i,k in enumerate(("a","b","c")):
            amount=info["perCode"][i]
            assert f"{amount:,}" in page.locator("#consensus-"+k).text_content()
            displayed=float(page.locator("#consensus-bar-"+k).evaluate("(el)=>parseFloat(el.style.width)"))
            assert abs(displayed-100*amount/biggest)<0.02,(k,displayed,amount,biggest)
            aria=page.locator("#consensus-bar-"+k).locator("..").get_attribute("aria-valuenow")
            assert int(aria)==round(100*amount/biggest)
        return info
    info=assert_live_bars()
    assert info["peakProtectionActive"] is False and info["activationThreshold"]==1000
    assert "高點保護尚未啟動" in page.locator("#consensus-status").text_content()
    for i in range(12):
        page.locator("#win-button").click()
        info=assert_live_bars()
        if info["peakProtectionActive"]:
            break
        assert page.evaluate("snapshot.state.locked_profit")==0
    assert info["peakProtectionActive"] is True
    assert page.evaluate("snapshot.state.locked_profit")>0
    assert "高點保護已啟動" in page.locator("#consensus-status").text_content()
    assert page.locator("#consensus-final").text_content()==f"{page.evaluate('snapshot.quote.per'):,} 元／碼"
    print("BROWSER #10 risk",info["perCode"],"quote",page.evaluate("snapshot.quote.per"),flush=True)
    page.locator("#loss-button").click()
    info=assert_live_bars()
    assert page.evaluate("snapshot.state.session_status")=="active"
    assert len(set(info["perCode"]))>1, "A B C values must diverge after mixed real win/loss results"
    assert min(info["perCode"])==page.evaluate("snapshot.quote.per")
    print("BROWSER #10 DIVERGENT risk",info["perCode"],"quote",page.evaluate("snapshot.quote.per"),flush=True)
    print("ALL-26 BROWSER: starting one real user-interface plan per strategy",flush=True)
    code_list=[0,99,66,1,2,3,4,5,6,7,8,9,10,11,12,13,14,16,17,18,19,20,22,23,24,26]
    rows=[]
    for code in code_list:
        try:
            page.goto(url,wait_until="domcontentloaded",timeout=120000)
            page.wait_for_function("document.querySelector('#engine-status')?.textContent?.includes('已就緒')",timeout=150000)
            opener="#create-plan" if page.locator("#create-plan").is_visible() else "#open-config"
            page.locator(opener).click()
            page.select_option("#strategy-select",str(code))
            page.locator('input[name="operation"]').fill("1000000")
            if code==26:
                page.locator('input[name="partsMin"]').fill("10")
                page.locator('input[name="partsMax"]').fill("10")
            else:
                page.locator('input[name="parts"]').fill("10")
            page.locator('input[name="count"]').fill("1")
            page.locator('input[name="planned"]').fill("8")
            page.locator('input[name="maxBet"]').fill("10000000")
            page.locator('input[name="profitPct"]').evaluate("(el) => { el.closest('details').open = true; }")
            page.locator('input[name="profitPct"]').fill("10000")
            page.locator('input[name="lossPct"]').fill("100")
            if code==23:
                page.locator('input[name="probability"]').fill("75")
            if code==14:
                page.select_option('select[name="sprintStart"]',"3")
            if code==99:
                page.locator('input[name="sequenceInput"]').fill("1,2,3")
            if code==0:
                page.locator('input[name="sequenceInput"]').fill("1,2,3")
            page.locator("#start-button").click(timeout=15000)
            page.wait_for_function(f"snapshot?.code === {code} && snapshot?.state?.strategy && snapshot?.state?.ledger?.length === 0 && snapshot?.quote?.per > 0",timeout=20000)
            before=page.evaluate("({n:snapshot.state.ledger.length,pnl:snapshot.state.pnl,quote:snapshot.quote.per})")
            assert before["n"]==0 and before["quote"]>=1,before
            page.locator("#win-button").click(timeout=15000)
            assert page.evaluate("snapshot.state.wins")==1
            assert page.evaluate("snapshot.state.ledger.length")==1
            assert page.locator("#undo-button").is_enabled()
            page.locator("#undo-button").click(timeout=15000)
            assert page.evaluate("snapshot.state.ledger.length")==0
            assert page.evaluate("snapshot.state.pnl")==0
            assert page.evaluate("snapshot.state.wins")==0
            page.locator("#loss-button").click(timeout=15000)
            assert page.evaluate("snapshot.state.losses")==1
            assert page.evaluate("snapshot.state.ledger.length")==1
            assert page.evaluate("snapshot.state.ledger[0].outcome")=="loss"
            # After a settled loss the UI stake must always be exactly the Python quote.
            available=page.evaluate("snapshot.quote")
            if available:
                assert page.locator("#per-code").text_content()==f"{available['per']:,}",(code,available,page.locator("#per-code").text_content())
            rows.append({"code":code,"status":"PASS","firstPer":before["quote"],
                         "afterLossPer":available["per"] if available else None})
            print(f"BROWSER26 PASS #{code:02d}: {before['quote']} -> {available['per'] if available else 'paused'}",flush=True)
        except Exception as e:
            err=str(e)
            rows.append({"code":code,"status":"FAIL","reason":err[:500]})
            print(f"BROWSER26 FAIL #{code:02d}: {err[:500]}",flush=True)
    import json
    (ROOT/"audit_browser_result.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
    failed=[r for r in rows if r["status"]=="FAIL"]
    print("BROWSER26 SUMMARY",len(rows)-len(failed),"passed",len(failed),"failed",flush=True)
    if failed:
        print("BROWSER26 FAILURES",[(r["code"],r["reason"][:100]) for r in failed],flush=True)
    print("BROWSER P0: total cap and #09 rollover",flush=True)
    for code in (0,26,9):
        page.goto(url,wait_until="domcontentloaded",timeout=120000)
        page.wait_for_function("document.querySelector('#engine-status')?.textContent?.includes('已就緒')",timeout=150000)
        page.locator("#create-plan").click()
        page.select_option("#strategy-select",str(code))
        page.locator('input[name="operation"]').fill("1000000")
        if code==26:
            page.locator('input[name="partsMin"]').fill("10")
            page.locator('input[name="partsMax"]').fill("10")
        else:
            page.locator('input[name="parts"]').fill("10")
        page.locator('input[name="count"]').fill("1")
        page.locator('input[name="planned"]').fill("2")
        page.locator('input[name="maxBet"]').fill("10000000")
        page.locator('input[name="profitPct"]').evaluate("(el)=>{el.closest('details').open=true}")
        page.locator('input[name="profitPct"]').fill("10000")
        page.locator("#start-button").click()
        page.wait_for_function(f"snapshot?.code==={code} && snapshot?.quote?.per>0",timeout=15000)
        for _ in range(2):
            page.locator("#loss-button").click()
        if code==9:
            assert page.evaluate("snapshot.state.round_id")==2
            assert page.evaluate("snapshot.state.session_status")=="active"
            assert page.evaluate("snapshot.quote.per")>0
            print("BROWSER P0 #09 next round active",flush=True)
        else:
            assert page.evaluate("snapshot.state.session_status")=="paused_round_limit"
            assert page.evaluate("snapshot.quote") is None
            assert page.locator("#win-button").is_disabled() and page.locator("#loss-button").is_disabled()
            assert page.locator("#round-count").text_content()=="2 / 2 · #1",page.locator("#round-count").text_content()
            if code!=26:
                # The standard progress bar is the completed plan ratio.
                assert abs(float(page.locator("#progress-text").text_content().rstrip("%"))-100)<0.01
            else:
                # #26 intentionally shows capital-return progress instead.
                capital_pct=float(page.locator("#progress-text").text_content().rstrip("%"))
                assert 0<=capital_pct<=100,capital_pct
            print("BROWSER P0 hard cap",code,flush=True)
    assert not errors,errors
    assert not failed,f"Browser UI failed for {len(failed)} of 26 strategies"
    print("BROWSER E2E ALL 26 STRATEGIES + P0 CAP PASS",flush=True)
    browser.close()
server.shutdown()

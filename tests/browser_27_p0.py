#!/usr/bin/env python3
"""Real mobile Chromium integration: #27 rendering, settlement and safe recovery."""
import json
import subprocess
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent.parent
server=subprocess.Popen(["python","-m","http.server","8879","--bind","127.0.0.1"],
                        cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT)
try:
    time.sleep(1)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        page=browser.new_page(viewport={"width":390,"height":844},device_scale_factor=2,
                             is_mobile=True,has_touch=True)
        errors=[]
        page.on("pageerror",lambda e:errors.append(str(e)))
        page.goto("http://127.0.0.1:8879/",wait_until="domcontentloaded",timeout=30000)
        page.wait_for_function("typeof callPython==='function' && !!document.querySelector('#strategy-select option[value=\"27\"]')",timeout=120000)
        assert page.locator("#strategy-select option").count()==27
        assert page.locator("#strategy-select option").last.get_attribute("value")=="27"
        assert page.locator("#view-strategies .drawer-head").inner_text().find("27 套策略中心")>=0
        cfg={"strategy":27,"operation":1000,"parts":10,"count":5,"maxSteps":8,"planned":35,
             "market":"單球","profitPct":10000,"lossPct":100,"minBet":1,"maxBet":20000,
             "dual_win_sequence":[1,2,4,8,16,2,4,8],"dual_loss_sequence":[1,2,4]}
        started=page.evaluate("(cfg)=>run('start',cfg)",cfg)
        assert started["quote"]["total"]==100,started
        page.evaluate("""() => {
            python.runPython("import web_engine; web_engine.STATE['payout_multiplier']=9.6; web_engine.STATE['payout_cycle_enabled']=False");
            run('status');
        }""")
        expected=[100,190,365,700,1345,200,400,800]
        for amount in expected:
            view=page.evaluate("() => ({quote:snapshot.quote, stage:snapshot.state.plan_state.step})")
            assert view["quote"]["total"]==amount,(amount,view)
            assert "dualProtection" in view["quote"]
            assert view["quote"]["total"]<=view["quote"]["dualProtection"]["maxTotal"]
            page.locator("#win-button").click()
            page.wait_for_function("(expected)=>snapshot?.state?.wins===expected",expected=expected.index(amount)+1)
        final=page.evaluate("() => ({pnl:snapshot.state.pnl,bet:snapshot.state.total_bet,quote:snapshot.quote,status:document.querySelector('#notice').textContent})")
        assert final["pnl"]==3772,final
        assert final["bet"]==4100,final
        assert final["quote"]["total"]==100,final
        assert "勝進保本" in final["status"],final
        # A new test plan is safe to replace without the UI confirmation since
        # this explicit test invokes the engine rather than user interaction.
        page.evaluate("(cfg)=>run('start',cfg)",cfg)
        page.locator("#loss-button").click()
        page.wait_for_function("snapshot?.state?.plan_state?.mode==='chase'")
        page.locator("#loss-button").click()
        page.wait_for_function("snapshot?.state?.losses===2")
        page.locator("#loss-button").click()
        page.wait_for_function("snapshot?.state?.session_status==='paused_strategy'")
        assert page.locator("#resume-button").is_visible()
        page.locator("#resume-button").click()
        page.wait_for_function("snapshot?.state?.session_status==='active' && snapshot?.state?.plan_state?.mode==='win'")
        assert page.evaluate("snapshot.quote.total")==100
        assert not errors,errors
        print("MOBILE CHROMIUM #27: EIGHT WIN STAGES, CAP VISIBLE, THREE-LOSS CHASE, MAIN RESUME: PASS")
        browser.close()
finally:
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()

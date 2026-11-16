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
    assert not errors, errors
    print("BROWSER E2E PASS",flush=True)
    browser.close()
server.shutdown()

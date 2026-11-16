"""Browser smoke tests for the 26-source strategy guide UI.

Verify intro, detail/summary toggles, parameter tooltip, and core Pyodide boot.
"""
import functools
import http.server
import socketserver
import threading
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/"index.html").read_text(encoding="utf-8")
match=re.search(r'<script type="application/json" id="ruby-strategies-json">([\s\S]*?)</script>',html)
assert match,"no strategy catalog"
catalog=json.loads(match.group(1))
assert len(catalog)==26
codes=[i["code"] for i in catalog]
assert len(set(codes))==26
for guide in catalog:
    for name in ("description","win","loss","stop"):
        assert 9<=len(guide[name])<=105,(guide["code"],name,guide.get(name))

handler=functools.partial(http.server.SimpleHTTPRequestHandler,directory=str(ROOT))
class Server(socketserver.TCPServer):
    allow_reuse_address=True
server=Server(("127.0.0.1",0),handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
url=__import__("os").environ.get("RUBY_PUBLIC_SITE_URL") or f"http://127.0.0.1:{server.server_address[1]}/index.html"
errors=[]
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
    page=browser.new_page(viewport={"width":1350,"height":950},locale="zh-TW")
    page.on("pageerror",lambda e: errors.append(str(e)))
    page.goto(url,wait_until="domcontentloaded",timeout=120000)
    if __import__("os").environ.get("RUBY_PUBLIC_SITE_URL"):
        live_data=json.loads(page.evaluate("document.getElementById('ruby-strategies-json')?.textContent || '[]'"))
        assert len(live_data)==26,"Live site did not load 26 strategies"
        assert next(x["description"] for x in live_data if x["code"]==7)=="連掛達門檻先冷卻；觀察連中後再恢復配注。"
        assert next(x["description"] for x in live_data if x["code"]==8)=="先按底線降低起注；中獎勝進，掛後再降起注。"
        assert next(x["description"] for x in live_data if x["code"]==9)=="把預算分到每輪固定局數，每局依本輪盈虧重算。"
        assert next(x["description"] for x in live_data if x["code"]==10)=="A 獲利、B 回撤、C 波動各算一注，取最低金額。"
        assert "s=copy.deepcopy(before)" in page.evaluate("document.getElementById('py-src-web_engine.py')?.textContent || ''"),"Live site lost P0 engine"
        print("LIVE GITHUB PAGES GUIDE AND P0 SOURCE VERIFIED",page.url,flush=True)
    page.wait_for_function("document.querySelector('#engine-status')?.textContent?.includes('已就緒')",timeout=150000)
    page.locator("#open-strategies").click()
    page.wait_for_selector("#view-strategies.open",timeout=15000)
    cards=page.locator("#strategy-grid .strategy-card")
    assert cards.count()==26, cards.count()
    for i,guide in enumerate(catalog):
        card=cards.nth(i)
        assert card.locator(".strategy-code").inner_text()==f"#{guide['code']:02d}"
        assert card.locator("p").first.inner_text()==guide["description"]
        details=card.locator("details.strategy-guide")
        assert details.count()==1 and details.get_attribute("open") is None
        assert details.locator("summary").inner_text()=="查看中／掛／停止規則"
        details.locator("summary").click()
        assert details.get_attribute("open") is not None
        lines=details.locator(".guide-line")
        assert lines.count()==3,(guide["code"],lines.count())
        for j,(label,key) in enumerate((("中","win"),("掛","loss"),("停止","stop"))):
            assert lines.nth(j).locator("b").inner_text()==label
            assert lines.nth(j).locator("span").inner_text()==guide[key]
        details.locator("summary").click()
        assert details.get_attribute("open") is None
    print("GUIDE CARDS 26/26 PASS",flush=True)

    page.locator("#strategy-search").fill("連掛冷卻")
    assert page.locator("#strategy-grid .strategy-card").count()==1
    assert page.locator("#strategy-grid .strategy-code").inner_text()=="#07"
    page.locator("#strategy-grid button.text-btn").click()
    page.wait_for_selector("#drawer-config.open",timeout=15000)
    assert page.locator("#strategy-select").input_value()=="7"
    info=page.locator("#strategy-hint").get_attribute("data-info")
    assert "玩法：" in info and "中：" in info and "掛：" in info and "停止：" in info
    assert "觀察連中" in info and "手動恢復只重置" not in info
    # The calculator tab can be hidden while the settings drawer is open.
    # Verify text state without requiring both views to be visible at once.
    assert page.locator("#current-summary").text_content()==next(x["description"] for x in catalog if x["code"]==7)
    assert "觀察連中" in page.locator("#summary-info").get_attribute("data-info")
    print("GUIDE SEARCH, SELECT, SUMMARY AND HINT PASS",flush=True)

    for code,banned in ((8,"獲利保底勝進滾利"),(9,"本輪剩餘局數"),(10,"曾有正獲利高點後才")):
        page.select_option("#strategy-select",str(code))
        guide=next(x for x in catalog if x["code"]==code)
        info=page.locator("#strategy-hint").get_attribute("data-info")
        assert guide["description"] in info and guide["win"] in info
        assert banned not in info
    print("GUIDE #07-#10 NEW COPY VERIFIED",flush=True)

    assert not errors,errors
    browser.close()
server.shutdown()
print("STRATEGY GUIDE E2E PASS",flush=True)

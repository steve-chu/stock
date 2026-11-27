"""手機版每個功能都點一次（主版本＋貝貝版）。"""
import json
import os
import re

import pytest

from helpers import stock_ids
from ui import enter_bb, is_chromium, touch_drag


def open_list(page, url):
    page.goto(url)
    page.locator("#watchlist li[data-id]").first.wait_for(timeout=15000)
    page.wait_for_timeout(400)


def open_stock(page, sid):
    page.locator(f'#watchlist li[data-id="{sid}"]').click()
    page.wait_for_function("document.body.classList.contains('m-stock')")
    page.wait_for_function(f"document.getElementById('sym-id')?.textContent.includes('{sid}') || document.getElementById('sym-name')?.textContent.length > 0")
    page.wait_for_timeout(600)


# ---------------- 主版本 ----------------

def test_list_open_tabs_back(phone, base_url):
    ctx, pg, errs = phone()
    open_list(pg, base_url)
    assert pg.locator("#watchlist li[data-id]").count() == len(stock_ids())
    assert "m-list" in pg.evaluate("document.body.className")
    for sid in stock_ids()[:4]:
        open_stock(pg, sid)
        for tab in ("fund", "tech", "hold"):
            pg.locator(f'#tabs button[data-tab="{tab}"]').click()
            assert pg.locator(f"#tab-{tab}").inner_text().strip(), f"{sid} {tab} 是空的"
        for tf in ("W", "M", "D"):
            pg.locator(f'#tfs button[data-tf="{tf}"]').click()
            pg.wait_for_timeout(250)
        pg.locator(".m-back").click()
        pg.wait_for_function("document.body.classList.contains('m-list')")
    assert pg.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), "畫面左右超出"
    assert not errs, errs


def test_modes_and_splitter(phone, base_url):
    ctx, pg, errs = phone()
    open_list(pg, base_url)
    open_stock(pg, stock_ids()[0])
    for m, chart_vis, side_vis in (("chart", True, False), ("text", False, True), ("split", True, True)):
        pg.locator(f'.m-mode [data-mode="{m}"]').click()
        pg.wait_for_timeout(300)
        cx = pg.locator(".chart-col").bounding_box()
        assert (cx["x"] >= 0) == chart_vis, f"{m}：K 線顯示不對"
        assert pg.locator(".analysis").is_visible() == side_vis, f"{m}：看板顯示不對"
    # 分頁固定在看板頂端
    pg.evaluate("document.querySelector('.analysis').scrollTop = 1500")
    t, a = pg.locator(".tabs").bounding_box(), pg.locator(".analysis").bounding_box()
    assert abs(t["y"] - a["y"]) < 2, "捲動看板時分頁要固定在上面"
    if is_chromium(pg):
        b = pg.locator(".m-split").bounding_box()
        pg.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
        pg.mouse.down(); pg.mouse.move(b["x"] + b["width"] / 2, b["y"] + 120, steps=6); pg.mouse.up()
        assert pg.evaluate("localStorage.getItem('kp.m.ratio.P')"), "拖完比例要記住"
    assert not errs, errs


def test_landscape_side_by_side(phone, base_url):
    ctx, pg, errs = phone()
    open_list(pg, base_url)
    open_stock(pg, stock_ids()[0])
    pg.set_viewport_size({"width": 844, "height": 390})
    pg.wait_for_timeout(700)
    c, s = pg.locator(".chart-col").bounding_box(), pg.locator(".side").bounding_box()
    assert c["x"] < s["x"] and abs(c["y"] - s["y"]) < 30, "橫放要左右並排"
    assert pg.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    pg.set_viewport_size({"width": 390, "height": 664})
    pg.wait_for_timeout(700)
    c, s = pg.locator(".chart-col").bounding_box(), pg.locator(".side").bounding_box()
    assert c["y"] < s["y"], "轉回直放要上下排"
    assert not errs, errs


def test_trades_and_form(phone, base_url):
    ctx, pg, errs = phone()
    open_list(pg, base_url)
    sid = stock_ids()[0]
    open_stock(pg, sid)
    pg.locator('.m-mode [data-mode="text"]').click()
    pg.locator('#tabs button[data-tab="hold"]').click()
    d, p = pg.locator("#t-date").bounding_box(), pg.locator("#t-price").bounding_box()
    assert d["x"] + d["width"] <= p["x"] + 1 and abs(d["height"] - p["height"]) < 2, "日期和成交價的框重疊或不等高"
    pg.fill("#t-date", "2026-01-05"); pg.fill("#t-price", "1000"); pg.fill("#t-qty", "2")
    pg.locator("#trade-form [type=submit]").click()
    pg.wait_for_function("document.getElementById('tab-hold').innerText.includes('損益兩平')")
    pg.locator('#side-seg button[data-side="sell"]').click()
    pg.fill("#t-date", "2026-01-06"); pg.fill("#t-price", "1100"); pg.fill("#t-qty", "5")
    pg.locator("#trade-form [type=submit]").click()
    pg.wait_for_timeout(400)
    assert "超過" in pg.inner_text("#t-msg"), "賣超過持有要被擋"
    stored = json.loads(pg.evaluate("localStorage.getItem('kp.m.trades')"))
    assert len(stored) == 1 and stored[0]["shares"] == 2000
    pg.locator(".m-back").click()
    assert "持" in pg.inner_text(f'li[data-id="{sid}"]'), "有持股的要標「持」"
    open_stock(pg, sid)
    pg.locator('#tabs button[data-tab="hold"]').click()
    pg.locator("[data-del]").first.click()
    pg.wait_for_timeout(600)
    assert json.loads(pg.evaluate("localStorage.getItem('kp.m.trades')")) == []
    assert not errs, errs


def test_backtest_markers_tables_fit(phone, base_url):
    ctx, pg, errs = phone()
    open_list(pg, base_url)
    sid = [s for s in stock_ids() if not s.startswith("00")][0]
    open_stock(pg, sid)
    pg.locator('.m-mode [data-mode="text"]').click()
    pg.locator('#tabs button[data-tab="tech"]').click()
    pg.evaluate("document.querySelector('details.fold[data-k=lbt]').open = true")
    pg.locator("#lbt-one").click()
    pg.locator(".lbt-wrap table").first.wait_for(timeout=10000)
    if pg.locator(".lbt-mark").count():
        pg.locator(".lbt-mark").first.click()
        pg.wait_for_timeout(500)
    pg.locator("#lbt-all").click()
    pg.wait_for_timeout(1500)
    # 表格要縮到看得完（最小縮到 6 成）
    bad = pg.evaluate("""[...document.querySelectorAll('.analysis table')].filter(t => t.offsetParent)
        .filter(t => t.getBoundingClientRect().width > t.parentElement.getBoundingClientRect().width * 1.01 && (+t.style.zoom || 1) > .61).length""")
    assert bad == 0, "有表格太寬又沒縮小"
    assert not errs, errs


def test_gestures_remove_star_reorder(phone, base_url):
    ctx, pg, errs = phone()
    if not is_chromium(pg):
        pytest.skip("觸控手勢只有 chromium 能模擬")
    open_list(pg, base_url)
    ids = stock_ids()

    def row(sid):
        pg.locator(f'li[data-id="{sid}"]').scroll_into_view_if_needed()
        pg.wait_for_timeout(200)
        b = pg.locator(f'li[data-id="{sid}"]').bounding_box()
        return b["x"] + 60, b["y"] + b["height"] / 2

    # 左滑移除（不在長期名單 → 直接移除）
    plain = pg.evaluate("[...document.querySelectorAll('#watchlist li[data-id]')].find(li => !li.querySelector('.cstar'))?.dataset.id")
    touch_drag(pg, *row(plain), -140, 0)
    pg.locator(f'li[data-id="{plain}"] [data-rm]').click()
    pg.wait_for_timeout(800)
    assert pg.locator(f'li[data-id="{plain}"]').count() == 0
    # 長期名單（★）的要先確認
    core = pg.evaluate("[...document.querySelectorAll('#watchlist li[data-id]')].find(li => li.querySelector('.cstar'))?.dataset.id")
    touch_drag(pg, *row(core), -140, 0)
    pg.locator(f'li[data-id="{core}"] [data-rm]').click()
    pg.locator(".m-dlg").wait_for()
    pg.locator('.m-dlg [data-a="0"]').click()
    assert pg.locator(f'li[data-id="{core}"]').count() == 1
    # 加回
    pg.locator(".m-restore").click()
    pg.locator(f'[data-back="{plain}"]').click()
    if pg.locator(".m-dlg [data-close]").count():   # 加回最後一檔時對話框會自己關
        pg.locator(".m-dlg [data-close]").click()
    pg.wait_for_timeout(1200)
    assert pg.locator(f'li[data-id="{plain}"]').count() == 1
    # 右滑加 ★
    assert not pg.locator(f'li[data-id="{plain}"] .cstar').count()
    touch_drag(pg, *row(plain), 150, 0)
    pg.wait_for_timeout(1500)
    assert pg.locator(f'li[data-id="{plain}"] .cstar').count() == 1, "右滑要加入 ★"
    # 按住拖曳排序
    pg.evaluate("window.scrollTo(0, 0)")
    pg.wait_for_timeout(200)
    first = pg.evaluate("document.querySelector('#watchlist li[data-id]').dataset.id")
    x, y = row(first)
    h = pg.locator(f'li[data-id="{first}"]').bounding_box()["height"]
    touch_drag(pg, x, y, 0, h * 2.6, hold_ms=550)
    pg.wait_for_timeout(1200)
    order = pg.evaluate("[...document.querySelectorAll('#watchlist li[data-id]')].map(li => li.dataset.id)")
    assert order.index(first) >= 2, f"排序沒動：{order[:5]}"
    pg.reload()
    pg.locator("#watchlist li[data-id]").first.wait_for()
    pg.wait_for_timeout(500)
    assert pg.evaluate("[...document.querySelectorAll('#watchlist li[data-id]')].map(li => li.dataset.id)")[:5] == order[:5], "重開後順序要還在"
    # 一般捲動不能誤觸拖曳
    touch_drag(pg, x, 500, 0, -200, steps=6)
    assert not pg.locator(".wl li.m-drag").count()
    assert not errs, errs


def test_add_stock_via_relay(phone, base_url, relay_url, built):
    if not relay_url:
        pytest.skip("沒有設定中繼站")
    ctx, pg, errs = phone()
    src = stock_ids()[0]
    data = os.path.join(built, "site", "data")
    pool = set(stock_ids())
    names = json.load(open(os.path.join(data, "names.json"), encoding="utf-8"))
    new = [r for r in names if r[0] not in pool and re.fullmatch(r"\d{4}", r[0])][:2]
    calls = {"add": [], "status": 0}

    def fake(sid, path):   # 用一檔現有的資料假裝是新加的那檔
        rel = path.replace(sid, src)
        if rel.startswith("quote/"):
            q = next(x for x in json.load(open(os.path.join(data, "watchlist.json"), encoding="utf-8"))["quotes"] if x["stock_id"] == src)
            obj = q
        else:
            obj = json.load(open(os.path.join(data, rel), encoding="utf-8"))
        s = json.dumps(obj, ensure_ascii=False).replace(f'"{src}"', f'"{sid}"')
        return s

    def handler(route):
        u = route.request.url[len(relay_url):]
        if u.startswith("/add"):
            calls["add"].append(json.loads(route.request.post_data)["id"])
            return route.fulfill(json={"status": "pending"}, headers={"Access-Control-Allow-Origin": "*"})
        if u.startswith("/status"):
            calls["status"] += 1
            ids = re.search(r"ids=([^&]+)", u).group(1).split(",")
            st = "ready" if calls["status"] >= 3 else "running"
            return route.fulfill(json={"jobs": {i: {"status": st} for i in ids}, "busy": True}, headers={"Access-Control-Allow-Origin": "*"})
        m = re.match(r"/file/(.+)", u)
        if m and calls["status"] >= 3:
            sid = re.search(r"(\d{4})", m.group(1)).group(1)
            return route.fulfill(body=fake(sid, m.group(1)), content_type="application/json", headers={"Access-Control-Allow-Origin": "*"})
        route.fulfill(status=404, json={"error": "not found"}, headers={"Access-Control-Allow-Origin": "*"})

    pg.route(relay_url + "/**", handler)
    open_list(pg, base_url)
    n0 = pg.locator("#watchlist li[data-id]").count()
    pg.locator(".m-add").click()
    for sid, nm, _ in new:
        pg.fill(".m-search", sid)
        pg.locator(f'[data-add="{sid}"]').click()
        pg.wait_for_timeout(400)
    pg.locator(".m-dlg [data-close]").click()
    assert calls["add"] == [r[0] for r in new]
    pg.locator(".m-pill:not([hidden])").wait_for()
    assert all(r[0] in pg.inner_text(".m-pill") for r in new), "底部要列出下載中的股票"
    assert pg.locator("#watchlist li[data-id]").count() == n0 + 2
    pg.locator(f'li[data-id="{new[0][0]}"]').click()   # 下載中點了不能進去
    assert "m-list" in pg.evaluate("document.body.className")
    pg.locator(".m-pill").wait_for(state="hidden", timeout=30000)
    for sid, nm, _ in new:
        assert re.search(r"\d", pg.inner_text(f'li[data-id="{sid}"]').split(sid)[-1]), "下載好要有股價"
    open_stock(pg, new[0][0])
    pg.locator('#tabs button[data-tab="tech"]').click()
    assert pg.inner_text("#tab-tech").strip()
    assert not errs, errs


def test_auto_update_reload_once(phone, base_url):
    ctx, pg, errs = phone()
    navs = []
    pg.route("**/data/version.json*", lambda r: r.fulfill(json={"v": "209912312359"}))
    pg.on("request", lambda r: r.resource_type == "document" and "?v=" in r.url and navs.append(r.url))
    open_list(pg, base_url)
    pg.wait_for_timeout(2500)
    assert len(navs) == 1, f"有新版要自動重新載入「一次」，不能一直重載：{navs}"
    assert "?v=" not in pg.url, "網址上的 ?v= 要清掉"


# ---------------- 貝貝版 ----------------

def test_bb_gift_page_in_browser(phone, base_url):
    ctx, pg, errs = phone()
    pg.goto(base_url + "bb/")
    pg.locator(".bb-gift").wait_for()
    assert pg.locator(".bb-splash").count() == 0 and pg.locator(".bb-photo").count() == 0, "瀏覽器裡不能先看到照片"
    assert "加入主畫面" in pg.inner_text(".bb-gift")
    assert not errs, errs


def test_bb_line_inapp_browser(phone, base_url, pw):
    ua = pw.devices["iPhone 13"]["user_agent"] + " Line/14.0.0"
    ctx, pg, errs = phone(user_agent=ua)
    pg.goto(base_url + "bb/")
    pg.locator(".bb-copy").wait_for()
    assert "Safari" in pg.inner_text(".bb-gift")


def test_bb_splash_loyalty_relaunch(phone, base_url):
    ctx, pg, errs = phone(standalone=True)
    pg.goto(base_url + "bb/")
    pg.locator(".bb-photo").wait_for()
    pg.wait_for_timeout(3500)
    assert pg.locator(".bb-splash").count() == 1, "沒點不能自己跳走"
    assert pg.inner_text(".bb-skip") == "Tap to continue"
    pg.locator(".bb-splash").click()
    pg.locator(".bb-no").wait_for()
    pg.wait_for_timeout(300)
    W, H = pg.evaluate("[innerWidth, innerHeight]")
    for i in range(1, 6):
        before = pg.locator(".bb-no").bounding_box()
        pg.locator(".bb-no").dispatch_event("pointerdown")
        pg.wait_for_timeout(550)
        yb = pg.locator(".bb-yes").bounding_box()
        assert yb["x"] >= -1 and yb["x"] + yb["width"] <= W + 1 and yb["y"] + yb["height"] <= H + 1, "Yes 跑出螢幕"
        if i < 5:
            nb = pg.locator(".bb-no").bounding_box()
            assert (round(nb["x"]), round(nb["y"])) != (round(before["x"]), round(before["y"])), "No 要移開"
            assert nb["x"] >= -1 and nb["x"] + nb["width"] <= W + 1, "No 跑出螢幕"
            overlap = not (nb["x"] + nb["width"] <= yb["x"] or yb["x"] + yb["width"] <= nb["x"] or nb["y"] + nb["height"] <= yb["y"] or yb["y"] + yb["height"] <= nb["y"])
            assert not overlap, "Yes 和 No 疊在一起"
    assert "be faithful" in pg.inner_text(".bb-q-msg").lower()
    assert "gone" in pg.get_attribute(".bb-no", "class")
    pg.locator(".bb-yes").click()
    pg.locator(".bb-splash").wait_for(state="detached", timeout=5000)
    assert pg.locator("#watchlist li[data-id]").count() == len(stock_ids())
    # 關掉馬上再開：一樣要有開場
    pg2 = ctx.new_page()
    pg2.goto(base_url + "bb/")
    pg2.locator(".bb-photo").wait_for(timeout=8000)
    assert not errs, errs


def test_bb_texts_and_separate_storage(phone, base_url):
    ctx, pg, errs = phone(standalone=True)
    pg.goto(base_url + "bb/")
    enter_bb(pg)
    assert pg.inner_text(".brand > span").strip() == "貝貝看盤台"
    assert "貝貝自選股" in pg.inner_text(".watch-head h2")
    open_stock(pg, stock_ids()[0])
    assert "貝貝自選股" in pg.inner_text(".m-back")
    assert pg.inner_text('#tabs [data-tab="hold"]') == "貝貝的持股"
    pg.locator('.m-mode [data-mode="text"]').click()
    pg.locator('#tabs button[data-tab="hold"]').click()
    pg.fill("#t-date", "2026-01-05"); pg.fill("#t-price", "1000"); pg.fill("#t-qty", "1")
    pg.locator("#trade-form [type=submit]").click()
    pg.wait_for_timeout(600)
    keys = pg.evaluate("(()=>{const o=[];for(let i=0;i<localStorage.length;i++)o.push(localStorage.key(i));return o})()")
    assert any(k == "bb:kp.m.trades" for k in keys), keys
    assert not any(k.startswith("kp.") for k in keys), f"貝貝版的紀錄要和主版本分開：{keys}"
    # 主版本看不到貝貝的持股
    main = ctx.new_page()
    main.goto(base_url)
    main.locator("#watchlist li[data-id]").first.wait_for()
    assert main.evaluate("localStorage.getItem('kp.m.trades')") in (None, "[]")
    assert not errs, errs


def test_bb_landscape_and_overflow(phone, base_url):
    ctx, pg, errs = phone(standalone=True)
    pg.goto(base_url + "bb/")
    enter_bb(pg)
    assert pg.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    open_stock(pg, stock_ids()[0])
    pg.set_viewport_size({"width": 844, "height": 390})
    pg.wait_for_timeout(700)
    c, s = pg.locator(".chart-col").bounding_box(), pg.locator(".side").bounding_box()
    assert c["x"] < s["x"]
    assert not errs, errs


# ---------------- 媽媽版 ----------------

def test_mom_install_page_in_browser(phone, base_url):
    ctx, pg, errs = phone()
    pg.goto(base_url + "mom/")
    pg.locator(".mom-install").wait_for()
    t = pg.inner_text(".mom-install")
    assert "加入主畫面" in t and "看盤台" in t
    assert pg.locator(".mom-icon").evaluate("i => i.complete && i.naturalWidth > 0"), "圖示要載得出來"
    assert pg.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    assert not errs, errs


def test_mom_line_inapp_browser(phone, base_url, pw):
    ctx, pg, errs = phone(user_agent=pw.devices["iPhone 13"]["user_agent"] + " Line/14.0.0")
    pg.goto(base_url + "mom/")
    pg.locator(".mom-copy").wait_for()
    assert "Safari" in pg.inner_text(".mom-install")


def test_mom_app_works_and_storage_separate(phone, base_url):
    ctx, pg, errs = phone(standalone=True)
    open_list(pg, base_url + "mom/")
    assert pg.locator(".mom-install").count() == 0, "從主畫面打開不能再出現安裝說明"
    assert pg.locator("#watchlist li[data-id]").count() == len(stock_ids())
    sid = stock_ids()[0]
    open_stock(pg, sid)
    pg.locator('.m-mode [data-mode="text"]').click()
    pg.locator('#tabs button[data-tab="hold"]').click()
    pg.fill("#t-date", "2026-01-05"); pg.fill("#t-price", "1000"); pg.fill("#t-qty", "1")
    pg.locator("#trade-form [type=submit]").click()
    pg.wait_for_timeout(600)
    keys = pg.evaluate("(()=>{const o=[];for(let i=0;i<localStorage.length;i++)o.push(localStorage.key(i));return o})()")
    assert "mom:kp.m.trades" in keys and not any(k.startswith(("kp.", "bb:")) for k in keys), keys
    assert not errs, errs

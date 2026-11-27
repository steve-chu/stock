"""瀏覽器測試：用 iPhone 尺寸的瀏覽器開建好的網站，每個功能都實際點一次。
中繼站（手機新增股票）用假的回應，不連外。"""
import functools
import json
import os
import re
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="session")
def base_url(built):
    """把 site/ 放在 /stock/ 底下（和 GitHub Pages 一樣的路徑）。"""
    root = os.path.join(built, "_serve")
    os.makedirs(root, exist_ok=True)
    link = os.path.join(root, "stock")
    if not os.path.exists(link):
        os.symlink(os.path.join(built, "site"), link)
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    h = functools.partial(Quiet, directory=root)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/stock/"
    srv.shutdown()


@pytest.fixture(scope="session")
def relay_url(built):
    p = os.path.join(built, "relay.txt")
    return open(p).read().split("#")[0].strip().rstrip("/") if os.path.exists(p) else ""


@pytest.fixture(scope="session")
def pw():
    with playwright.sync_playwright() as p:
        yield p


BROWSERS = os.environ.get("E2E_BROWSERS", "chromium,webkit").split(",")


@pytest.fixture(scope="session", params=BROWSERS)
def browser(pw, request):
    try:
        b = getattr(pw, request.param).launch()
    except Exception as e:
        pytest.skip(f"{request.param} 沒裝：{str(e)[:80]}")
    yield b
    b.close()


@pytest.fixture
def phone(browser, pw):
    """一支「新手機」：全新的儲存空間，回傳 (context, page, 錯誤清單)。"""
    dev = dict(pw.devices["iPhone 13"])
    dev.pop("default_browser_type", None)
    ctxs = []

    def make(standalone=False, **over):
        ctx = browser.new_context(**{**dev, **over})
        if standalone:   # 從主畫面圖示打開
            ctx.add_init_script("Object.defineProperty(navigator,'standalone',{get:()=>true})")
        ctxs.append(ctx)
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(f"JS 錯誤：{e}"))
        pg.on("console", lambda m: m.type == "error" and not re.search(r"Failed to load resource", m.text) and errs.append(m.text))
        return ctx, pg, errs
    yield make
    for c in ctxs:
        c.close()



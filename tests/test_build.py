"""每日建置：輸出給手機的每個檔案都要在、格式要對；兩個版本（主版本、貝貝版）都要組得起來。"""
import json
import os
import re

import pytest

from helpers import stock_ids


def site(repo, *p):
    return os.path.join(repo, "site", *p)


def load(repo, *p):
    return json.load(open(site(repo, *p), encoding="utf-8"))


@pytest.mark.parametrize("sid", stock_ids())
def test_every_stock_has_all_files(built, sid):
    d = load(built, "data", "stock", f"{sid}.json")
    a = load(built, "data", "stock", f"{sid}.alt.json")
    assert d["stock_id"] == sid and len(d["bars"]) > 200 and "strategy" in d
    assert d["longterm"]["core"]["core"] != a["longterm"]["core"]["core"], "★ 相反版本要真的相反"
    assert isinstance(d["pf_levels"], list)
    for tf in ("W", "M"):
        assert load(built, "data", "bars", f"{sid}_{tf}.json")["bars"]
    lbt = load(built, "data", "lbt", f"{sid}.json")
    assert "summary" in lbt or "error" in lbt


def test_watchlist_quotes(built):
    q = load(built, "data", "watchlist.json")["quotes"]
    assert [x["stock_id"] for x in q] == stock_ids()
    for x in q:
        assert x["close"] > 0 and x["base"] is True and x["held"] is False
        assert "alt" in x, f"{x['stock_id']} 少了 ★ 相反的欄位"
        for k in ("_heat", "_crash", "_cooling", "core", "cyclical"):
            assert k in x


def test_status_names_version(built):
    st = load(built, "data", "status.json")
    assert st["last_date"] and st["built_at"] and st["token"] is True
    names = load(built, "data", "names.json")
    assert len(names) > 1000 and all(len(r) == 3 for r in names)
    assert any(r[0] == "2330" and "台積" in r[1] for r in names)
    v = load(built, "data", "version.json")["v"]
    assert f'name="kp-ver" content="{v}"' in open(site(built, "index.html"), encoding="utf-8").read()
    assert load(built, "data", "lbt_all.json")


def test_main_index(built):
    h = open(site(built, "index.html"), encoding="utf-8").read()
    for need in ("static-api.js", "mobile.js", "mobile.css", "manifest.webmanifest", "apple-touch-icon.png", "user-scalable=no"):
        assert need in h, need
    assert h.index("static-api.js") < h.index('src="app.js'), "static-api 要在 app.js 之前載入"
    relay = open(os.path.join(built, "relay.txt")).read().split("#")[0].strip() if os.path.exists(os.path.join(built, "relay.txt")) else ""
    assert (f'KP_RELAY = "{relay}"' in h) == bool(relay)
    for f in ("app.js", "style.css", "static-api.js", "mobile.js", "mobile.css", "icon-192.png", "icon-512.png", ".nojekyll"):
        assert os.path.exists(site(built, f)), f
    json.load(open(site(built, "manifest.webmanifest"), encoding="utf-8"))


def test_theme_bb(built):
    h = open(site(built, "bb", "index.html"), encoding="utf-8").read()
    assert "<title>貝貝看盤台</title>" in h and 'KP_DATA = "../data/"' in h
    assert h.index("theme-pre.js") < h.index("style.css"), "紀錄分開存要最先載入"
    assert h.index("mobile.js") < h.index("theme.js")
    m = json.load(open(site(built, "bb", "manifest.webmanifest"), encoding="utf-8"))
    assert m["name"] == "貝貝看盤台"
    for f in ("photo.webp", "avatar.webp", "sign.woff2", "apple-touch-icon.png", "theme.css", "theme.js", "theme-pre.js"):
        assert os.path.getsize(site(built, "bb", f)) > 100, f
    assert not os.path.exists(site(built, "bb", "theme.json")), "theme.json 不該被發佈"
    assert "css('--grid')" in open(site(built, "bb", "app.js"), encoding="utf-8").read(), "主題的格線顏色沒套到"
    assert not os.path.exists(site(built, "bb", "data")), "主題版要共用上一層的資料"


def test_site_size_reasonable(built):
    total = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(site(built)) for f in fs)
    assert total < 300 * 1024 * 1024, "網站太大（GitHub Pages 上限 1GB，留安全空間）"


def test_no_secrets_published(built):
    pat = re.compile(r"(github_pat_|ghp_)[A-Za-z0-9_]{20,}|FINMIND_TOKEN\s*=\s*\S{10,}")
    for dp, _, fs in os.walk(site(built)):
        for f in fs:
            if f.endswith((".js", ".json", ".html", ".css", ".txt")):
                assert not pat.search(open(os.path.join(dp, f), encoding="utf-8", errors="ignore").read()), f


def test_theme_mom(built):
    h = open(site(built, "mom", "index.html"), encoding="utf-8").read()
    assert "<title>看盤台</title>" in h and 'KP_DATA = "../data/"' in h
    assert 'status-bar-style" content="black-translucent"' in h, "深色主題的狀態列要是深色"
    assert h.index("theme-pre.js") < h.index("style.css")
    m = json.load(open(site(built, "mom", "manifest.webmanifest"), encoding="utf-8"))
    assert m["name"] == "看盤台" and m["start_url"] == "./"
    for f in ("apple-touch-icon.png", "icon-192.png", "theme.js", "theme.css", "theme-pre.js"):
        assert os.path.exists(site(built, "mom", f)), f
    assert not os.path.exists(site(built, "mom", "theme.json"))

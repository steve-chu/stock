"""手機版：每天收盤後在 GitHub Actions 跑一次，把電腦版的分析全部算好，存成網頁要用的檔案。

流程：
  1. 資料庫：core/data/market.db（沒有就從 seed/market.db 複製）
  2. 自選股照 stocks.txt 同步（加進來的會自動抓資料，刪掉的移除）
  3. 每檔跑一次電腦版的完整分析（core/ 是電腦版程式原封不動的複本）
  4. 輸出到 site/：網頁（電腦版畫面＋手機版外殼）＋ data/ 底下的 JSON

本機測試：python build.py     （會連 FinMind 抓最新資料）
只用資料庫、不連網路：OFFLINE=1 python build.py
"""
import json
import os
import re
import shutil
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(ROOT, "core")
SITE = os.path.join(ROOT, "site")
os.environ.setdefault("TZ", "Asia/Taipei")
if hasattr(time, "tzset"):
    time.tzset()
db = os.path.join(CORE, "data", "market.db")
if not os.path.exists(db):
    os.makedirs(os.path.dirname(db), exist_ok=True)
    shutil.copy(os.path.join(ROOT, "seed", "market.db"), db)
    print("資料庫：從 seed/market.db 開始")

sys.path.insert(0, CORE)
import app as core  # noqa: E402  電腦版的 app.py
import data_source as ds  # noqa: E402
import portfolio  # noqa: E402
from fastapi import HTTPException  # noqa: E402

OFFLINE = os.environ.get("OFFLINE") == "1"
if OFFLINE:   # 不連網路：所有抓資料的地方都當作「已經是最新」
    ds.price_needs_refresh = lambda *a, **k: False
    _gd = ds.get_dataset
    ds.get_dataset = lambda name, sid, force=False: (ds.get_dataset_cached(name, sid), None)
    ds.backfill_long = lambda sid: None
    ds.get_prices = (lambda f: (lambda sid, *a, **k: f(sid, refresh=False)))(ds.get_prices)


def dump(path, obj):
    path = os.path.join(SITE, "data", path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), default=str)


def wanted():
    out = []
    for line in open(os.path.join(ROOT, "stocks.txt"), encoding="utf-8"):
        sid = line.split("#")[0].strip().upper()
        if sid and sid not in out:
            out.append(sid)
    return out


def sync_watchlist(ids):
    have = ds.watchlist_ids()
    for sid in have:
        if sid not in ids:
            ds.watchlist_remove(sid)
            print("移除", sid)
    for sid in ids:
        if sid not in have:
            try:
                core.watchlist_add({"stock_id": sid})
                print("加入", sid)
            except HTTPException as e:
                print("加入失敗", sid, e.detail)


# 抓出電腦版算持股損益時用的價位（支撐、月線、策略價位、壓力），手機自己算損益要用
_levels = {}
_orig = portfolio.compute


def _cap(stock_id, trades, close, levels, tick_fn):
    _levels[stock_id] = [list(x) for x in levels]
    return _orig(stock_id, trades, close, levels, tick_fn)


portfolio.compute = _cap
core.portfolio.compute = _cap


def main():
    t0 = time.time()
    ds.init_db()
    if not OFFLINE:
        try:
            ds.ensure_stock_info()
        except Exception as e:
            print("股票名稱更新失敗（不影響）：", e)
    ids = wanted()
    sync_watchlist(ids)
    ids = ds.watchlist_ids()
    if os.path.exists(SITE):
        shutil.rmtree(SITE)
    ok, failed = [], []
    for sid in ids:
        try:
            r = core.stock(sid)
            r["pf_levels"] = _levels.get(sid, [])
            r.pop("prefs", None)
            dump(f"stock/{sid}.json", r)
            for tf in ("W", "M"):
                dump(f"bars/{sid}_{tf}.json", core.bars_tf(sid, tf))
            ok.append(sid)
        except HTTPException as e:
            failed.append({"stock_id": sid, "error": e.detail})
        except Exception as e:
            traceback.print_exc()
            failed.append({"stock_id": sid, "error": str(e)})
        print(f"{sid} {'OK' if sid in ok else '失敗'}  {time.time() - t0:.0f}s", flush=True)

    # 自選股清單：過熱／股災只對「持有的人」顯示，誰持有由各自的手機決定，所以全部先算好
    core_ids = ds.core_ids()
    quotes = []
    for sid in ids:
        q = core._quote(sid, True)
        q.update({"core": sid in core_ids, "cyclical": ds.meta_get(f"category:{sid}") == "cyclical",
                  "_heat": q.pop("heat", None), "_crash": q.pop("crash", None), "_cooling": q.pop("cooling", False)})
        q["held"] = False
        quotes.append(q)
    dump("watchlist.json", {"quotes": quotes})

    for sid in ok:
        try:
            dump(f"lbt/{sid}.json", core.longbt_one(sid))
        except Exception as e:
            dump(f"lbt/{sid}.json", {"stock_id": sid, "error": f"回測失敗：{e}"})
    try:
        dump("lbt_all.json", core.longbt_all())
    except Exception as e:
        dump("lbt_all.json", {"stocks": [], "total": {}, "error": str(e)})

    st = core.status()
    st.update({"mode": "live", "token": True, "built_at": time.strftime("%Y-%m-%d %H:%M"), "stocks": len(ok), "failed": failed,
               "last_date": max((q.get("date") or "" for q in quotes), default="")})
    dump("status.json", st)

    # 網頁：電腦版的畫面（core/static）＋手機版外殼（web/）
    shutil.copytree(os.path.join(CORE, "static"), SITE, dirs_exist_ok=True)
    shutil.copytree(os.path.join(ROOT, "web"), SITE, dirs_exist_ok=True)
    write_index()
    open(os.path.join(SITE, ".nojekyll"), "w").close()
    print(f"完成：{len(ok)} 檔，失敗 {len(failed)} 檔，{time.time() - t0:.0f} 秒")
    for f in failed:
        print("  失敗", f)


MOBILE_HEAD = """<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="看盤台">
<meta name="theme-color" content="#0c0e12">
<meta name="kp-ver" content="{v}">
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="stylesheet" href="mobile.css?v={v}">
</head>"""


def write_index():
    """手機版首頁 = 電腦版 index.html ＋ 手機外殼（電腦版畫面改了，手機版自動跟著）。"""
    v = time.strftime("%Y%m%d%H%M")
    html = open(os.path.join(CORE, "static", "index.html"), encoding="utf-8").read()
    html = re.sub(r"\?v=[0-9.]+", "?v=" + v, html)
    html = html.replace('content="width=device-width, initial-scale=1"',
                        'content="width=device-width, initial-scale=1, minimum-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover"')
    html = html.replace("</head>", MOBILE_HEAD.format(v=v), 1)
    html = html.replace('<script src="app.js', f'<script src="static-api.js?v={v}"></script>\n<script src="app.js', 1)
    html = html.replace("</body>", f'<script src="mobile.js?v={v}"></script>\n</body>', 1)
    assert "static-api.js" in html and "mobile.js" in html and "manifest" in html, "index.html 結構變了"
    open(os.path.join(SITE, "index.html"), "w", encoding="utf-8").write(html)
    dump("version.json", {"v": v})   # 手機打開時比對，版本不同就自動重新載入


if __name__ == "__main__":
    main()

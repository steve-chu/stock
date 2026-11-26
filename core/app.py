"""我的看盤台 — 啟動：python app.py，然後打開 http://127.0.0.1:8000"""
import os
import threading
import webbrowser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_env():
    """讀同資料夾的 .env（KEY=VALUE），不用額外裝套件。"""
    path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

import csv  # noqa: E402
import bisect  # noqa: E402
import json  # noqa: E402
import datetime as dt  # noqa: E402
import io  # noqa: E402
import traceback  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

import uvicorn  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import analysis  # noqa: E402
import longbt  # noqa: E402
import danger  # noqa: E402
import strategy  # noqa: E402
import data_source as ds  # noqa: E402
import fundamentals  # noqa: E402
import longterm  # noqa: E402
import portfolio  # noqa: E402
import retail  # noqa: E402
import trend  # noqa: E402
import zones  # noqa: E402

OUT_BARS = 1250  # 傳給前端畫圖的日 K 根數（約 5 年）
CHART_KEYS = ["ma5", "ma20", "ma60", "ma50", "ma120", "ma150", "ma200", "ma240", "trend_ma",
              "k", "d", "dif", "dea", "hist", "rsi"]
FUND_SETS = list(ds.DATASETS)
ETF_SKIP = {"TaiwanStockMonthRevenue", "TaiwanStockFinancialStatements"}   # ETF 也抓股利：算含息報酬
_pool = ThreadPoolExecutor(max_workers=4)


@asynccontextmanager
async def lifespan(_app):
    ds.init_db()
    try:
        ds.backup_db()
    except Exception as e:  # 備份失敗不影響使用
        print("備份失敗：", e)
    threading.Thread(target=ds.ensure_stock_info, daemon=True).start()
    yield


app = FastAPI(title="我的看盤台", lifespan=lifespan)


@app.middleware("http")
async def no_cache(request, call_next):
    """前端檔案每次都向伺服器確認，更新程式後不用強制重新整理。"""
    resp = await call_next(request)
    if not request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/api/status")
def status():
    exp = ds.expected_date()
    return {"mode": "demo" if ds.DEMO else "finmind", "token": bool(ds.TOKEN),
            "expected_date": exp.isoformat(), "weekend": dt.date.today().weekday() >= 5}


# ---------- 自選股 ----------

def _held():
    by = {}
    for t in ds.trades():
        by.setdefault(t["stock_id"], []).append(t)
    out = set()
    for sid, ts in by.items():
        st, _ = portfolio.replay(sid, ts)
        if st and st["shares"] > 0:
            out.add(sid)
    return out


def _save_plan(stock_id, date, L, dg):
    """把長線計畫的恐慌段價位、過熱程度存起來，讓自選股清單和通知不用重算。"""
    try:
        fear = [{"p": t["price"], "n": t["n"], "trial": str(t.get("why", "")).startswith("試單")}
                for t in (L or {}).get("tranches", []) if t.get("stage") == "恐慌段" and t.get("price")]
        heat = (dg or {}).get("level") if (dg or {}).get("applies") and not (dg or {}).get("late") else "healthy"
        cooling = bool((dg or {}).get("cooling")) and heat != "healthy"
        crash = (dg or {}).get("crash") or {}
        cheap = next((x.get("ok") for x in (L or {}).get("fear", []) if str(x.get("text", "")).startswith("估值")), None)
        ds.meta_set(f"plan:{stock_id}", json.dumps({"date": date, "fear": fear, "heat": heat, "cheap": cheap, "cooling": cooling,
                                                     "crash": crash.get("reasons") if crash.get("on") else None}))
    except Exception:
        pass


def _plan(stock_id):
    try:
        return json.loads(ds.meta_get(f"plan:{stock_id}") or "null")
    except Exception:
        return None


def _quote(stock_id, held=False):
    """只讀資料庫，不連網路。"""
    meta = ds.stock_meta(stock_id)
    bars = ds.cached_quote_bars(stock_id)
    if not bars:
        return {"stock_id": stock_id, **meta, "held": held, "missing": True, "error": "尚無資料，按「全部更新」"}
    last, prev = bars[-1], bars[-2] if len(bars) > 1 else bars[-1]
    chg = last["close"] - prev["close"]
    pl = _plan(stock_id) or {}
    hit = [t for t in pl.get("fear", []) if t["p"] >= last["close"] * 0.999]   # 股價已經到（或低於）這些恐慌段價位
    deepest = min(hit, key=lambda t: t["p"]) if hit else None
    nxt = max((t for t in pl.get("fear", []) if t["p"] < last["close"] * 0.999), key=lambda t: t["p"], default=None)
    return {
        "stock_id": stock_id, **meta, "held": held, "date": last["date"], "close": last["close"],
        "change": round(chg, 2), "change_pct": round(chg / prev["close"] * 100, 2),
        "spark": [b["close"] for b in bars[-30:]],
        "stale": last["date"] < ds.expected_date().isoformat(),
        "buy": deepest, "next_buy": nxt, "heat": pl.get("heat") if held else None,
        "crash": pl.get("crash") if held else None, "cooling": bool(pl.get("cooling")) if held else False,
    }


def _alerts(quotes):
    """三種通知，各自只在「狀態改變」時通知一次（記在資料庫，重開也不重複）：
    1. 股價跌到長線計畫的恐慌段價位   2. 持股進入過熱「留意」或「危機」（停止加碼）   3. 持股出現股災警報"""
    out = []
    for q in quotes:
        if q.get("missing"):
            continue
        sid, b = q["stock_id"], q.get("buy")
        # 只記第幾批：試單價位每天跟著收盤走，用價位當 key 會天天重複通知
        key, cur = f"alert:buy:{sid}", (str(b["n"]) if b else "none")
        prev = ds.meta_get(key)
        if prev != cur:
            ds.meta_set(key, cur)
            # 試單只在核心股、或估值也便宜時才發通知（大盤一跌就全部亮，太吵）；清單上的標籤照常顯示
            loud = b and (not b.get("trial") or q.get("core") or (_plan(sid) or {}).get("cheap"))
            if loud:
                out.append({"stock_id": sid, "name": q["name"], "date": q["date"], "kind": "buy",
                            "title": f"到買點：{q['name']}" + (" 試單" if b.get("trial") else f" 第 {b['n']} 批"),
                            "text": (f"短期下跌中（收盤 {q['close']:g}），可以先試單" if b.get("trial") else
                                     f"收盤 {q['close']:g}，已到恐慌段第 {b['n']} 批價位 {b['p']:g}，可以加碼")})
        h = q.get("heat")
        key, cur = f"alert:heat:{sid}", h or "none"
        prev = ds.meta_get(key)
        if prev != cur:
            ds.meta_set(key, cur)
            # 從「沒熱」變成留意／危機、或從留意升級成危機才通知；退回健康不通知
            if (h == "watch" and prev not in ("watch", "crisis")) or (h == "crisis" and prev != "crisis"):
                out.append({"stock_id": sid, "name": q["name"], "date": q["date"], "kind": "heat",
                            "title": f"{'持股高檔轉弱' if q.get('cooling') else '持股過熱'}：{q['name']}",
                            "text": ("高檔轉弱：停止加碼，持股不動" if q.get("cooling")
                                     else f"過熱「{'留意' if h == 'watch' else '危機'}」：停止加碼，持股不動")})
        cr = q.get("crash")
        key, cur = f"alert:crash:{sid}", ("|".join(cr) if cr else "none")
        prev = ds.meta_get(key)
        if prev != cur:
            ds.meta_set(key, cur)
            if cr and (not prev or prev == "none"):
                out.append({"stock_id": sid, "name": q["name"], "date": q["date"], "kind": "crash",
                            "title": f"股災警報：{q['name']}",
                            "text": "；".join(cr) + "。短線 30% 部位減碼，可轉其他商品；長線 70% 不動"})
    return out


_bg_lock = threading.Lock()


def _bg_update_plans(ids):
    """背景重算：沒有財報的股票補抓一次、長線計畫還停在舊日期的重算，讓清單標籤和通知跟上最新收盤。"""
    if not _bg_lock.acquire(blocking=False):
        return
    try:
        for sid in ids:
            try:
                last = ds.cached_quote_bars(sid)
                pl = _plan(sid)
                # 沒有財報、或財報還是舊格式（沒存淨利，無法確認除權股數）→ 重算一次會順便重抓
                no_fund = not ds.is_etf(sid) and (not ds.has_dataset(sid, "TaiwanStockFinancialStatements")
                                                  or not ds.meta_get(f"fsv2:{sid}"))
                no_div = ds.is_etf(sid) and not ds.has_dataset(sid, "TaiwanStockDividend")   # ETF 配息（算含息報酬）
                if no_fund or no_div or not pl or (last and pl.get("date") < last[-1]["date"]):
                    stock(sid)
            except Exception:
                traceback.print_exc()
    finally:
        _bg_lock.release()


@app.get("/api/watchlist")
def watchlist():
    held = _held()
    core = ds.core_ids()
    quotes = [{**_quote(s, s in held), "core": s in core, "cyclical": ds.meta_get(f"category:{s}") == "cyclical"}
              for s in ds.watchlist_ids()]
    return {"quotes": quotes, "alerts": _alerts(quotes)}


class RefreshReq(BaseModel):
    force: bool = False          # True = 「全部更新」按鈕
    min_interval: int | None = None


@app.post("/api/refresh")
def refresh(body: RefreshReq):
    """更新自選股的日 K。已有最新收盤的會跳過；開 app 時用 30 分鐘間隔。"""
    ids = ds.watchlist_ids()
    interval = body.min_interval if body.min_interval is not None else ds.OPEN_INTERVAL
    todo = [s for s in ids if ds.price_needs_refresh(s, interval, body.force)]

    def one(sid):
        try:
            return sid, ds.refresh_prices(sid), None
        except ds.SourceError as e:
            return sid, 0, str(e)

    results = list(_pool.map(one, todo))
    threading.Thread(target=_bg_update_plans, args=(ids,), daemon=True).start()
    held = _held()
    core = ds.core_ids()
    quotes = [{**_quote(s, s in held), "core": s in core, "cyclical": ds.meta_get(f"category:{s}") == "cyclical"}
              for s in ids]
    return {
        "alerts": _alerts(quotes),
        "checked": len(ids), "fetched": len(todo),
        "updated": [sid for sid, n, err in results if n > 0],
        "failed": [{"stock_id": sid, "error": err} for sid, _, err in results if err],
        "latest": len(ids) - len(todo),
        "quotes": quotes,
    }


@app.post("/api/watchlist")
def watchlist_add(body: dict):
    sid = str(body.get("stock_id", "")).strip().upper()
    if not sid or len(sid) > 10 or not sid.isalnum():
        raise HTTPException(400, "股票代號格式不對")
    try:
        ds.get_prices(sid)
    except ds.SourceError as e:
        raise HTTPException(404, str(e))
    ds.watchlist_add(sid)
    return _quote(sid, sid in _held())


@app.delete("/api/watchlist/{stock_id}")
def watchlist_remove(stock_id: str):
    ds.watchlist_remove(stock_id)
    return {"ok": True}


@app.get("/api/search")
def search(q: str = ""):
    return ds.search_stocks(q)


# ---------- 個股 ----------

def _safe(fn, *args, **kw):
    """一個區塊出錯只影響那一塊，不讓整頁讀不到。"""
    try:
        return fn(*args, **kw), None
    except Exception as e:
        traceback.print_exc()
        return None, f"{e.__class__.__name__}: {e}"


def _next_month_10(y, m):
    return dt.date(y + (m == 12), m % 12 + 1, 10)


EPS_DEADLINE = {3: (5, 15), 6: (8, 14), 9: (11, 14)}


def _known_on(dataset, rows, as_of):
    """回看日期時，只保留「那天已經公布」的資料，避免偷看未來。"""
    a = as_of.isoformat()
    if dataset == "TaiwanStockMonthRevenue":
        return [r for r in rows if _next_month_10(int(r["revenue_year"]), int(r["revenue_month"])) <= as_of]
    if dataset == "TaiwanStockFinancialStatements":
        out = []
        for r in rows:
            d = dt.date.fromisoformat(r["date"][:10])
            mm, dd = EPS_DEADLINE.get(d.month, (3, 31))
            avail = dt.date(d.year + (d.month == 12), mm, dd)
            if avail <= as_of:
                out.append(r)
        return out
    if dataset == "TaiwanStockDividend":
        def ann(r):
            x = str(r.get("AnnouncementDate") or "")[:10]
            return x if len(x) == 10 and x[4] == "-" else str(r.get("date", ""))[:10]
        return [r for r in rows if ann(r) <= a]
    return [r for r in rows if str(r.get("date", ""))[:10] <= a]


def _forward(bars_all, k):
    """回看日期之後實際怎麼走。"""
    base = bars_all[k]["close"]
    fut = bars_all[k + 1:k + 61]
    if not fut:
        return None
    ret = lambda n: round((bars_all[k + n]["close"] / base - 1) * 100, 2) if k + n < len(bars_all) else None
    return {"d5": ret(5), "d20": ret(20), "d60": ret(60), "days": len(fut),
            "max_up": round((max(b["high"] for b in fut) / base - 1) * 100, 2),
            "max_down": round((min(b["low"] for b in fut) / base - 1) * 100, 2),
            "to_date": fut[-1]["date"]}


@app.get("/api/stock/{stock_id}")
def stock(stock_id: str, force: bool = False, as_of: str | None = None):
    try:
        p = ds.get_prices(stock_id, min_interval=ds.CLICK_INTERVAL, force=force)
    except ds.SourceError as e:
        raise HTTPException(404, str(e))
    etf = ds.is_etf(stock_id)
    need = [n for n in FUND_SETS if not (etf and n in ETF_SKIP)]  # ETF 不抓營收、財報（股利要抓：算含息報酬）
    if ds.DEMO:
        sets = {n: ds.get_dataset(n, stock_id, force) for n in need}
    else:
        futs = {n: _pool.submit(ds.get_dataset, n, stock_id, force) for n in need}
        sets = {n: f.result() for n, f in futs.items()}
    sets.update({n: ([], None) for n in FUND_SETS if n not in sets})
    warnings = [p["warning"]] if p["warning"] else []
    warnings += [w for _, w in sets.values() if w]
    data = {n: rows for n, (rows, _) in sets.items()}

    bars_all = p["bars"]
    replay = None
    if as_of:
        try:
            asd = dt.date.fromisoformat(as_of)
        except ValueError:
            raise HTTPException(400, "日期格式要是 YYYY-MM-DD")
        k = max((j for j, b in enumerate(bars_all) if b["date"] <= as_of), default=None)
        if k is None or k < 60:
            raise HTTPException(400, f"{as_of} 之前的資料不足，請選晚一點的日期")
        if k < len(bars_all) - 1:
            bars = bars_all[:k + 1]
            data = {n: _known_on(n, rows, asd) for n, rows in data.items()}
            replay = {"as_of": bars[-1]["date"], "forward": _forward(bars_all, k)}
        else:
            bars = bars_all
    else:
        bars = bars_all

    close = bars[-1]["close"]
    cfg = ds.settings(stock_id)
    tech = analysis.compute(bars)

    if etf:
        per = data["TaiwanStockPER"]
        fund, fund_err = {"etf": True, "category": "general", "manual": False,
                          "category_info": {"label": "ETF", "icon": "🧺", "method": "—"},
                          "valuations": {}, "primary_method": None,
                          "dividend_yield": (per[-1].get("dividend_yield") if per else None)}, None
        # ETF 沒有 EPS、配息率，但配息紀錄一定要看：每次配多少、當次殖利率、每年合計、近 12 個月殖利率
        ed, ed_err = _safe(fundamentals.etf_dividends, data["TaiwanStockDividend"],
                           ds.raw_closes(stock_id, bars[-1]["date"]), ds.div_series(stock_id, bars), close,
                           bars[-1]["date"], ds.price_events(stock_id, bars[-1]["date"]))
        fund["etf_div"], fund["etf_div_error"] = ed, ed_err
    else:
        fund, fund_err = _safe(fundamentals.build, close, data["TaiwanStockMonthRevenue"],
                               data["TaiwanStockFinancialStatements"], data["TaiwanStockDividend"],
                               data["TaiwanStockPER"], cfg["category"], ds.prefs()["rev_rule"],
                               ds.raw_closes(stock_id, bars[-1]["date"]),
                               ds.price_events(stock_id, bars[-1]["date"]))
        ca = (fund or {}).get("corp_actions") or {}
        if ca.get("events"):
            # 確認過的倍數存起來，K 線還原改用確切倍數（開盤價會偏離參考價，用跳空算會差幾 %）
            known = ds.known_splits(stock_id)
            new = {e["date"]: e["k"] for e in ca["events"]}
            if any(abs(known.get(d, 0) - k) > 1e-6 for d, k in new.items()):
                ds.meta_set(f"splits:{stock_id}", json.dumps({**known, **new}))
    category = fund["category"] if fund else "general"
    auto_profile = trend.CATEGORY_TO_PROFILE[category]
    profile = cfg["trend_profile"] if cfg["trend_profile"] in trend.PROFILES else auto_profile
    regime, regime_err = _safe(trend.judge, bars, data["TaiwanStockInstitutionalInvestorsBuySell"],
                               data["TaiwanStockMarginPurchaseShortSale"], profile)
    if regime:
        regime.update(auto_profile=auto_profile, manual=cfg["trend_profile"] in trend.PROFILES,
                      profiles={k: v["label"] for k, v in trend.PROFILES.items()})
        st = regime.pop("stages", None) or []
        regime["stages"] = [{"date": b["date"], "s": x} for b, x in zip(bars[-len(st):], st) if x] if st else []
        for sec in regime.get("sections", []):
            for m in (sec.get("overlay") or {}).get("markers", []):
                if "idx" in m:
                    m["date"] = bars[m.pop("idx")]["date"]
    ret, ret_err = _safe(retail.judge, bars, data["TaiwanStockMarginPurchaseShortSale"])
    zn, zn_err = _safe(zones.build, bars, data["TaiwanStockPER"], ((fund or {}).get("eps") or {}).get("estimate"))
    dg, dg_err = _safe(danger.judge, bars, data["TaiwanStockMarginPurchaseShortSale"],
                       data["TaiwanStockInstitutionalInvestorsBuySell"], data["TaiwanStockPER"],
                       (regime or {}).get("state"))
    # 長期體質：技術面 6 項（對照 0050）＋基本面趨勢＋我的長期名單
    bench = None
    if stock_id != "0050":
        try:
            bench = [b for b in ds.get_prices("0050")["bars"] if b["date"] <= bars[-1]["date"]]
        except ds.SourceError:
            bench = []
    tq, tq_err = _safe(longterm.tech_quality, bars, bench, ds.div_series(stock_id, bars),
                       ds.div_series("0050", bench) if bench else None)
    ftr = longterm.fund_trend(fund)
    core = ds.core_get(stock_id)
    category = (fund or {}).get("category") if not etf else "etf"
    elig = longterm.eligibility(tq, ftr, core["core"], etf, category) if tq else None
    # 股災警報：大盤（0050）過熱危機、或跌破年線且年線下彎、或這檔體質轉壞 → 只減短線 30% 部位
    mkt = _market(bench if stock_id != "0050" else bars)
    if dg:
        dg["market"] = mkt
        dg["crash"] = danger.crash_check(mkt, (elig or {}).get("status"))
    if not replay and category:
        try:
            if ds.meta_get(f"category:{stock_id}") != category:
                ds.meta_set(f"category:{stock_id}", category)   # 給自選股清單標記循環股用
        except Exception:
            pass
    strat, strat_err = _safe(strategy.build, bars, tech["raw"], tech["analysis"], regime, fund, ret, zn,
                             ds.prefs(), dg, elig, tq)
    strat = strat or {"error": strat_err, "lines": [], "long": None, "swing": None}
    if not replay:
        _save_plan(stock_id, bars[-1]["date"], strat.get("long"), dg)

    lv = tech["analysis"]["levels"]
    levels = [("支撐", lv["support"], "support"), ("現價", close, "now"), ("月線", lv["ma20"], "ma")]
    levels += [(x["label"], x["price"], {"stop": "stop", "target": "target"}.get(x["kind"], x["kind"]))
               for x in strat["lines"]]
    levels += [(f"壓力區 {x['lo']:.1f}", x["lo"], "resistance") for x in ((zn or {}).get("resist") or [])[:2]]
    merged = {}
    for lab, price, kind in levels:
        if price is None:
            continue
        key = round(price, 2)
        if key in merged and kind != "now":
            merged[key] = (merged[key][0] + "／" + lab, price, merged[key][2])
        elif key not in merged or kind == "now":
            merged[key] = (lab, price, kind)
    my_trades = [t for t in ds.trades(stock_id) if not replay or t["date"] <= replay["as_of"]]
    pos, pos_err = _safe(portfolio.compute, stock_id, my_trades, close, list(merged.values()), analysis.tick)

    # 圖：指標用完整資料算（只看過去，不會偷看未來），回看時視窗延伸到之後 120 根方便對照
    closes_all = [b["close"] for b in bars_all]
    ind = {k: v for k, v in analysis.compute(bars_all)["indicators"].items()}
    for n_ in (50, 120, 150, 200, 240):
        ind[f"ma{n_}"] = analysis.sma(closes_all, n_)
    ind["trend_ma"] = analysis.sma(closes_all, (regime or {}).get("ma_period") or 150)
    end = min(len(bars) - 1 + 120, len(bars_all) - 1) if replay else len(bars_all) - 1
    start = max(0, end - OUT_BARS + 1)
    out_bars = bars_all[start:end + 1]
    chart_ind = {k: [None if x is None else round(x, 2) for x in ind[k][start:end + 1]] for k in CHART_KEYS}

    return {
        "stock_id": stock_id, **ds.stock_meta(stock_id),
        "bars": out_bars, "analysis_date": bars[-1]["date"], "replay": replay,
        "fetched_at": p["fetched_at"], "up_to_date": p["up_to_date"],
        "warning": "；".join(warnings) or None,
        "indicators": chart_ind, "analysis": tech["analysis"], "strategy": strat,
        "regime": regime or {"error": regime_err},
        "fundamentals": fund or {"error": fund_err},
        "retail": ret or {"error": ret_err},
        "danger": dg or {"error": dg_err},
        "longterm": {"tech": tq or {"error": tq_err}, "fund": ftr, "elig": elig, "core": core},
        "zones": zn or {"error": zn_err},
        "portfolio": pos or {"error": pos_err, "trades": [], "realized": 0, "has_position": False},
        "settings": cfg, "prefs": ds.prefs(),
    }


_mkt_cache = {}


def _market(bench):
    """大盤狀態（用 0050），同一天只算一次。"""
    if not bench:
        return None
    key = bench[-1]["date"]
    if key not in _mkt_cache:
        try:
            dset = lambda n: ds.get_dataset_cached(n, "0050")
            bdg = danger.judge(bench, dset("TaiwanStockMarginPurchaseShortSale"),
                               dset("TaiwanStockInstitutionalInvestorsBuySell"), dset("TaiwanStockPER"))
            _mkt_cache.clear()
            _mkt_cache[key] = danger.market_state(bench, bdg)
        except Exception:
            traceback.print_exc()
            return None
    return _mkt_cache[key]


class CoreBody(BaseModel):
    core: bool
    reason: str | None = None
    invalidation: str | None = None


@app.put("/api/core/{stock_id}")
def core_save(stock_id: str, body: CoreBody):
    return ds.core_save(stock_id, body.core, body.reason, body.invalidation)


# ---------- 週 K、月 K（用長歷史合成） ----------

def _bucket(date, tf):
    if tf == "M":
        return date[:7] + "-01"
    d = dt.date.fromisoformat(date)
    return (d - dt.timedelta(days=d.weekday())).isoformat()  # 每週一當代表日


@app.get("/api/bars/{stock_id}")
def bars_tf(stock_id: str, tf: str = "W"):
    if tf not in ("W", "M"):
        raise HTTPException(400, "tf 只能是 W 或 M")
    warning = None
    try:
        ds.backfill_long(stock_id)  # 每檔只會補抓一次
    except ds.SourceError as e:
        warning = f"長歷史補抓失敗，先用現有資料：{e}"
    out, cur = [], None
    for b in ds.long_bars(stock_id):
        k = _bucket(b["date"], tf)
        if not cur or cur["date"] != k:
            cur = {"date": k, "open": b["open"], "high": b["high"], "low": b["low"],
                   "close": b["close"], "volume": b["volume"], "last": b["date"]}
            out.append(cur)
        else:
            cur["high"] = max(cur["high"], b["high"])
            cur["low"] = min(cur["low"], b["low"])
            cur["close"] = b["close"]
            cur["volume"] += b["volume"]
            cur["last"] = b["date"]
    return {"stock_id": stock_id, "tf": tf, "bars": out, "warning": warning,
            "since": out[0]["date"] if out else None}


# ---------- 回測 ----------

def _profile_for(stock_id):
    cfg = ds.settings(stock_id)
    if cfg["trend_profile"] in trend.PROFILES:
        return cfg["trend_profile"]
    cat = cfg["category"] if cfg["category"] in fundamentals.CATEGORIES else None
    if not cat:  # 沒手動設定時，用快取的財報資料判斷分類（不連網）
        try:
            f = fundamentals.build(1, [], ds.get_dataset_cached("TaiwanStockFinancialStatements", stock_id),
                                   ds.get_dataset_cached("TaiwanStockDividend", stock_id), [])
            cat = f["category"]
        except Exception:
            cat = "general"
    return trend.CATEGORY_TO_PROFILE.get(cat, "default")


# ---------- 長線回測：照策略總表的買點，近 1／2／3／5 年每次 5 萬，抱到今天 ----------

def _longbt(stock_id, bench, bench_divs):
    """照策略總表回測。每天的價位表算過就存起來（只會多算新的交易日），第二次打開很快。"""
    bars = ds.long_bars(stock_id)
    if len(bars) < longbt.MIN_HIST + 2:
        return {"error": "歷史資料不足"}
    dates = [b["date"] for b in bars]
    y0 = int(dates[-1][:4])
    start = max(bisect.bisect_right(dates, f"{y0 - max(longbt.YEARS)}{dates[-1][4:]}"), longbt.MIN_HIST)
    key = f"lbt:{stock_id}"
    try:
        cache = json.loads(ds.meta_get(key) or "null")
    except Exception:
        cache = None
    if not cache or cache.get("v") != longbt.VERSION or cache.get("first") != dates[0]:
        cache = {"v": longbt.VERSION, "first": dates[0], "lad": {}}
    lad = cache["lad"]
    done = max(lad) if lad else None
    todo = start if not done else max(start, bisect.bisect_right(dates, done))
    if todo < len(bars) - 1:
        lad.update(longbt.ladders(bars, ds.get_dataset_cached("TaiwanStockPER", stock_id),
                                  ds.get_dataset_cached("TaiwanStockInstitutionalInvestorsBuySell", stock_id),
                                  ds.get_dataset_cached("TaiwanStockMarginPurchaseShortSale", stock_id),
                                  _profile_for(stock_id), todo))
        lad = {d: v for d, v in lad.items() if d >= dates[start]}
        cache["lad"] = lad
        try:
            ds.meta_set(key, json.dumps(cache, separators=(",", ":"), ensure_ascii=False))
        except Exception:
            traceback.print_exc()
    return longbt.run(bars, lad, ds.div_series(stock_id, bars), bench if stock_id != "0050" else None, bench_divs)


def _bench_long():
    b = ds.long_bars("0050")
    return b, ds.div_series("0050", b)


@app.get("/api/longbt/{stock_id}")
def longbt_one(stock_id: str):
    if ds.is_etf(stock_id):
        return {"stock_id": stock_id, **ds.stock_meta(stock_id),
                "error": "ETF 不做回測：ETF 是比較基準，個股每次買進時，會用同一天、同金額買 0050 來比"}
    bench, bdiv = _bench_long()
    return {"stock_id": stock_id, **ds.stock_meta(stock_id), **_longbt(stock_id, bench, bdiv),
            "cyclical": ds.meta_get(f"category:{stock_id}") == "cyclical"}


@app.get("/api/longbt")
def longbt_all():
    bench, bdiv = _bench_long()
    series, skipped = [], []
    for sid in ds.watchlist_ids():
        # 循環股不在長線範圍；ETF 不回測（ETF 是拿來當比較基準的：每次買個股，同一天同金額買 0050 比）
        if ds.is_etf(sid) or ds.meta_get(f"category:{sid}") == "cyclical":
            skipped.append(ds.stock_meta(sid)["name"])
            continue
        try:
            series.append((sid, ds.stock_meta(sid)["name"], _longbt(sid, bench, bdiv)))
        except Exception:
            traceback.print_exc()
    return {**longbt.run_many(series), "skipped": skipped}


# ---------- 偏好設定（短線資金、每筆最多虧幾 %） ----------

class Prefs(BaseModel):
    capital: float | None = None
    risk_pct: float | None = None
    rev_rule: str | None = None
    long_capital: float | None = None
    cash_pct: float | None = None
    stock_pct: float | None = None
    sector_pct: float | None = None


@app.put("/api/prefs")
def prefs_save(body: Prefs):
    if body.capital is not None and body.capital < 0:
        raise HTTPException(400, "資金不能是負數")
    if body.risk_pct is not None and not (0.1 <= body.risk_pct <= 10):
        raise HTTPException(400, "每筆最多虧損請填 0.1～10%")
    if body.rev_rule is not None and body.rev_rule not in fundamentals.REV_RULES:
        raise HTTPException(400, "營收規則不存在")
    for k in ("cash_pct", "stock_pct", "sector_pct"):
        v = getattr(body, k)
        if v is not None and not (0 <= v <= 100):
            raise HTTPException(400, "百分比請填 0～100")
    if body.long_capital is not None and body.long_capital < 0:
        raise HTTPException(400, "資金不能是負數")
    return ds.prefs_save(**body.model_dump())


# ---------- 交易紀錄 ----------

class Trade(BaseModel):
    stock_id: str
    date: str
    side: str
    price: float
    shares: int


@app.post("/api/trades")
def trade_add(t: Trade):
    sid = t.stock_id.strip().upper()
    try:
        dt.date.fromisoformat(t.date)
    except ValueError:
        raise HTTPException(400, "日期格式要是 YYYY-MM-DD")
    if t.side not in ("buy", "sell"):
        raise HTTPException(400, "side 要是 buy 或 sell")
    if t.price <= 0 or t.shares <= 0:
        raise HTTPException(400, "價格和股數要大於 0")
    trial = ds.trades(sid) + [{"id": 10 ** 9, "stock_id": sid, "date": t.date, "side": t.side,
                               "price": t.price, "shares": t.shares}]
    _, err = portfolio.replay(sid, trial)
    if err:
        raise HTTPException(400, err)
    return {"id": ds.trade_add(sid, t.date, t.side, t.price, t.shares)}


@app.delete("/api/trades/{trade_id}")
def trade_delete(trade_id: int):
    ds.trade_delete(trade_id)
    return {"ok": True}


@app.get("/api/trades.csv")
def trades_csv():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["股票代號", "名稱", "日期", "買賣", "成交價", "股數"])
    for t in ds.trades():
        w.writerow([t["stock_id"], ds.stock_meta(t["stock_id"])["name"], t["date"],
                    "買進" if t["side"] == "buy" else "賣出", t["price"], t["shares"]])
    name = f"trades-{dt.date.today():%Y%m%d}.csv"
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------- 個股設定 ----------

class Settings(BaseModel):
    category: str | None = None
    trend_profile: str | None = None


@app.put("/api/settings/{stock_id}")
def settings_save(stock_id: str, body: Settings):
    if body.category is not None and body.category != "auto" and body.category not in fundamentals.CATEGORIES:
        raise HTTPException(400, "分類不存在")
    if body.trend_profile is not None and body.trend_profile != "auto" and body.trend_profile not in trend.PROFILES:
        raise HTTPException(400, "參數組不存在")
    return ds.settings_save(stock_id, body.category, body.trend_profile)


app.mount("/", StaticFiles(directory=os.path.join(BASE_DIR, "static"), html=True), name="static")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    url = f"http://127.0.0.1:{port}"
    if os.environ.get("NO_BROWSER") != "1":
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"\n  我的看盤台已啟動：{url}\n  資料來源：{'示範資料' if ds.DEMO else 'FinMind'}"
          f"\n  關掉這個視窗，平台就會停止。\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

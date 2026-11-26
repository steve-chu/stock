"""長線回測：照「策略總表」的價位表操作，近 1／2／3／5 年每碰到一個買點買 5 萬，全部抱到今天。

做法（不偷看未來）：
  1. 從回測起點開始，每個交易日只用「當天以前」的資料，重算一次策略總表：
     恐慌區（歷史回檔、200 日線乖離、估值底線、成交密集區）、壓力、恐慌 1／2／3、回升 1／2。
     趨勢判斷（Weinstein／Wyckoff／Minervini）和過熱訊號每 5 個交易日重算一次。
  2. 隔天照表操作：
     - 恐慌段：試單 → 隔天開盤買；其他價位 → 掛限價，盤中碰到就買（開盤就更低的用開盤價）
     - 回升段：表上顯示「可以加碼」（站回均線且中期不是出貨／空頭）→ 隔天開盤買
     - 過熱「留意／危機」時停止加碼；黑天鵝價位是備用資金，不算進來
  3. 同一種買點（試單、中途、目標區、回升哪條線）買過後，要創新高或過半年、且至少隔 20 個交易日才會再買；
     同一天碰到好幾個買點，只買一次 5 萬。
比較回升段和恐慌段要看「年化」或「買後半年」：越早買的抱越久，「到今天」的報酬天生比較高。
報酬 = 抱到今天、假設今天賣（含股利，扣手續費和證交稅），並和「同一天買 0050 抱到今天」比較。
只用股價、本益比／淨值比、法人與融資資料，這些都在資料庫裡，不連網路。
"""
import bisect

import danger as danger_mod
import strategy
import trend
import zones as zones_mod
from analysis import sma

AMOUNT = 50_000
YEARS = (1, 2, 3, 5)
BUY_FEE = 0.001425
SELL_COST = 0.001425 + 0.003
HIST = 1215          # 分析用的歷史長度（約 5 年，和平台一樣）
MIN_HIST = 250
SLOW_EVERY = 5       # 趨勢、過熱每幾天重算
DAYS_Y = 245         # 一年的交易日
HALF_Y = 120         # 半年的交易日
VERSION = 3          # 規則改了就換版本，舊的快取作廢
ELIG = {"status": "合格", "tone": "bull", "warns": [], "core": True}


def _until(rows, dates, d):
    return rows[:bisect.bisect_right(dates, d)]


def _kind(t):
    """同一段行情裡用來判斷「這種買點買過了沒」：試單／中途（含一般回檔層）／目標區；回升看是哪條均線。"""
    w = t.get("why") or ""
    if t["stage"] == "恐慌段":
        return "試單" if w.startswith("試單") else "目標區" if w == "恐慌目標區" else "中途"
    return "回升:" + w


def _short(t):
    k = _kind(t)
    if t["stage"] == "恐慌段":
        return f"恐慌{t['n']} {k}"
    w = t.get("why") or ""
    m = "半年線" if "MA120" in w else "年線" if "年線" in w else "月線" if "MA20" in w else "季線" if "MA60" in w else ""
    return f"回升{t['n']} {m}".strip()


def ladders(bars, per, inst, mg, profile, start):
    """bars[start:] 每一天收盤後的策略總表（只用當天以前的資料）。回傳 {日期: {"tr": [...], "heat": 等級}}。"""
    pd_ = [r["date"] for r in per]
    id_ = [r["date"] for r in inst]
    md_ = [r["date"] for r in mg]
    c = [b["close"] for b in bars]
    ma120, ma240 = sma(c, 120), sma(c, 240)
    out, regime, dg = {}, None, None
    for j in range(max(start, MIN_HIST), len(bars) - 1):
        w = bars[max(0, j - HIST + 1):j + 1]
        d = bars[j]["date"]
        p_ = _until(per, pd_, d)
        if regime is None or (j - start) % SLOW_EVERY == 0:
            try:
                regime = trend.judge(w, _until(inst, id_, d), _until(mg, md_, d), profile)
            except Exception:
                regime = None
            try:
                dg = danger_mod.judge(w, _until(mg, md_, d), _until(inst, id_, d), p_, (regime or {}).get("state"))
            except Exception:
                dg = None
        try:
            z = zones_mod.build(w, p_, None)
        except Exception:
            continue
        tq = {"ma120": ma120[j], "ma240": ma240[j],
              "ma240_up": bool(ma240[j] and j >= 20 and ma240[j - 20] and ma240[j] > ma240[j - 20])}
        try:
            L = strategy.long_plan(w, None, regime, None, None, z, dg, None, ELIG, tq)
        except Exception:
            continue
        lv = (dg or {}).get("level") if (dg or {}).get("applies") and not (dg or {}).get("late") else "healthy"
        out[d] = {"heat": lv, "tr": [{"stage": t["stage"], "n": t["n"], "why": t["why"], "price": t["price"],
                                      "met": bool(t["met"])} for t in L["tranches"] if t.get("price")]}
    return out


def _div_between(divs, d0, d1):
    """d0 < 除息日 ≤ d1 的現金股利合計（divs 已排序）。"""
    if not divs:
        return 0.0
    ds_ = [d for d, _ in divs]
    i, k = bisect.bisect_right(ds_, d0), bisect.bisect_right(ds_, d1)
    return sum(a for _, a in divs[i:k])


GAP_DAYS = 20       # 同一種買點至少隔 20 個交易日
RESET_DAYS = 120    # 沒創新高的話，半年後才算新的一段行情


def simulate(bars, lad, start):
    """從 start 開始照表操作，回傳每一筆買進。
    同一種買點（試單、中途、目標區、回升哪條線）買過之後，要「創了買進時的新高」或「過了半年」，
    而且至少隔 20 個交易日，才算新的一段行情、可以再買。"""
    trades, last = [], {}            # last[種類] = (買進的 index, 當時近 60 日高點, 之後的最高收盤)
    for j in range(start, len(bars) - 1):
        for k, (bj, pk, hw) in list(last.items()):
            last[k] = (bj, pk, max(hw, bars[j]["close"]))
        L = lad.get(bars[j]["date"])
        if not L or L["heat"] in ("watch", "crisis"):              # 過熱：停止加碼
            continue
        nb = bars[j + 1]
        hits = []
        for t in L["tr"]:
            k = _kind(t)
            if k in last:
                bj, pk, hw = last[k]
                if j - bj < GAP_DAYS or not (hw > pk or j - bj >= RESET_DAYS):
                    continue
            if t["stage"] == "恐慌段":
                if t["met"]:
                    fill, how = nb["open"] or nb["close"], "開盤買"
                elif nb["low"] <= t["price"]:
                    fill, how = min(nb["open"] or t["price"], t["price"]), f"掛 {t['price']:g} 成交"
                else:
                    continue
            elif t["met"]:
                fill, how = nb["open"] or nb["close"], "開盤買"
            else:
                continue
            last[k] = (j, max(b["high"] for b in bars[max(0, j - 59):j + 1]), bars[j]["close"])
            hits.append((fill, t, how))
        if hits:
            # 同一天碰到好幾個買點，只買一次 5 萬（用最低的成交價），名稱合併；有恐慌段就算恐慌段
            fill = min(h[0] for h in hits)
            panic = any(h[1]["stage"] == "恐慌段" for h in hits)
            trades.append({"date": nb["date"], "j": j + 1, "kind": "+".join(_kind(h[1]) for h in hits),
                           "label": "＋".join(_short(h[1]) for h in hits), "side": "down" if panic else "up",
                           "why": f"{bars[j]['date']} 的策略總表：" + "；".join(f"{_short(t)}（{t['why']}）{how}" for _, t, how in hits),
                           "price": round(fill, 2)})
    return trades


def run(bars, lad, divs=None, bench=None, bench_divs=None):
    """lad = ladders() 的結果（可快取）。每個「近 N 年」各自從那天重新開始照表操作，抱到今天。"""
    if len(bars) < MIN_HIST + 2:
        return {"error": f"歷史資料只有 {len(bars)} 天，至少要 {MIN_HIST + 2} 天"}
    last = bars[-1]
    bmap = {b["date"]: b for b in bench or []}
    bdates = [b["date"] for b in bench or []]

    def bench_ret(d_buy):
        if not bench:
            return None
        i = bisect.bisect_left(bdates, d_buy)
        if i >= len(bdates) or not bmap[bdates[i]]["open"]:
            return None
        b0, b1 = bmap[bdates[i]], bmap[bdates[-1]]
        return ((b1["close"] + _div_between(bench_divs, bdates[i], bdates[-1])) * (1 - SELL_COST)
                / (b0["open"] * (1 + BUY_FEE)) - 1) * 100

    def bench_dca(ts, cut):
        """0050 每月無腦買：個股某個月買了幾次，0050 就在那個月第一個交易日開盤買幾次（金額一樣，只差時機和標的）。"""
        if not bench:
            return None
        cnt = {}
        for t in ts:
            cnt[t["date"][:7]] = cnt.get(t["date"][:7], 0) + 1
        n = val = 0
        for m, k in cnt.items():
            i = bisect.bisect_right(bdates, max(cut, m + "-00"))
            if i >= len(bdates) or bdates[i][:7] != m or not bmap[bdates[i]]["open"]:
                continue
            b0 = bmap[bdates[i]]
            f = (bench[-1]["close"] + _div_between(bench_divs, bdates[i], bdates[-1])) * (1 - SELL_COST) / (b0["open"] * (1 + BUY_FEE))
            n += k
            val += k * AMOUNT * f
        return {"n": n, "invested": n * AMOUNT, "value": round(val),
                "total": round((val / (n * AMOUNT) - 1) * 100, 1) if n else None} if n else {"n": 0}

    dates = [b["date"] for b in bars]
    y0 = int(last["date"][:4])
    windows, all_trades = {}, {}
    for y in YEARS:
        cut = f"{y0 - y}{last['date'][4:]}"
        s0 = bisect.bisect_right(dates, cut)
        s = max(s0, MIN_HIST)
        ts = simulate(bars, lad, s)
        for t in ts:
            cost = t["price"] * (1 + BUY_FEE)
            dv = _div_between(divs, t["date"], last["date"])
            t["ret"] = round(((last["close"] + dv) * (1 - SELL_COST) / cost - 1) * 100, 1)
            t["div"] = round(dv, 2)
            br = bench_ret(t["date"])
            t["bench"] = None if br is None else round(br, 1)
            jb = t.pop("j")
            hold = len(bars) - 1 - jb
            # 年化：抱滿半年才算（太短的年化會被放大，沒意義）；買後半年：買進後 120 個交易日的含息報酬
            t["hold"] = hold
            t["cagr"] = round(((1 + t["ret"] / 100) ** (DAYS_Y / hold) - 1) * 100, 1) if hold >= HALF_Y and t["ret"] > -100 else None
            k6 = jb + HALF_Y
            t["f6"] = (round(((bars[k6]["close"] + _div_between(divs, t["date"], bars[k6]["date"])) * (1 - SELL_COST) / cost - 1) * 100, 1)
                       if k6 < len(bars) else None)
        windows[y] = {"from": dates[s] if s < len(dates) else cut, "short": s > s0,
                      **_summary(ts), "dca": bench_dca(ts, dates[s - 1] if s > 0 else cut)}
        all_trades[y] = ts
    return {"trades": all_trades, "summary": windows, "last": last["date"], "close": last["close"],
            "has_divs": bool(divs), "bench": bool(bench), "bench_divs": bool(bench_divs)}


def _one(ts):
    if not ts:
        return {"n": 0}
    rets = sorted(t["ret"] for t in ts)
    vb = [t for t in ts if t["bench"] is not None]
    value = sum(AMOUNT * (1 + r / 100) for r in rets)
    bval = sum(AMOUNT * (1 + t["bench"] / 100) for t in vb)
    cg = [t["cagr"] for t in ts if t.get("cagr") is not None]
    f6 = [t["f6"] for t in ts if t.get("f6") is not None]
    return {"n": len(ts), "success": round(sum(1 for r in rets if r > 0) / len(rets) * 100),
            "cagr": round(sum(cg) / len(cg), 1) if cg else None, "cagr_n": len(cg),
            "f6": round(sum(f6) / len(f6), 1) if f6 else None, "f6_n": len(f6),
            "f6_win": round(sum(1 for x in f6 if x > 0) / len(f6) * 100) if f6 else None,
            "hold": round(sum(t["hold"] for t in ts) / len(ts)),
            "avg": round(sum(rets) / len(rets), 1), "worst": rets[0], "best": rets[-1],
            "beat": round(sum(1 for t in vb if t["ret"] > t["bench"]) / len(vb) * 100) if vb else None,
            "beat_n": sum(1 for t in vb if t["ret"] > t["bench"]), "bench_n": len(vb),
            "bench_avg": round(sum(t["bench"] for t in vb) / len(vb), 1) if vb else None,
            "bench_worst": min(t["bench"] for t in vb) if vb else None,
            "bench_total": round((bval / (AMOUNT * len(vb)) - 1) * 100, 1) if vb else None,
            "invested": AMOUNT * len(ts), "value": round(value), "profit": round(value - AMOUNT * len(ts)),
            "total": round((value / (AMOUNT * len(ts)) - 1) * 100, 1),
            "bench_value": round(bval) if vb and len(vb) == len(ts) else None}


def _summary(ts):
    return {"all": _one(ts), "up": _one([t for t in ts if t["side"] == "up"]),
            "down": _one([t for t in ts if t["side"] == "down"])}


def run_many(series):
    """series = [(stock_id, name, result)]：每檔各自的結果，加上合計。"""
    rows, pooled, dca = [], {y: [] for y in YEARS}, {y: [0, 0] for y in YEARS}
    for sid, name, r in series:
        if r.get("error"):
            continue
        rows.append({"stock_id": sid, "name": name, "summary": {y: r["summary"][y]["all"] for y in YEARS},
                     "dca": {y: r["summary"][y].get("dca") for y in YEARS}})
        for y in YEARS:
            pooled[y] += r["trades"][y]
            dd = r["summary"][y].get("dca") or {}
            if dd.get("n"):
                dca[y][0] += dd["invested"]
                dca[y][1] += dd["value"]
    tot = {y: {**_summary(pooled[y]), "dca": {"n": dca[y][0] // AMOUNT, "invested": dca[y][0], "value": dca[y][1],
                                               "total": round((dca[y][1] / dca[y][0] - 1) * 100, 1) if dca[y][0] else None}}
           for y in YEARS}
    return {"stocks": rows, "total": tot,
            "bench_divs": any(r.get("bench_divs") for _, _, r in series)}

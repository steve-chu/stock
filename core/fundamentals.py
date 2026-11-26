"""股票體質：營收成長、EPS 預估、股利、分類（循環／穩定配息／成長）、估值。

分類和估值都是「依規則自動判斷 + 可手動覆蓋」，每一項都附上原因，方便你檢查。
"""
import datetime as dt
import re

CATEGORIES = {
    "cyclical": {"label": "循環股", "icon": "🔄", "method": "PBR 區間"},
    "stable": {"label": "穩定配息股", "icon": "💰", "method": "殖利率法"},
    "growth": {"label": "成長股", "icon": "📈", "method": "本益比區間"},
    "general": {"label": "一般股", "icon": "📊", "method": "殖利率法"},
}

# 殖利率法：5% 便宜、4% 合理、3% 昂貴
YIELD_BANDS = [("便宜價", 0.05), ("合理價", 0.04), ("昂貴價", 0.03)]


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _pct(a, b):
    return None if not b else (a / b - 1) * 100


def _percentile(vals, p):
    s = sorted(vals)
    if not s:
        return None
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


# ---------- 營收 ----------

def revenue_check(rows):
    monthly = {}
    for r in rows:
        y, m = int(r.get("revenue_year") or 0), int(r.get("revenue_month") or 0)
        if y and m:
            monthly[(y, m)] = _f(r.get("revenue"))
    if not monthly:
        return None
    years = sorted({y for y, _ in monthly})
    annual = [{"year": y, "revenue": sum(monthly.get((y, m), 0) for m in range(1, 13))}
              for y in years if all((y, m) in monthly for m in range(1, 13))]
    for i, a in enumerate(annual):
        a["yoy"] = _pct(a["revenue"], annual[i - 1]["revenue"]) if i else None
    yoys = [a["yoy"] for a in annual if a["yoy"] is not None][-3:]
    passed = None if len(yoys) < 3 else all(y > 0 for y in yoys)   # None = 資料不足，不是沒成長
    # 寬鬆：三年整體成長，最多一年小幅衰退（≥ −5%）
    lenient = None if len(yoys) < 3 else (
        sum(1 for y in yoys if y < 0) <= 1 and all(y >= -5 for y in yoys)
        and annual[-1]["revenue"] > annual[-4]["revenue"] if len(annual) >= 4 else False)

    # 今年累計 vs 去年同期
    ly, lm = max(monthly)
    ytd = sum(monthly.get((ly, m), 0) for m in range(1, lm + 1))
    ytd_prev = sum(monthly.get((ly - 1, m), 0) for m in range(1, lm + 1))
    # 近 12 個月 vs 前 12 個月
    keys = sorted(monthly)
    ttm = sum(monthly[k] for k in keys[-12:]) if len(keys) >= 12 else None
    ttm_prev = sum(monthly[k] for k in keys[-24:-12]) if len(keys) >= 24 else None
    cagr = None
    if len(annual) >= 4 and annual[-4]["revenue"] > 0:
        cagr = ((annual[-1]["revenue"] / annual[-4]["revenue"]) ** (1 / 3) - 1) * 100
    myoy = []
    for (y, m) in keys[-6:]:
        prev = monthly.get((y - 1, m))
        myoy.append({"ym": f"{y}-{m:02d}", "yoy": _pct(monthly[(y, m)], prev) if prev else None})
    last3 = [x["yoy"] for x in myoy[-3:]]
    recent_decline = None if len(last3) < 3 or None in last3 else all(x < 0 for x in last3)
    # 趨勢：不管中間哪一年衰退多少，只看三件事 —— 整體有成長、已經回到之前的高點、現在沒有在衰退
    trend, trend_why = None, None
    if len(annual) >= 4 and cagr is not None:
        peak = max(a["revenue"] for a in annual[-4:-1])
        now_rev = ttm if ttm else annual[-1]["revenue"]
        recovered = now_rev >= peak * 0.97
        ty = _pct(ttm, ttm_prev) if ttm and ttm_prev else None
        not_falling = ty is None or ty > -5
        trend = cagr > 0 and recovered and not_falling
        bad = [x for x, ok in (("3 年整體沒成長", cagr > 0), ("還沒回到之前的營收高點", recovered),
                                ("近 12 個月營收年減超過 5%", not_falling)) if not ok]
        dips = [f"{a['year']} 年 {a['yoy']:+.1f}%" for a in annual[-3:] if a["yoy"] is not None and a["yoy"] < 0]
        trend_why = ("符合：" + ("中間有衰退（" + "、".join(dips) + "）但已經回到高點" if dips else "三年整體成長且在高點附近")) if trend \
            else "不符合：" + "、".join(bad)
    return {
        "monthly_yoy": myoy, "recent_decline": recent_decline, "trend": trend, "trend_why": trend_why,
        "annual": annual[-4:], "passed": passed, "lenient": lenient, "cagr3": cagr,
        "ytd": {"year": ly, "month": lm, "yoy": _pct(ytd, ytd_prev)},
        "ttm_yoy": _pct(ttm, ttm_prev) if ttm and ttm_prev else None,
    }


# ---------- EPS ----------

def _quarters(rows):
    q = {}
    for r in rows:
        if r.get("type") != "EPS":
            continue
        d = dt.date.fromisoformat(r["date"][:10])
        q[(d.year, (d.month - 1) // 3 + 1)] = _f(r.get("value"))
    return dict(sorted(q.items()))


# ---------- 除權、分割、減資：換算成現在的股數 ----------

NI_TYPE = "EquityAttributableToOwnersOfParent"   # 歸屬母公司淨利（EPS 的分子）
SHARE_JUMP = 1.15    # 相鄰兩季股數差超過 15% 才算股數大變（可轉債轉換、員工認股只有幾 %）
K_TOL = 0.12         # 股價跳空倍數 vs 財報股數倍數：開盤價可能偏離參考價 10%，所以容許 12%


def _qkey(date):
    d = dt.date.fromisoformat(str(date)[:10])
    return d.year, (d.month - 1) // 3 + 1


def _qstart(k):
    return dt.date(k[0], k[1] * 3 - 2, 1)


def _qend(k):
    return dt.date(k[0], k[1] * 3, 31 if k[1] in (1, 4) else 30)


def _shares(rows):
    """每季股數 = 歸屬母公司淨利 ÷ EPS（EPS 太小時四捨五入誤差大，不用）。"""
    eps, ni = {}, {}
    for r in rows:
        t = r.get("type")
        if t == "EPS":
            eps[_qkey(r["date"])] = _f(r.get("value"))
        elif t == NI_TYPE:
            ni[_qkey(r["date"])] = _f(r.get("value"))
    sh = {k: ni[k] / e for k, e in eps.items() if abs(e) >= 0.1 and ni.get(k) and (ni[k] > 0) == (e > 0)}
    return dict(sorted(sh.items())), bool(ni)


def corporate_actions(eps_rows, price_events):
    """股票股利、分割、減資會讓每股數字整個變一個倍數。兩個獨立來源都要對得上才換算：
    1. 股價：開盤跳空超過 11.5%（交易所）  2. 財報：淨利 ÷ EPS 算出的股數，相鄰兩季跳動同樣倍數（公司）
    對得上 → 用財報股數的確切倍數換算；對不上 → 不換算，標記起來讓估值把會出錯的方法拿掉。"""
    qs_all = sorted({_qkey(r["date"]) for r in eps_rows if r.get("type") == "EPS"})
    if not price_events or not qs_all:
        return None
    # 財報第一季公布以前的事件：所有財報都已經是新股數，不用換算（也看不到股數跳動）
    first = (_qend(qs_all[0]) + dt.timedelta(days=100)).isoformat()
    evs = [e for e in price_events if e["date"] > first]
    if not evs:
        return None
    shares, has_ni = _shares(eps_rows)
    sk = list(shares)
    jumps = [(a, b, shares[b] / shares[a]) for a, b in zip(sk, sk[1:])
             if shares[a] > 0 and not (1 / SHARE_JUMP <= shares[b] / shares[a] <= SHARE_JUMP)]
    ok, pending, bad, used = [], [], [], set()
    for e in evs:
        d = dt.date.fromisoformat(e["date"])
        m = next((j for j in jumps if j not in used and _qstart(j[0]) <= d <= _qend(j[1]) + dt.timedelta(days=100)
                  and abs(j[2] / e["k_p"] - 1) <= K_TOL), None)
        if m:
            used.add(m)
            ok.append({"date": e["date"], "k": round(m[2], 4), "k_p": e["k_p"], "last_old": list(m[0])})
        elif d > _qend(qs_all[-1]):
            pending.append({"date": e["date"], "k_p": e["k_p"]})   # 事件之後還沒有新財報，股數還無法確認
        else:
            bad.append({"date": e["date"], "k_p": e["k_p"]})
    f = lambda k: f"{k:.2f}".rstrip("0").rstrip(".")
    notes = []
    if ok:
        notes.append("；".join(f"{e['date']} 除權／分割（1 股變 {f(e['k'])} 股）" for e in ok)
                     + "。之前的每季 EPS、股利、除息價都已除以這個倍數，換算成現在的股數，才能和現在的股價比；配息率、殖利率不受影響")
    if pending:
        notes.append("；".join(f"{e['date']} 股價跳空（約 1 股變 {f(e['k_p'])} 股）" for e in pending)
                     + "，像是除權或分割，但還沒有新一季財報能確認股數。EPS、股利還是舊股數，和現在股價比會差一個倍數，"
                     "所以殖利率法和 PEG 先不採用，等下一季財報出來會自動換算")
    if bad:
        notes.append("；".join(f"{e['date']} 股價跳空（約 1 股變 {f(e['k_p'])} 股）" for e in bad)
                     + ("，但財報股數對不上，無法確認換算倍數" if has_ni else "，但沒有淨利資料可以確認股數（按一次「全部更新」重抓財報）")
                     + "。EPS、股利沒有換算，殖利率法和 PEG 先不採用，請自行確認")
    return {"status": "unverified" if bad else "pending" if pending else "ok",
            "events": ok, "pending": pending, "unverified": bad, "note": "。".join(notes)}


def _split_factor(ok_events, date):
    """這個日期（含）以前的每股數字要除以多少：之後每一次確認過的事件倍數相乘。"""
    f = 1.0
    for e in ok_events:
        if date and date <= e["date"]:
            f *= e["k"]
    return f


def adjust_quarters(quarters, ok_events):
    out = {}
    for k, v in quarters.items():
        f = 1.0
        for e in ok_events:
            if k <= tuple(e["last_old"]):
                f *= e["k"]
        out[k] = round(v / f, 2) if f != 1.0 else v
    return out


def annual_eps(quarters):
    years = sorted({y for y, _ in quarters})
    return {y: round(sum(quarters[(y, k)] for k in range(1, 5)), 2)
            for y in years if all((y, k) in quarters for k in range(1, 5))}


def _monthly(rev_rows):
    m = {}
    for r in rev_rows or []:
        y, mo = int(r.get("revenue_year") or 0), int(r.get("revenue_month") or 0)
        if y and mo:
            m[(y, mo)] = _f(r.get("revenue"))
    return m


def _rev_estimate(quarters, monthly, ly, done, rest, conservative=False):
    """營收推估：剩下的季度 EPS = 該季營收 × 最近一季「每億營收賺多少 EPS」。
    該季已公布的月份用實際營收，還沒公布的月份用最近一個月的營收。
    conservative：營收突然大增時，新增的營收不一定一樣好賺（例如低毛利的組裝），獲利率用最近一季和近四季平均較低的。"""
    lq = max(done)
    q_rev = lambda y, q: sum(monthly.get((y, mo), 0) for mo in range(q * 3 - 2, q * 3 + 1))
    full = lambda y, q: all((y, mo) in monthly for mo in range(q * 3 - 2, q * 3 + 1))
    base_rev = q_rev(ly, lq)
    if not monthly or base_rev <= 0 or not full(ly, lq):
        return None
    ratio = quarters[(ly, lq)] / (base_rev / 1e8)            # 每 1 億營收對應的 EPS
    cons_note = ""
    if conservative:
        recent = [k for k in sorted(quarters)[-4:] if full(*k) and q_rev(*k) > 0]
        if len(recent) >= 3:
            avg = sum(quarters[k] / (q_rev(*k) / 1e8) for k in recent) / len(recent)
            if avg < ratio:
                cons_note = f"；營收大增時新營收不一定一樣好賺，獲利率改用近 {len(recent)} 季平均（比 Q{lq} 低 {(1 - avg / ratio) * 100:.0f}%）"
                ratio = avg
    last_m = max(monthly)
    parts, est_rest = [], 0.0
    for q in rest:
        known = [(ly, mo) for mo in range(q * 3 - 2, q * 3 + 1) if (ly, mo) in monthly]
        rev = sum(monthly[k] for k in known) + monthly[last_m] * (3 - len(known))
        e = rev / 1e8 * ratio
        est_rest += e
        parts.append(f"Q{q} 營收約 {rev / 1e8:,.0f} 億（已公布 {len(known)} 個月，其餘用最近一個月 {monthly[last_m] / 1e8:,.0f} 億）→ EPS {e:.2f}")
    unit = next(((u, lab) for u, lab in ((1, "1 億"), (100, "100 億"), (1000, "1,000 億")) if ratio * u >= 0.1), (1000, "1,000 億"))
    return est_rest, (f"用 Q{lq} 的獲利率推：Q{lq} 營收 {base_rev / 1e8:,.0f} 億賺 EPS {quarters[(ly, lq)]:.2f}"
                      f"（換算採用每 {unit[1]}營收 {ratio * unit[0]:.3f} 元{cons_note}）。" + "；".join(parts))


def estimate_eps(quarters, monthly=None):
    """你的方法：今年已公布季度對比去年同期的成長率，套用到剩下的季度。
    成長率太極端（> +50% 或 < −30%，常見於循環股谷底反彈）時，改用營收 × 最近一季獲利率推估。"""
    if not quarters:
        return None
    ly = max(y for y, _ in quarters)
    done = [k for k in range(1, 5) if (ly, k) in quarters]
    rest = [k for k in range(1, 5) if k not in done]
    ytd = sum(quarters[(ly, k)] for k in done)
    detail = {"year": ly, "quarters": [{"q": k, "eps": quarters.get((ly, k)),
                                        "prev": quarters.get((ly - 1, k))} for k in range(1, 5)]}
    if not rest:
        return {**detail, "estimate": round(ytd, 2), "method": "全年已公布",
                "note": f"{ly} 年四季都已公布，直接用實際 EPS"}
    prev_same = [quarters.get((ly - 1, k)) for k in done]
    prev_rest = [quarters.get((ly - 1, k)) for k in rest]
    qs = "、".join(f"Q{k}" for k in done)
    why = None
    if None not in prev_same and None not in prev_rest:
        ps, pr = sum(prev_same), sum(prev_rest)
        if ps > 0 and pr > 0 and ytd > 0:
            g = ytd / ps - 1
            if -0.30 <= g <= 0.50:
                est_rest = pr * (1 + g)
                r = _rev_estimate(quarters, monthly or {}, ly, done, rest)
                # 營收突然大跳（或大掉）時，成長率推估會跟不上轉折：兩者差超過 25% 就改用營收推估
                if r and r[0] > 0 and abs(r[0] / est_rest - 1) > 0.25:
                    why = (f"{qs} 成長率 {g * 100:+.0f}% 推出剩餘季度 EPS {est_rest:.2f}，"
                           f"但最近營收換算是 {r[0]:.2f}，差很多（營收出現轉折）")
                    if r[0] > est_rest:   # 營收往上跳：保守一點，不假設新增的營收一樣好賺
                        rc = _rev_estimate(quarters, monthly or {}, ly, done, rest, conservative=True)
                        if rc and rc[0] > 0:
                            return {**detail, "estimate": round(ytd + rc[0], 2), "method": "營收推估",
                                    "note": why + "，改用營收推估。" + f"{qs} 合計 {ytd:.2f}；" + rc[1]}
                else:
                    est = ytd + est_rest
                    return {**detail, "estimate": round(est, 2), "growth": round(g * 100, 1),
                            "method": "成長率推估",
                            "note": f"{qs} 合計 {ytd:.2f}，去年同期 {ps:.2f}，成長 {g * 100:+.1f}%；"
                                    f"去年剩餘季度 {pr:.2f} × {1 + g:.2f} = {est_rest:.2f}"}
            else:
                why = f"{qs} 比去年同期成長 {g * 100:+.0f}%，太極端，照比例推會失真"
    r = _rev_estimate(quarters, monthly or {}, ly, done, rest)
    if r and r[0] > 0:
        est_rest, note = r
        return {**detail, "estimate": round(ytd + est_rest, 2), "method": "營收推估",
                "note": (why + "，改用營收推估。" if why else "") + f"{qs} 合計 {ytd:.2f}；" + note
                        + "。獲利率若繼續變好（漲價循環），實際可能更高"}
    lq = quarters[(ly, max(done))]
    return {**detail, "estimate": round(ytd + lq * len(rest), 2), "method": "最近一季推估",
            "note": (why + "，" if why else "") + f"剩下 {len(rest)} 季用最近一季 EPS {lq:.2f} 推估"}


# ---------- 股利 ----------

def _close_before(closes, d):
    """除息日前一個交易日的收盤價（殖利率就是用這個價格算的）。"""
    import bisect
    if not closes or not d:
        return None
    i = bisect.bisect_left(closes, (d[:10],)) - 1
    return closes[i] if i >= 0 else None


def etf_dividends(rows, closes, adj_divs, close, last_date, splits=None):
    """ETF 配息紀錄：每次配多少、除息前一天的價格、當次殖利率；每年合計；近 12 個月殖利率。
    表格用當時的真實價格和金額（殖利率是比例，不受分割影響）；近 12 個月殖利率用換算成現在單位數的配息 ÷ 現價。"""
    import datetime as _dt
    ev = []
    for r in rows:
        cash = _f(r.get("CashEarningsDistribution")) + _f(r.get("CashStatutorySurplus"))
        ex = str(r.get("CashExDividendTradingDate") or "")[:10]
        if cash <= 0 or len(ex) != 10 or ex > last_date:
            continue
        px = _close_before(closes, ex)
        ev.append({"ex": ex, "cash": round(cash, 4), "price": px[1] if px else None,
                   "yield": round(cash / px[1] * 100, 2) if px and px[1] else None})
    ev.sort(key=lambda e: e["ex"])
    if not ev:
        return None
    years = {}
    for e in ev:
        y = years.setdefault(int(e["ex"][:4]), {"year": int(e["ex"][:4]), "n": 0, "cash": 0.0, "yield": 0.0})
        y["n"] += 1
        y["cash"] = round(y["cash"] + e["cash"], 4)
        y["yield"] = round(y["yield"] + (e["yield"] or 0), 2)
    cut = (_dt.date.fromisoformat(last_date) - _dt.timedelta(days=365)).isoformat()
    ttm_n = sum(1 for e in ev if e["ex"] > cut)
    ttm_cash = sum(a for d, a in (adj_divs or []) if cut < d <= last_date)
    freq = {12: "月配", 6: "雙月配", 4: "季配", 2: "半年配", 1: "年配"}.get(ttm_n, f"一年 {ttm_n} 次" if ttm_n else "近一年沒有配息")
    this_y = int(last_date[:4])
    full = [years[y]["yield"] for y in sorted(years) if this_y - 5 <= y < this_y]
    return {"events": ev, "years": [years[y] for y in sorted(years)], "freq": freq, "ttm_n": ttm_n,
            "ttm_cash": round(ttm_cash, 4), "ttm_yield": round(ttm_cash / close * 100, 2) if close and ttm_cash else None,
            "avg5": round(sum(full) / len(full), 2) if full else None, "avg5_n": len(full),
            "split_note": ("；".join(f"{e['date']} 分割／除權（約 1 變 {e['k_p']:.2f}）" for e in splits)
                           + "：表格是當時真正的配息和價格，近 12 個月殖利率已換算成現在的單位數") if splits else None}


def dividends(rows, eps_by_year, closes=None, splits=None):
    """splits = 已確認的除權／分割事件：事件以前的每股股利和除息價都換算成現在的股數。"""
    by_year, cnt, seq, exd = {}, {}, [], {}
    splits = splits or []
    for r in rows:
        txt = str(r.get("year") or "")
        m = re.search(r"(\d+)\s*年", txt)
        if not m:
            continue
        y = int(m.group(1)) + 1911
        amt = _f(r.get("CashEarningsDistribution")) + _f(r.get("CashStatutorySurplus"))
        ex = str(r.get("CashExDividendTradingDate") or "")[:10]
        # 除息日（沒有就用公告日）在除權那天或之前 → 是發給舊股數的，要換算
        sf = _split_factor(splits, ex if len(ex) == 10 else str(r.get("date") or "")[:10]) if splits else 1.0
        amt /= sf
        by_year[y] = by_year.get(y, 0) + amt
        if amt > 0 and len(ex) == 10:
            px = _close_before(closes, ex)
            if px:
                exd.setdefault(y, []).append((ex, amt, px[1] / sf, px[0]))
        if amt > 0:
            cnt[y] = cnt.get(y, 0) + 1
            q = re.search(r"第\s*(\d)\s*季", txt)
            h = 2 if "下半" in txt else 1 if "上半" in txt else 0
            seq.append(((y, int(q.group(1)) if q else h * 2 if h else 4), amt, txt))
    out = []
    for y in sorted(by_year):
        e = eps_by_year.get(y)
        ex = exd.get(y) or []
        # 當時殖利率 = 每次配息 ÷ 除息前一天收盤價，全年加總（季配、半年配的每一次都用當時的股價）
        yld = round(sum(a / p * 100 for _, a, p, _ in ex), 2) if ex else None
        avg_px = round(sum(p for _, _, p, _ in ex) / len(ex), 2) if ex else None
        out.append({"year": y, "cash": round(by_year[y], 2), "eps": e,
                    "payout": round(by_year[y] / e * 100, 1) if e and e > 0 else None,
                    "ex_price": avg_px, "ex_n": len(ex), "ex_yield": yld,
                    "ex_dates": [d for d, _, _, _ in ex],
                    # 這年度的配息都除息了，而且次數不少於前一年（季配股年中只配了 1、2 次時不算完整）
                    "ex_done": len(ex) == cnt.get(y, 0) and cnt.get(y, 0) >= cnt.get(y - 1, 0)})
    streak = 0
    for d in reversed(out):
        if d["cash"] > 0:
            streak += 1
        else:
            break
    payouts = [d["payout"] for d in out[-3:] if d["payout"] is not None]
    # 最新股利年化：季配 = 最新一季 × 4、半年配 = 最新一次 × 2、年配 = 最近一年合計（已宣告的，不是預估）
    latest = None
    if seq:
        seq.sort(key=lambda x: x[0])
        (ly, _), amt, txt = seq[-1]
        full = [y for y in cnt if y < ly]
        n = cnt[max(full)] if full else cnt[ly]
        if n >= 2:
            latest = {"cash": round(amt * n, 2), "label": f"{txt} {amt:.2f} 元 × {n}"}
        else:
            latest = {"cash": round(by_year[ly], 2), "label": f"{ly - 1911} 年度 {by_year[ly]:.2f} 元"}
    last_pay = next((d["payout"] for d in reversed(out) if d["payout"] is not None), None)
    return {"history": out[-5:], "streak": streak, "latest": latest, "last_payout": last_pay,
            "avg_payout": round(sum(payouts) / len(payouts), 1) if payouts else None,
            # 近 5 年配息率中位數：某一年突然配很高（例如 78%）也不會被拉偏
            "med_payout": round(_percentile(p5, .5), 1) if (p5 := [d["payout"] for d in out[-5:] if d["payout"] is not None]) else None,
            "n_payout": len(p5)}


# ---------- 分類 ----------

def classify(annual, rev, div, latest_yield, quarters=None, eps_mixed=False):
    years = sorted(annual)[-5:]
    vals = [annual[y] for y in years]
    reasons = {"cyclical": [], "growth": [], "stable": []}
    if eps_mixed:      # 除權後股數沒確認：EPS 新舊股數混在一起，「大跌」可能是假的，不拿來判斷循環股
        quarters = None
    if vals and eps_mixed and min(vals) <= 0:
        # 股數沒確認時 EPS 的「幅度」不能比，但「有沒有虧損」看正負號就好，不受股數影響
        reasons["cyclical"].append(f"近 {len(vals)} 年有虧損年度（EPS 最低 {min(vals):.2f}）")
    if vals and not eps_mixed:
        lo, hi = min(vals), max(vals)
        # 只看「高低差很大」會把一路成長的公司（例如 8 → 47）也誤判成循環股；
        # 循環股的特徵是「會大跌」：有虧損年度，或某一年 EPS 比前一年少 40% 以上
        drops = [(years[i], vals[i] / vals[i - 1] - 1) for i in range(1, len(vals)) if vals[i - 1] > 0]
        worst = min(drops, key=lambda x: x[1], default=None)
        if lo <= 0:
            reasons["cyclical"].append(f"近 {len(vals)} 年有虧損年度（EPS 最低 {lo:.2f}）")
        elif worst and worst[1] <= -0.4:
            reasons["cyclical"].append(f"{worst[0]} 年 EPS 比前一年少 {-worst[1] * 100:.0f}%（近 {len(vals)} 年最高 {hi:.2f}、最低 {lo:.2f}）")
    if quarters and not reasons["cyclical"]:
        # 年度加總會把波動抹平，改看單季：同一季比去年掉 60% 以上、又有某季比去年多 150% 以上 → 循環股
        ks = sorted(quarters)[-16:]
        yoy = [(k, quarters[k] / quarters[(k[0] - 1, k[1])] - 1) for k in ks
               if quarters.get((k[0] - 1, k[1])) and quarters[(k[0] - 1, k[1])] > 0]
        drop = min(yoy, key=lambda x: x[1], default=None)
        jump = max(yoy, key=lambda x: x[1], default=None)
        if drop and jump and drop[1] <= -0.6 and jump[1] >= 1.5:
            reasons["cyclical"].append(f"單季 EPS 大起大落：{drop[0][0]} Q{drop[0][1]} 比去年同季 {drop[1] * 100:+.0f}%，"
                                       f"{jump[0][0]} Q{jump[0][1]} 比去年同季 {jump[1] * 100:+.0f}%")
    cagr = rev and rev.get("cagr3")
    if cagr is not None and cagr >= 15:
        low_yield = latest_yield is not None and latest_yield < 3
        low_payout = div["avg_payout"] is not None and div["avg_payout"] < 50
        if low_yield or low_payout:
            why = f"殖利率 {latest_yield:.1f}%" if low_yield else f"配息率 {div['avg_payout']:.0f}%"
            reasons["growth"].append(f"近 3 年營收年複合成長 {cagr:.0f}%，{why}偏低（盈餘多留著擴張）")
    pays = [d["payout"] for d in div["history"] if d.get("payout") is not None]
    if div["streak"] >= 5 and vals and min(vals) > 0 and max(vals) / min(vals) < 2:
        reasons["stable"].append(f"連續 {div['streak']} 年配現金股利，EPS 最高與最低差距不到 2 倍")
    elif div["streak"] >= 5 and len(pays) >= 4 and sum(1 for x in pays if x >= 40) >= len(pays) - 1:
        reasons["stable"].append(f"連續 {div['streak']} 年配現金股利，近 {len(pays)} 年配息率 {min(pays):.0f}%–{max(pays):.0f}%，"
                                 "賺越多配越多（配息政策穩定）")

    matched = [k for k in ("cyclical", "growth", "stable") if reasons[k]]
    primary = matched[0] if matched else "general"
    general_reason = []
    if not matched:
        general_reason.append("不符合循環、成長、穩定配息任一條件")
        if not vals:
            general_reason.append("EPS 資料不足")
    return {"auto": primary, "secondary": matched[1:],
            "reasons": reasons.get(primary) or general_reason,
            "secondary_reasons": {k: reasons[k] for k in matched[1:]},
            "eps_years": [{"year": y, "eps": annual[y]} for y in years]}


# ---------- 估值 ----------

def _zone(price, bands):
    """bands 由低到高：便宜、合理、昂貴。"""
    cheap, fair, rich = (b["price"] for b in bands)
    if price <= cheap: return "便宜", "bull"
    if price <= fair: return "合理偏低", "bull"
    if price <= rich: return "合理偏高", "neutral"
    return "昂貴", "bear"


def valuations(close, est, div, per_rows):
    out = {}
    eps = est and est.get("estimate")

    # 殖利率法：預估明年股利（今年預估 EPS × 近 3 年平均配息率）÷ 這檔自己過去 5 年的殖利率區間
    # 已宣告的股利是去年獲利發的；股價反映的是今年獲利 → 用預估股利算「預估殖利率」，漲多了殖利率就被稀釋
    pay = div.get("med_payout") or div["avg_payout"]
    pay_lab = f"近 {div.get('n_payout')} 年配息率中位數" if div.get("med_payout") else "近 3 年平均配息率"
    yh = [_f(r.get("dividend_yield")) for r in per_rows if _f(r.get("dividend_yield")) > 0][-245 * 5:]
    cash = eps * pay / 100 if eps and eps > 0 and pay else None
    lat = div.get("latest")
    if len(yh) >= 245 and yh[-1] > 0:
        trail = close * yh[-1] / 100                  # 交易所殖利率背後的近一年股利
        if cash:
            base, base_lab = cash, f"預估明年股利 = 今年預估 EPS {eps:.2f} × {pay_lab} {pay:.0f}% = {cash:.2f} 元"
        elif lat and lat["cash"] > 0:
            base, base_lab = lat["cash"], f"沒有 EPS 預估，改用已宣告股利 {lat['label']} = {lat['cash']:.2f} 元"
        else:
            base, base_lab = trail, f"沒有 EPS 預估，改用近一年實際股利 {trail:.2f} 元"
        # 合理 = 這檔近 5 年殖利率中位數；便宜 / 昂貴 = 中位數 ± 1%（股民習慣的算法）
        # 殖利率很低的股票（中位數 < 2.5%）±1% 會差太多倍，改用中位數的 ±40%
        mid_y = _percentile(yh, .5)
        step, step_lab = 1.0, "1%"
        bands = []
        for lab, y, note in (("便宜價", mid_y + step, f"中位數 +{step:g}%"), ("合理價", mid_y, "近 5 年中位數"),
                             ("昂貴價", mid_y - step, f"中位數 −{step:g}%")):
            bands.append({"label": lab, "rate": round(y / 100, 4), "note": note, "price": round(base / (y / 100), 2)})
        cur_y = base / close * 100
        rank = sum(1 for h in yh if h <= cur_y) / len(yh) * 100
        z, tone = _zone(close, bands)
        yrs = round(len(yh) / 245, 1)
        f = (f"{base_lab}。合理殖利率 = 近 {yrs:g} 年中位數 {mid_y:.2f}%（範圍 {min(yh):.2f}%–{max(yh):.2f}%），便宜／昂貴 = 中位數 ± {step_lab}。"
             f"目前預估殖利率 {base:.2f} ÷ {close:g} = {cur_y:.2f}%（第 {rank:.0f} 百分位，越高越便宜）")
        if cash and lat and lat["cash"] > 0:
            f += f"。參考：用已宣告股利 {lat['cash']:.2f} 元算，合理價 {lat['cash'] / bands[1]['rate']:.1f}"
        recent = _percentile(yh[-245:], .5)
        trend, unfit = None, None
        if recent < bands[1]["rate"] * 100 * 0.75 and rank < 30:
            trend = (f"近一年殖利率中位數 {recent:.2f}% 明顯低於 5 年中位數，目前預估殖利率也還在歷史低檔（第 {rank:.0f} 百分位），"
                     "代表股價漲得比股利快（市場給更高評價），歷史殖利率區間可能不適用，請搭配本益比看")
            unfit = "殖利率長期往下，歷史區間失準"
        elif recent < bands[1]["rate"] * 100 * 0.75:
            trend = (f"近一年殖利率中位數 {recent:.2f}% 偏低（股價曾經大漲），但用預估股利算，目前殖利率已回到歷史區間"
                     f"（第 {rank:.0f} 百分位），這個方法仍可參考")
        elif recent > bands[1]["rate"] * 100 * 1.25:
            trend = (f"近一年殖利率中位數 {recent:.2f}% 明顯高於 5 年中位數：可能是股價跌了，也可能是市場不看好未來股利，"
                     "要搭配營收、EPS 一起看")
        out["yield"] = {"name": "殖利率法", "bands": bands, "zone": z, "tone": tone, "formula": f,
                        "implied_yield": round(cur_y, 2), "history": True, "current": round(cur_y, 2), "rank": round(rank), "years": yrs,
                        "range": [round(min(yh), 2), round(max(yh), 2)], "trend_note": trend, "unfit": unfit,
                        "median": round(mid_y, 2)}
    elif cash:
        bands = [{"label": lab, "rate": r, "price": round(cash / r, 2)} for lab, r in YIELD_BANDS]
        z, tone = _zone(close, bands)
        out["yield"] = {"name": "殖利率法", "bands": bands, "zone": z, "tone": tone,
                        "formula": f"殖利率歷史不足 1 年，暫用固定 5／4／3%。預估明年股利 = 預估 EPS {eps:.2f} × {pay_lab} {pay:.0f}% = {cash:.2f} 元",
                        "implied_yield": round(cash / close * 100, 2)}
    else:
        out["yield"] = {"name": "殖利率法", "unavailable": "預估 EPS 為負或沒有配息紀錄，無法計算"}

    # PBR 區間
    pbr = [(_f(r.get("PBR")), r["date"]) for r in per_rows if _f(r.get("PBR")) > 0]
    if len(pbr) > 120:
        hist = [p for p, _ in pbr]
        cur = hist[-1]
        bvps = close / cur
        qs = [("便宜價", .1), ("合理價", .5), ("昂貴價", .9)]
        bands = [{"label": lab, "pbr": round(_percentile(hist, q), 2),
                  "price": round(_percentile(hist, q) * bvps, 2)} for lab, q in qs]
        rank = sum(1 for h in hist if h <= cur) / len(hist) * 100
        z, tone = _zone(close, bands)
        f = f"每股淨值約 {bvps:.2f}，目前 PBR {cur:.2f}，位於近 {len(hist) // 245 or 1} 年第 {rank:.0f} 百分位"
        roes = [_f(r.get("PBR")) / _f(r.get("PER")) * 100 for r in per_rows if _f(r.get("PBR")) > 0 and 0 < _f(r.get("PER")) < 200]
        note, unfit, roe_now, roe_med = None, None, None, None
        if len(roes) > 245:
            roe_now = _percentile(roes[-20:], .5)
            roe_med = _percentile(roes[-245 * 5:], .5)
            f += f"。ROE（PBR ÷ 本益比推算）現在約 {roe_now:.1f}%，5 年中位數 {roe_med:.1f}%"
            if roe_med > 0 and abs(roe_now / roe_med - 1) > 0.15:
                up = roe_now > roe_med
                note = (f"ROE 比過去{'高' if up else '低'}很多（{roe_med:.0f}% → {roe_now:.0f}%）。公司越會賺錢，PBR 本來就該越高"
                        f"（PBR ≈ ROE × 本益比），所以歷史 PBR 區間會{'高估貴的程度' if up else '低估風險'}，參考就好")
                unfit = f"ROE 從 {roe_med:.0f}% 變成 {roe_now:.0f}%，歷史 PBR 失準"
        out["pbr"] = {"name": "PBR 區間", "bands": bands, "zone": z, "tone": tone, "formula": f, "trend_note": note, "unfit": unfit,
                      "roe_now": roe_now, "roe_med": roe_med,
                      "current": cur, "rank": round(rank), "years": round(len(hist) / 245, 1)}
    else:
        out["pbr"] = {"name": "PBR 區間", "unavailable": "淨值比歷史資料不足"}

    # 本益比區間：歷史本益比（過去四季 EPS）× 過去四季 EPS，兩邊同一種 EPS；預估 EPS 另列參考
    per_all = [_f(r.get("PER")) for r in per_rows if 0 < _f(r.get("PER")) < 200]
    per = per_all[-245 * 5:]
    cur_per = _f(per_rows[-1].get("PER")) if per_rows else 0
    if len(per) > 120 and 0 < cur_per < 200:
        ttm = close / cur_per
        qs = [("便宜價", .2), ("合理價", .5), ("昂貴價", .8)]
        bands = [{"label": lab, "per": round(_percentile(per, q), 1),
                  "price": round(_percentile(per, q) * ttm, 2)} for lab, q in qs]
        z, tone = _zone(close, bands)
        rank = sum(1 for h in per if h <= cur_per) / len(per) * 100
        f = (f"近 {round(len(per) / 245, 1):g} 年本益比 20／50／80 百分位 = {bands[0]['per']}／{bands[1]['per']}／{bands[2]['per']} 倍，"
             f"× 過去四季 EPS {ttm:.2f}。目前本益比 {cur_per:.1f} 倍（第 {rank:.0f} 百分位）")
        if eps and eps > 0:
            f += f"。參考：用今年預估 EPS {eps:.2f}，合理價約 {bands[1]['per'] * eps:.0f}"
            prev = [q.get("prev") for q in (est.get("quarters") or [])]
            last_year = sum(prev) if prev and None not in prev else None
            g = (eps / last_year - 1) * 100 if last_year and last_year > 0 else None
            if g and g > 0:
                f += f"；今年預估 EPS 比去年 {last_year:.2f} 成長 {g:.0f}%"
                f += "（PEG 見「PEG 成長估值」）"
        out["per"] = {"name": "本益比區間", "bands": bands, "zone": z, "tone": tone, "formula": f,
                      "current": cur_per, "rank": round(rank)}
    else:
        out["per"] = {"name": "本益比區間", "unavailable": "虧損或本益比歷史不足"}
    return out


LOW_YIELD = 2.5   # 近 5 年殖利率中位數低於這個 → 殖利率法不採用
PEG_BANDS = (("便宜價", 0.8), ("合理價", 1.0), ("昂貴價", 1.5))
PEG_G_CAP = 25.0   # 成長率上限（%）：避免一年爆發就把合理價拉到天上


def peg_valuation(close, est, annual, per_hi=None):
    """PEG 成長估值：合理本益比 = 成長率（PEG = 1）。成長率取「近 3 年 EPS 年複合成長」和「今年預估 EPS 成長」較低者，上限 25%。"""
    name = "PEG 成長估值"
    eps = (est or {}).get("estimate")
    if not eps or eps <= 0:
        return {"name": name, "unavailable": "預估 EPS 為負或沒有資料，無法計算"}
    y = est["year"]
    base, last = annual.get(y - 3), annual.get(y - 1)
    cagr = ((eps / base) ** (1 / 3) - 1) * 100 if base and base > 0 else None
    this_g = (eps / last - 1) * 100 if last and last > 0 else None
    gs = [g for g in (cagr, this_g) if g is not None]
    if not gs:
        return {"name": name, "unavailable": "EPS 歷史不足 3 年，無法算成長率"}
    g = min(gs)
    parts = [f"近 3 年 EPS 年複合成長 {cagr:.0f}%" if cagr is not None else None,
             f"今年預估比去年 {this_g:+.0f}%" if this_g is not None else None]
    why = "、".join(x for x in parts if x)
    if g < 3:
        return {"name": name, "stalled": True,
                "unavailable": f"{why}：成長暫停或正在轉折，PEG 不適用。這時候看公司財測（新業務何時放量），不要看估值數字"}
    gp = min(g, PEG_G_CAP)
    # 市場從來沒給過這麼高的本益比，就不假設以後會給：合理本益比不超過這檔自己近 5 年第 90 百分位
    capped = bool(per_hi and gp > per_hi)
    fair = min(gp, per_hi) if per_hi else gp
    bands = [{"label": lab, "peg": k, "per": round(k * fair, 1), "price": round(k * fair * eps, 2)} for lab, k in PEG_BANDS]
    z, tone = _zone(close, bands)
    peg_now = close / eps / gp
    f = (f"成長率取較保守的：{why} → {g:.0f}%" + (f"，超過上限改用 {PEG_G_CAP:.0f}%" if g > PEG_G_CAP else "") +
         (f"。PEG 1 × {gp:.0f} = {gp:.0f} 倍，但這檔近 5 年本益比很少超過 {per_hi:.1f} 倍（第 90 百分位），合理本益比改用 {fair:.1f} 倍"
          if capped else f"。合理本益比 = PEG 1 × {gp:.0f} = {gp:.0f} 倍") + f"，× 今年預估 EPS {eps:.2f}。"
         f"目前本益比 {close / eps:.1f} 倍、PEG {peg_now:.2f}（< 1 代表成長撐得起本益比）")
    return {"name": name, "bands": bands, "zone": z, "tone": tone, "formula": f, "growth": round(g, 1),
            "peg_now": round(peg_now, 2), "per_capped": capped}


METHOD_KEY = {"cyclical": "pbr", "stable": "yield", "growth": "per", "general": "yield"}


REV_RULES = {"strict": "營收三年每年都成長", "lenient": "營收三年整體成長（容許一年 ≤5% 衰退）",
             "trend": "營收趨勢向上（允許衰退年，但要回到高點、現在沒在衰退）"}


def build(close, rev_rows, eps_rows, div_rows, per_rows, category_override="auto", rev_rule="strict", closes=None,
          price_events=None):
    corp = corporate_actions(eps_rows, price_events)
    ok_ev = corp["events"] if corp else []
    quarters = adjust_quarters(_quarters(eps_rows), ok_ev)
    annual = annual_eps(quarters)
    rev = revenue_check(rev_rows)
    if rev:
        rule = rev_rule if rev_rule in REV_RULES else "strict"
        rev.update(rule=rule, rule_label=REV_RULES[rule],
                   passed_rule=rev["lenient"] if rule == "lenient" else rev["trend"] if rule == "trend" else rev["passed"])
    div = dividends(div_rows, annual, closes, ok_ev)
    est = estimate_eps(quarters, _monthly(rev_rows))
    latest_yield = _f(per_rows[-1].get("dividend_yield")) if per_rows else None
    cls = classify(annual, rev, div, latest_yield, quarters, eps_mixed=bool(corp and corp["unverified"]))
    category = category_override if category_override in CATEGORIES else cls["auto"]
    vals = valuations(close, est, div, per_rows)
    ph = [_f(r.get("PER")) for r in per_rows if _f(r.get("PER")) > 0][-245 * 5:]
    vals["peg"] = peg_valuation(close, est, annual, _percentile(ph, .9) if len(ph) >= 245 else None)
    corp_bad = bool(corp and (corp["pending"] or corp["unverified"]))
    if corp_bad:
        # EPS、股利和現在股價差一個倍數：用到預估 EPS／股利的方法都會錯，寧可不給
        why = "除權／分割後股數還沒確認，EPS 和現在股價差一個倍數，先不採用"
        vals["yield"] = {"name": "殖利率法", "unavailable": why}
        vals["peg"] = {"name": "PEG 成長估值", "unavailable": why}
        pe = vals.get("per") or {}
        if pe.get("formula") and "。參考：用今年預估 EPS" in pe["formula"]:
            pe["formula"] = pe["formula"].split("。參考：用今年預估 EPS")[0]
    low_yield = None
    ym = (vals.get("yield") or {}).get("median")
    if ym is not None and ym < LOW_YIELD:
        # 殖利率很低 = 市場用「成長」在估值，不是看股利；拿過去的殖利率回推股價會低到不可能，直接不採用
        low_yield = ym
        vals.pop("yield")
    pb = vals.get("pbr") or {}
    if category == "cyclical" and pb.get("roe_now") is not None and pb.get("unfit"):
        # 循環股的 ROE 本來就大起大落，PBR 正是為了這種股票設計的，不算失準；反而 ROE 位置透露景氣在哪
        up = pb["roe_now"] > pb["roe_med"]
        pb["unfit"] = None
        pb["trend_note"] = (f"循環股 ROE 從 {pb['roe_med']:.0f}% 衝到 {pb['roe_now']:.0f}%，代表景氣在高檔。"
                            "這時候本益比看起來很便宜，但獲利可能是高峰；用 PBR 看比較不會被高峰獲利騙到。ROE 開始往下時要小心"
                            if up else
                            f"循環股 ROE 從 {pb['roe_med']:.0f}% 掉到 {pb['roe_now']:.0f}%，代表景氣在低檔。"
                            "這時候本益比看起來很貴，但常常是布局時機；PBR 落在便宜區時可以分批")
    primary = METHOD_KEY[category]
    primary_note = None
    if corp_bad and primary in ("yield", "peg"):
        primary = "per" if "unavailable" not in (vals.get("per") or {"unavailable": 1}) else "pbr"
        primary_note = f"這檔最近有除權／分割，股數還沒確認，殖利率法暫停，改看{vals[primary]['name']}（交易所的本益比、淨值比已經是新股數）"
    elif primary == "yield" and "yield" not in vals:
        primary = "per" if "unavailable" not in (vals.get("per") or {"unavailable": 1}) else "pbr"
        primary_note = (f"殖利率太低（近 5 年中位數 {low_yield:.2f}%），市場是用成長在估值，不是看股利，"
                        f"所以殖利率法不採用，改看{vals[primary]['name']}" + ("＋PEG" if primary == "per" else ""))
    elif category == "general" and "unavailable" in vals.get("yield", {"unavailable": 1}):
        primary = "pbr"
    if primary_note:
        pass
    elif vals[primary].get("unfit") and category_override in CATEGORIES:   # 你手動指定的分類：照你的方法，只提醒
        primary_note = f"提醒：{vals[primary]['name']}目前{vals[primary]['unfit']}，可以搭配下面其他估值一起看"
    elif vals[primary].get("unfit"):   # 自動分類時，主要方法對這檔失準：換一個還適用的
        alt = next((k for k in ("per", "pbr", "yield") if k != primary and k in vals and "unavailable" not in vals[k] and not vals[k].get("unfit")), None)
        if alt:
            primary_note = f"原本該用{vals[primary]['name']}，但{vals[primary]['unfit']}，改用{vals[alt]['name']}"
            primary = alt
    # 成長股：歷史本益比 + PEG 一起看
    combo = None
    if primary == "per":
        pe, pg = vals.get("per") or {}, vals.get("peg") or {}
        if corp_bad:
            combo = {"tone": "warn", "text": "最近有除權／分割，股數還沒確認，PEG 暫停；本益比區間用交易所資料，可以照看"}
        elif pg.get("stalled"):
            combo = {"tone": "warn", "text": "PEG 不適用（成長暫停或轉折中），本益比區間只能當參考，重點看公司財測"}
        elif pe.get("zone") and pg.get("zone"):
            cheap = lambda z: z in ("便宜", "合理偏低")
            if pe["zone"] == pg["zone"] or cheap(pe["zone"]) == cheap(pg["zone"]):
                combo = {"tone": pe["tone"], "text": f"兩種方法一致：歷史本益比「{pe['zone']}」、PEG「{pg['zone']}」"}
            else:
                hi = "PEG" if cheap(pg["zone"]) else "歷史本益比"
                combo = {"tone": "warn", "text": f"看法分歧：歷史本益比說「{pe['zone']}」、PEG 說「{pg['zone']}」。"
                         + ("PEG 比較樂觀，代表市場還沒完全反映成長；但成長率如果放慢，PEG 的價位會往下修"
                            if hi == "PEG" else
                            "歷史本益比比較樂觀，代表成長率不夠高、撐不起現在的本益比；要確認成長有沒有放慢")}
    return {
        "category": category, "category_info": CATEGORIES[category], "valuation_combo": combo,
        "manual": category_override in CATEGORIES,
        "classification": cls, "categories": CATEGORIES,
        "revenue": rev, "eps": est, "dividends": div,
        "valuations": vals, "primary_method": primary, "primary_note": primary_note, "low_yield": low_yield,
        "dividend_yield": latest_yield, "corp_actions": corp,
    }

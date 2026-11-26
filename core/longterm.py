"""長期體質：這檔是不是「過去幾年穩定成長、長期站在半年線／年線之上」的好股票。

技術面 6 項（看過去 5 年）：
  1. 站上年線（MA240）的時間比例 ≥ 70%
  2. 站上半年線（MA120）的時間比例 ≥ 65%
  3. 年線往上的時間比例 ≥ 70%
  4. 每年最低價墊高（至少 3 次）
  5. 跌超過 20% 後，平均一年內回到前高
  6. 3 年、5 年報酬都贏 0050（當作大盤）
基本面趨勢 3 項（ETF 不看）：營收 3 年年複合成長 > 0、近 12 個月營收年增 > 0、預估 EPS 比 3 年前高。

結果：合格／觀察／論點警訊。這些都是「過去」的表現，龍頭也可能失去優勢，
所以長期名單裡的股票，你寫下的「認錯條件」仍要每季對照。
"""
from analysis import sma


def _item(key, text, ok, value=None, note=None):
    return {"key": key, "text": text, "ok": ok, "value": value, "note": note}


def _share(flags):
    flags = [f for f in flags if f is not None]
    return (sum(flags) / len(flags) * 100) if flags else None


def tech_quality(bars, bench=None, divs=None, bench_divs=None):
    c = [b["close"] for b in bars]
    n = len(c)
    ma120, ma240 = sma(c, 120), sma(c, 240)
    items = []

    a240 = _share([c[i] > ma240[i] if ma240[i] else None for i in range(n)])
    items.append(_item("above240", "站上年線（MA240）的時間比例 ≥ 70%",
                       None if a240 is None else a240 >= 70, None if a240 is None else f"{a240:.0f}%"))
    a120 = _share([c[i] > ma120[i] if ma120[i] else None for i in range(n)])
    items.append(_item("above120", "站上半年線（MA120）的時間比例 ≥ 65%",
                       None if a120 is None else a120 >= 65, None if a120 is None else f"{a120:.0f}%"))
    up = _share([ma240[i] > ma240[i - 20] if ma240[i] and i >= 20 and ma240[i - 20] else None for i in range(n)])
    items.append(_item("rising240", "年線往上的時間比例 ≥ 70%",
                       None if up is None else up >= 70, None if up is None else f"{up:.0f}%"))

    # 每年最低價墊高（最後一年未滿也算）
    lows = {}
    for b in bars:
        y = b["date"][:4]
        lows[y] = min(lows.get(y, b["low"]), b["low"])
    ys = sorted(lows)
    higher = sum(1 for a, b in zip(ys, ys[1:]) if lows[b] > lows[a])
    pairs = len(ys) - 1
    items.append(_item("higher_lows", "每年最低價墊高（至少 3 次）",
                       None if pairs < 3 else higher >= 3, f"{higher}/{pairs} 次" if pairs > 0 else None))

    # 跌超過 20% 後回到前高要多久
    peak, peak_i, trough, in_dd, rec = c[0], 0, c[0], False, []
    open_dd = None
    for i in range(1, n):
        if c[i] >= peak:
            if in_dd:
                rec.append(i - peak_i)
                in_dd = False
            peak, peak_i, trough = c[i], i, c[i]
        else:
            trough = min(trough, c[i])
            if not in_dd and trough <= peak * 0.8:
                in_dd = True
    if in_dd:
        open_dd = n - 1 - peak_i
    if rec or open_dd is not None:
        avg = sum(rec) / len(rec) if rec else None
        ok = (avg is not None and avg <= 250) and (open_dd is None or open_dd <= 250)
        val = (f"{len(rec)} 次，平均 {avg / 21:.0f} 個月" if rec else "")
        if open_dd is not None:
            val += ("；" if val else "") + f"目前已 {open_dd / 21:.0f} 個月未回前高"
        items.append(_item("recovery", "跌超過 20% 後，平均一年內回到前高", ok, val))
    else:
        items.append(_item("recovery", "跌超過 20% 後，平均一年內回到前高", True, "5 年內沒有跌超過 20%"))

    # 贏過 0050
    if bench:
        bmap = {b["date"]: b["close"] for b in bench}
        def ret(days):
            if n <= days:
                return None, None
            d0 = bars[-1 - days]["date"]
            b0 = bmap.get(d0)
            b1 = bmap.get(bars[-1]["date"])
            if not b0 or not b1:
                return None, None
            # 含息報酬：期間內領到的現金股利加回去（高股息 ETF 只比股價會很吃虧）
            dv = lambda xs: sum(a for d, a in (xs or []) if d0 < d <= bars[-1]["date"])
            return (c[-1] + dv(divs)) / c[-1 - days] * 100 - 100, (b1 + dv(bench_divs)) / b0 * 100 - 100
        s3, b3 = ret(735)
        s5, b5 = ret(min(1225, n - 1))
        if s3 is not None:
            ok = s3 > b3 and (s5 is None or s5 > b5)
            val = f"3 年 {s3:+.0f}% vs {b3:+.0f}%" + (f"；5 年 {s5:+.0f}% vs {b5:+.0f}%" if s5 is not None else "") \
                + ("（含息）" if divs and bench_divs else "（只比股價，還沒有配息資料）")
            items.append(_item("vs_bench", "3 年、5 年報酬都贏 0050", ok, val))
        else:
            items.append(_item("vs_bench", "3 年、5 年報酬都贏 0050", None, "資料不足"))
    else:
        items.append(_item("vs_bench", "3 年、5 年報酬都贏 0050", None, "本身就是大盤 ETF" if bench is None else "抓不到 0050"))

    known = [x for x in items if x["ok"] is not None]
    passed = sum(1 for x in known if x["ok"])
    return {"items": items, "passed": passed, "total": len(known),
            "years": round(n / 245, 1), "ma120": ma120[-1], "ma240": ma240[-1],
            "ma240_up": bool(ma240[-1] and n > 20 and ma240[-21] and ma240[-1] > ma240[-21])}


def fund_trend(fund):
    if not fund or fund.get("error") or fund.get("etf"):
        return None
    rev = fund.get("revenue") or {}
    eps = (fund.get("eps") or {}).get("estimate")
    years = (fund.get("classification") or {}).get("eps_years") or []
    base = years[-3]["eps"] if len(years) >= 3 else None
    items = [
        _item("rev_cagr", "營收 3 年年複合成長 > 0",
              None if rev.get("cagr3") is None else rev["cagr3"] > 0,
              None if rev.get("cagr3") is None else f"{rev['cagr3']:+.1f}%"),
        _item("rev_ttm", "近 12 個月營收年增 > 0",
              None if rev.get("ttm_yoy") is None else rev["ttm_yoy"] > 0,
              None if rev.get("ttm_yoy") is None else f"{rev['ttm_yoy']:+.1f}%"),
        _item("eps3", "預估 EPS 比 3 年前高",
              None if eps is None or base is None else eps > base,
              None if eps is None or base is None else f"{eps:.2f} vs {base:.2f}（{years[-3]['year']}）"),
    ]
    warns = []
    if rev.get("recent_decline"):
        warns.append("營收連續 3 個月年減")
    last = years[-1]["eps"] if years else None
    if eps is not None and last and last > 0 and eps < last * 0.8:
        warns.append(f"預估 EPS 比去年衰退 20% 以上（{eps:.2f} vs {last:.2f}）")
    known = [x for x in items if x["ok"] is not None]
    return {"items": items, "passed": sum(1 for x in known if x["ok"]), "total": len(known), "warns": warns}


def eligibility(tech, ftr, core, is_etf, category=None):
    if category == "cyclical" and not is_etf:
        # 循環股不在這個平台的長線範圍：它的買賣邏輯跟成長股、穩定配息股相反，另用循環股工具判斷
        return {"status": "循環股", "tone": "muted", "warns": [], "core": bool(core), "etf": False, "cyclical": True}
    warns = list((ftr or {}).get("warns") or [])
    notes = []
    if tech["total"] >= 4 and tech["passed"] <= 2:
        if is_etf:   # ETF 是一籃子、不會倒；股價又不含配息（高股息 ETF 特別吃虧），弱勢只降到「觀察」
            notes.append(f"技術體質只有 {tech['passed']}/{tech['total']}；ETF 股價不含配息，高股息 ETF 會被低估，降為觀察")
        else:
            warns.append(f"技術面長期體質只有 {tech['passed']}/{tech['total']}")
    if ftr and ftr["total"] >= 2 and ftr["passed"] == 0:
        warns.append("基本面趨勢 3 項都沒過")
    tech_ok = tech["passed"] >= max(3, tech["total"] - 2)
    fund_ok = is_etf or (ftr is not None and ftr["passed"] >= 2)
    if warns:
        status, tone = "論點警訊", "warn"
    elif tech_ok and fund_ok:
        status, tone = "合格", "bull"
    else:
        status, tone = "觀察", "neutral"
    return {"status": status, "tone": tone, "warns": warns + notes if status != "論點警訊" else warns,
            "core": bool(core), "etf": is_etf}

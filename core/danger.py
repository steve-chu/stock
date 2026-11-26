"""多頭危機訊號：多頭裡「頂部特有的跡象」，用來提早分批減碼。

趨勢方法（Weinstein／Minervini）是落後指標，頂部時只會說「很強」；
這裡改看大戶出貨會留下的痕跡：漲太遠、出貨日、背離、高檔爆量、融資追價、法人趁強賣、估值高檔。

計分：0–1 健康、2–3 留意（不加碼、先減 1/3）、≥4 或「≥2 且跌破月線」危機（再減 1/3，
剩下 1/3 等 Weinstein 轉做頭或跌破 50 日均線）。
price_signals() 只用日 K，可以拿來回測；judge() 再加上籌碼和估值。
"""
from analysis import kd, rsi, sma


def prep(bars):
    c = [b["close"] for b in bars]
    v = [b["volume"] for b in bars]
    h = [b["high"] for b in bars]
    k, _ = kd(h, [b["low"] for b in bars], c)
    return {"bars": bars, "c": c, "o": [b["open"] for b in bars], "h": h, "l": [b["low"] for b in bars],
            "v": v, "ma20": sma(c, 20), "ma50": sma(c, 50), "ma200": sma(c, 200), "vol20": sma(v, 20),
            "rsi": rsi(c), "k": k}


def _sig(key, label, on, value, text, dates=None):
    return {"key": key, "label": label, "on": bool(on), "value": value, "text": text, "dates": dates or []}


def price_signals(x, j):
    """只用日 K 的 7 個訊號（截至第 j 根）。"""
    c, o, h, l, v, b = x["c"], x["o"], x["h"], x["l"], x["v"], x["bars"]
    out = []
    if j < 260:
        return out

    # 1. 離 200 日均線太遠（同時看自己過去一年的乖離位置）
    m200 = x["ma200"][j]
    if m200:
        dev = c[j] / m200 - 1
        hist = sorted(c[t] / x["ma200"][t] - 1 for t in range(max(200, j - 750), j) if x["ma200"][t])
        p90 = hist[int(len(hist) * 0.9)] if len(hist) > 100 else None
        on = dev >= 0.40 or (p90 is not None and dev >= p90 and dev >= 0.20)
        out.append(_sig("ext", "離 200 日均線太遠", on, f"{dev * 100:+.0f}%",
                        "乖離 ≥40%，或在自己歷史乖離最高 10%（且 ≥20%）"
                        + (f"；歷史 90 百分位 {p90 * 100:+.0f}%" if p90 is not None else "")))

    # 2. 60 日漲幅過大
    r60 = c[j] / c[j - 60] - 1
    out.append(_sig("run", "60 日漲幅過大", r60 > 0.25, f"{r60 * 100:+.0f}%", "60 個交易日漲超過 25%"))

    # 3. 動能長時間過熱
    hot = sum(1 for t in range(j - 9, j + 1) if (x["rsi"][t] or 0) >= 70 or (x["k"][t] or 0) >= 85)
    out.append(_sig("hot", "動能長時間過熱", hot >= 5, f"{hot}/10 天",
                    "近 10 天有 5 天以上 RSI ≥70 或 K ≥85"))

    # 4. 出貨日：下跌而且量比前一天大
    dd = [t for t in range(j - 24, j + 1) if c[t] < c[t - 1] * 0.998 and v[t] > v[t - 1]]
    out.append(_sig("dist", "出貨日偏多", len(dd) >= 5, f"{len(dd)} 天",
                    "近 25 天「收跌且量比前一天大」的天數 ≥5（法人在賣的痕跡）",
                    [b[t]["date"] for t in dd]))

    # 5 & 6. 頂背離、量價背離：近 10 日的高點 vs 前一段（15～60 日前）的高點
    i_hi = max(range(j - 9, j + 1), key=lambda t: c[t])
    j_hi = max(range(j - 60, j - 14), key=lambda t: c[t])
    new_high = c[i_hi] > c[j_hi]
    div = new_high and x["rsi"][i_hi] is not None and x["rsi"][j_hi] is not None and x["rsi"][i_hi] < x["rsi"][j_hi] - 3
    out.append(_sig("div", "頂背離", div,
                    f"RSI {x['rsi'][i_hi]:.0f} vs {x['rsi'][j_hi]:.0f}" if new_high and x["rsi"][i_hi] else "—",
                    "股價創新高，但 RSI 比前一個高點低（上漲力道減弱）",
                    [b[j_hi]["date"], b[i_hi]["date"]] if div else []))
    va = lambda t: sum(v[max(0, t - 2):t + 3]) / len(v[max(0, t - 2):t + 3])
    vdiv = new_high and va(i_hi) < va(j_hi) * 0.8
    out.append(_sig("vdiv", "量價背離", vdiv,
                    f"量 {va(i_hi) / max(va(j_hi), 1) * 100:.0f}%" if new_high else "—",
                    "創新高時的成交量不到上一個高點的 80%（追價的人變少）",
                    [b[j_hi]["date"], b[i_hi]["date"]] if vdiv else []))

    # 7. 高檔爆量、長上影線
    hi60 = max(h[j - 59:j + 1])
    climax = [t for t in range(j - 9, j + 1)
              if x["vol20"][t - 1] and v[t] >= 2 * x["vol20"][t - 1] and h[t] >= hi60 * 0.95
              and (h[t] - max(o[t], c[t])) >= 0.5 * max(h[t] - l[t], 1e-9)]
    out.append(_sig("climax", "高檔爆量長上影", bool(climax), b[climax[-1]]["date"] if climax else "—",
                    "近 10 天在高檔出現 2 倍量、上影線佔一半以上的 K 棒（有人趁高大量賣）",
                    [b[t]["date"] for t in climax]))
    return out


def chip_signals(bars, margin_rows, inst_rows, per_rows):
    out = []
    c = [b["close"] for b in bars]
    r20 = c[-1] / c[-21] - 1 if len(c) > 21 else 0
    rows = sorted(margin_rows or [], key=lambda r: r["date"])
    bal = [r.get("MarginPurchaseTodayBalance") or 0 for r in rows]
    if len(bal) > 20 and bal[-21] > 0:
        m = bal[-1] / bal[-21] - 1
        out.append(_sig("margin", "融資追價", m >= 0.08 and r20 > 0, f"20 日 {m * 100:+.1f}%",
                        "股價上漲時融資 20 日增加 ≥8%（籌碼從大戶流到散戶）"))
    if inst_rows:
        dates = sorted({r["date"] for r in inst_rows})[-20:]
        keep = set(dates)
        net = {"Foreign_Investor": 0, "Investment_Trust": 0}
        for r in inst_rows:
            if r["date"] in keep and r.get("name") in net:
                net[r["name"]] += (r.get("buy") or 0) - (r.get("sell") or 0)
        f, t = round(net["Foreign_Investor"] / 1000), round(net["Investment_Trust"] / 1000)
        out.append(_sig("inst", "法人趁強賣", r20 > 0.05 and (f + t) < 0, f"外資 {f:+,}、投信 {t:+,} 張",
                        "近 20 日股價漲 >5%，但外資＋投信合計賣超"))
    pbr = [float(r["PBR"]) for r in (per_rows or []) if r.get("PBR") and float(r["PBR"]) > 0]
    if len(pbr) > 120:
        rank = sum(1 for p in pbr if p <= pbr[-1]) / len(pbr) * 100
        out.append(_sig("val", "估值在歷史高檔", rank >= 90, f"PBR 第 {rank:.0f} 百分位",
                        f"PBR 在近 {len(pbr) / 245:.1f} 年最高 10%"))
    return out


def level(n, broke_ma20):
    if n >= 4 or (n >= 2 and broke_ma20):
        return "crisis"
    if n >= 2:
        return "watch"
    return "healthy"


LEVELS = {
    "healthy": {"label": "多頭健康", "tone": "bull", "advice": "可照計畫布局"},
    "watch": {"label": "留意", "tone": "warn", "advice": "停止加碼，持股不動"},
    "crisis": {"label": "危機", "tone": "bear",
               "advice": "停止加碼，持股不動（股災警報出現時，才減短線部位）"},
}


def market_state(bench_bars, bench_dg):
    """大盤（0050）狀態：過熱危機 = 股災預告；跌破年線且年線下彎 = 空頭確認。"""
    if not bench_bars or len(bench_bars) < 260:
        return None
    c = [b["close"] for b in bench_bars]
    ma = lambda k: sum(c[-k - 240:len(c) - k]) / 240
    ma_now, ma_prev = ma(0), ma(20)
    heat = (bench_dg or {}).get("level")
    late = bool((bench_dg or {}).get("late"))
    bear = c[-1] < ma_now and ma_now < ma_prev
    return {"close": c[-1], "ma240": round(ma_now, 2), "ma240_down": ma_now < ma_prev, "bear": bear,
            "heat": heat, "heat_late": late, "heat_label": (bench_dg or {}).get("label"),
            "count": (bench_dg or {}).get("count"), "total": (bench_dg or {}).get("total"),
            "warn": heat == "crisis" and not late}


def crash_check(market, elig_status=None):
    """股災警報：只減短線 30% 部位，長線 70% 不動。"""
    why = []
    if market and market.get("warn"):
        why.append(f"大盤（0050）過熱「危機」（{market['count']}/{market['total']} 個頂部訊號）：股災預告")
    if market and market.get("bear"):
        why.append(f"大盤（0050）跌破年線 {market['ma240']:g}，而且年線往下彎：空頭確認")
    if elig_status == "論點警訊":
        why.append("這檔長期體質轉壞（論點警訊）")
    return {"on": bool(why), "reasons": why,
            "advice": "短線 30% 部位減碼，資金可以轉到其他商品（例如債券 ETF、現金）；長線 70% 部位不動" if why else None}


def judge(bars, margin_rows, inst_rows, per_rows, regime_state=None):
    x = prep(bars)
    j = len(bars) - 1
    sig = price_signals(x, j) + chip_signals(bars, margin_rows, inst_rows, per_rows)
    n = sum(1 for s in sig if s["on"])
    broke = bool(x["ma20"][j]) and x["c"][j] < x["ma20"][j] and max(x["c"][j - 20:j]) > x["ma20"][j] * 1.03
    lv = level(n, broke)
    info = LEVELS[lv]
    applies = regime_state in ("bull", "dist") or (x["ma200"][j] and x["c"][j] > x["ma200"][j])
    # 頂部訊號是用來「熱的時候減碼」。已經從高點跌超過 15%，再亮危機就太晚了：這時候減碼等於在恐慌時賣
    peak = max(b["high"] for b in bars[-120:])
    dd = (1 - x["c"][j] / peak) * 100 if peak else 0
    late = dd >= 15 and lv != "healthy"
    # 頂部訊號還亮著、但股價已經跌破月線往下走：判斷不變（一樣停止加碼），只是不叫「過熱」，免得看了困惑
    cooling = lv != "healthy" and not late and bool(x["ma20"][j]) and x["c"][j] < x["ma20"][j] and dd >= 5
    if cooling:
        info = {**info, "label": "高檔轉弱", "advice": "停止加碼，持股不動：等跌到恐慌價位，或重新站穩月線再加碼"}
    return {
        "level": lv, **info, "count": n, "total": len(sig), "signals": sig, "cooling": cooling,
        "broke_ma20": broke, "applies": bool(applies), "drawdown": round(dd, 1), "late": late,
        "late_note": (f"已經從近半年高點 {peak:g} 回檔 {dd:.0f}%，頂部訊號亮得太晚：現在減碼等於在恐慌時賣。"
                      "改看恐慌區和你寫的認錯條件") if late else None,
        "summary": f"{info['label']}：{n}/{len(sig)} 個頂部訊號" + ("，股價已從高點回落、跌破月線" if cooling else "，且已跌破月線" if broke else "")
                   + ("" if applies else "（目前不在多頭，這組訊號僅供參考）"),
    }

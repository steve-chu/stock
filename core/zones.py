"""恐慌區間（下方大機率止跌帶）與壓力區間（上方大機率賣壓帶）。

四種方法各自算出價位帶，彼此重疊（±3%）的合併成一個區間，
重疊的方法越多，代表越多證據指向同一個價位 → 可信度越高。
這是機率區間，不是預言。
"""
from analysis import sma


def _pct(vals, p):
    s = sorted(vals)
    if not s:
        return None
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _drawdowns(bars, min_dd=0.10, rally=0.20):
    """切出每一段「高點 → 回檔」：創新高，或從低點反彈 20% 以上，就算新的一段。
    回傳歷次 ≥10% 回檔的最大跌幅、目前這段的高點、目前回檔幅度。"""
    eps, peak, trough = [], bars[0]["high"], bars[0]["low"]
    for b in bars[1:]:
        if b["high"] > peak:
            if 1 - trough / peak >= min_dd:
                eps.append(1 - trough / peak)
            peak, trough = b["high"], b["low"]
            continue
        trough = min(trough, b["low"])
        if b["high"] >= trough * (1 + rally) and 1 - trough / peak >= min_dd:
            eps.append(1 - trough / peak)
            peak, trough = b["high"], b["low"]
    cur = max(0.0, 1 - bars[-1]["close"] / peak)
    return eps, peak, cur


def _volume_nodes(bars, n_bins=30, top=4):
    """近一年成交量最集中的價位。"""
    rec = bars[-250:]
    lo, hi = min(b["low"] for b in rec), max(b["high"] for b in rec)
    if hi <= lo:
        return []
    w = (hi - lo) / n_bins
    hist = [0.0] * n_bins
    for b in rec:
        k = min(int(((b["high"] + b["low"] + b["close"]) / 3 - lo) / w), n_bins - 1)
        hist[k] += b["volume"]
    total = sum(hist) or 1
    idx = sorted(range(n_bins), key=lambda k: -hist[k])[:top]
    return [(lo + (k + 0.5) * w, hist[k] / total * 100) for k in idx]


TIERS = {  # 距離現價的跌幅區間
    "normal": (0.0, 0.18, "一般回檔"),
    "deep": (0.18, 0.28, "深度回檔"),
    "extreme": (0.28, 9.0, "極端恐慌"),
}


def _cluster(cands, close, below):
    cands = sorted([x for x in cands if x["price"] and ((x["price"] < close) if below else (x["price"] > close))],
                   key=lambda x: -x["price"] if below else x["price"])
    zones = []
    for x in cands:
        z = next((z for z in zones if abs(x["price"] / z["mid"] - 1) <= 0.03), None)
        if z:
            z["items"].append(x)
            ps = [i["price"] for i in z["items"]]
            z["lo"], z["hi"], z["mid"] = min(ps), max(ps), sum(ps) / len(ps)
        else:
            zones.append({"lo": x["price"], "hi": x["price"], "mid": x["price"], "items": [x]})
    out = []
    for z in zones:
        methods = sorted({i["method"] for i in z["items"]})
        out.append({"lo": round(z["lo"], 2), "hi": round(z["hi"], 2), "mid": round(z["mid"], 2),
                    "dist": round((z["mid"] / close - 1) * 100, 1),
                    "strength": len(methods), "methods": methods,
                    "detail": [i["text"] for i in z["items"]]})
    return out


def build(bars, per_rows, est_eps):
    close = bars[-1]["close"]
    c = [b["close"] for b in bars]
    below, above, notes = [], [], []

    # 1. 歷史回檔幅度
    eps, peak, cur = _drawdowns(bars)
    if eps:
        med, deep = _pct(eps, 0.5), max(eps)
        below.append({"method": "歷史回檔", "price": peak * (1 - med),
                      "text": f"從高點 {peak:.2f} 回檔中位數 {med * 100:.0f}%"})
        below.append({"method": "歷史回檔", "price": peak * (1 - deep),
                      "text": f"從高點 {peak:.2f} 最大回檔 {deep * 100:.0f}%"})
        notes.append(f"近 {len(bars) // 245 or 1} 年有 {len(eps)} 次 ≥10% 的回檔" + ("，樣本少、僅供參考" if len(eps) < 4 else ""))
    else:
        notes.append("近幾年沒有 ≥10% 的回檔，無法統計回檔幅度")

    # 2. 200 日均線乖離
    ma200 = sma(c, 200)
    dev = [(c[k] / ma200[k] - 1) for k in range(len(c)) if ma200[k]]
    if len(dev) > 120 and ma200[-1]:
        for p, lab in ((0.10, "低 10%"), (0.03, "低 3%")):
            d = _pct(dev, p)
            if d < 0:
                below.append({"method": "200 日均線乖離", "price": ma200[-1] * (1 + d),
                              "text": f"乖離歷史{lab}位置（{d * 100:.0f}%）"})
        if close < ma200[-1]:
            above.append({"method": "200 日均線", "price": ma200[-1], "text": f"股價在 200 日均線 {ma200[-1]:.2f} 之下"})

    # 3. 估值底線（龍頭股最可靠）
    pbr = [float(r["PBR"]) for r in per_rows if r.get("PBR") and float(r["PBR"]) > 0]
    if len(pbr) > 120:
        bvps = close / pbr[-1]
        p10 = _pct(pbr, 0.10)
        below.append({"method": "估值底線", "price": bvps * p10, "text": f"PBR 歷史低 10%（{p10:.2f} 倍）"})
        p90 = _pct(pbr, 0.90)
        above.append({"method": "估值上緣", "price": bvps * p90, "text": f"PBR 歷史高 10%（{p90:.2f} 倍）"})
    per = [float(r["PER"]) for r in per_rows if r.get("PER") and 0 < float(r["PER"]) < 200]
    per_now = float(per_rows[-1].get("PER") or 0) if per_rows else 0
    if 0 < per_now < 200 and len(per) > 120:   # 歷史本益比是用過去四季 EPS 算的，要配同一種 EPS
        e10 = _pct(per[-245 * 5:], 0.10)
        ttm = close / per_now
        below.append({"method": "估值底線", "price": ttm * e10, "text": f"本益比歷史低 10%（{e10:.1f} 倍 × 過去四季 EPS {ttm:.2f}）"})

    # 4. 成交密集區
    for price, share in _volume_nodes(bars):
        item = {"method": "成交密集區", "price": price, "text": f"近一年 {share:.0f}% 成交量集中在 {price:.2f} 附近"}
        (below if price < close else above).append(item)

    # 壓力：前高
    hi60, hi250 = max(b["high"] for b in bars[-60:]), max(b["high"] for b in bars[-250:])
    above.append({"method": "前高", "price": hi60, "text": f"近 60 日高點 {hi60:.2f}"})
    if hi250 > hi60 * 1.01:
        above.append({"method": "前高", "price": hi250, "text": f"52 週高點 {hi250:.2f}"})

    panic = _cluster(below, close, True)
    resist = _cluster(above, close, False)

    # 到達機率：過去「已經跌到目前幅度」的回檔中，有幾成會再跌到這個價位
    base_dd = max(cur, 0.10)
    pool = [e for e in eps if e >= base_dd]
    for z in panic:
        need = 1 - z["mid"] / peak
        z["reach"] = {"n": sum(1 for e in pool if e >= need), "of": len(pool),
                      "pct": round(sum(1 for e in pool if e >= need) / len(pool) * 100) if pool else None}
        z["tier"] = next((k for k, (lo, hi, _) in TIERS.items() if lo <= -z["dist"] / 100 < hi), "normal")
        z["label"] = TIERS[z["tier"]][2]

    # 三層分批：每一層挑一個（重疊方法多的優先，同分挑離現價近的）
    tiers = []
    for k, (_, _, label) in TIERS.items():
        cand = [z for z in panic if z["tier"] == k]
        if cand:
            pick = max(cand, key=lambda z: (z["strength"], z["mid"]))
            tiers.append({"tier": k, "label": label, **pick})

    best = max(panic, key=lambda z: (z["strength"], z["mid"]), default=None)
    return {
        "panic": panic[:8], "resist": resist[:4], "notes": notes, "tiers": tiers,
        "drawdown_now": round(cur * 100, 1), "peak": round(peak, 2),
        "dd_median": round(_pct(eps, 0.5) * 100, 1) if eps else None,
        "best_panic": best,
        "summary": (f"距高點已回檔 {cur * 100:.0f}%。" +
                    (f"最多方法重疊的恐慌區在 {best['lo']:.2f}–{best['hi']:.2f}（{best['strength']} 種方法，距現價 {best['dist']:+.1f}%）"
                     if best else "下方暫時算不出恐慌區")),
    }

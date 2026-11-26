"""技術指標 + 股價分析 + 買賣策略。

指標（MA / KD / MACD / RSI / ATR）是標準算法。
analyze() 和 strategy() 目前是「暫用規則」，之後換成你自己的分析邏輯和策略，
只要回傳的欄位格式不變，前端就不用改。
"""


# ---------- 指標 ----------

def sma(vals, n):
    out, s = [None] * len(vals), 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(vals, n):
    """支援前段為 None 的序列（例如 MACD 的 DIF）。"""
    out = [None] * len(vals)
    k = 2 / (n + 1)
    seed, prev = [], None
    for i, v in enumerate(vals):
        if v is None:
            continue
        if prev is None:
            seed.append(v)
            if len(seed) == n:
                prev = sum(seed) / n
                out[i] = prev
            continue
        prev = v * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(closes, n=14):
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for i in range(n, len(closes)):
        if i > n:
            ag = (ag * (n - 1) + gains[i - 1]) / n
            al = (al * (n - 1) + losses[i - 1]) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def kd(highs, lows, closes, n=9):
    k_out, d_out = [None] * len(closes), [None] * len(closes)
    k = d = 50.0
    for i in range(len(closes)):
        if i < n - 1:
            continue
        hh, ll = max(highs[i - n + 1:i + 1]), min(lows[i - n + 1:i + 1])
        rsv = 50.0 if hh == ll else (closes[i] - ll) / (hh - ll) * 100
        k = k * 2 / 3 + rsv / 3
        d = d * 2 / 3 + k / 3
        k_out[i], d_out[i] = k, d
    return k_out, d_out


def macd(closes, fast=12, slow=26, sig=9):
    ef, es = ema(closes, fast), ema(closes, slow)
    dif = [None if a is None or b is None else a - b for a, b in zip(ef, es)]
    dea = ema(dif, sig)
    hist = [None if a is None or b is None else a - b for a, b in zip(dif, dea)]
    return dif, dea, hist


def atr(highs, lows, closes, n=14):
    out = [None] * len(closes)
    trs = [highs[0] - lows[0]] + [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        for i in range(1, len(closes))
    ]
    if len(trs) < n:
        return out
    a = sum(trs[:n]) / n
    out[n - 1] = a
    for i in range(n, len(trs)):
        a = (a * (n - 1) + trs[i]) / n
        out[i] = a
    return out


# ---------- 工具 ----------

def tick(price):
    """台股升降單位。"""
    if price < 10: return 0.01
    if price < 50: return 0.05
    if price < 100: return 0.1
    if price < 500: return 0.5
    if price < 1000: return 1.0
    return 5.0


def to_tick(price):
    if price is None:
        return None
    t = tick(price)
    return round(round(price / t) * t, 2)


def _crossed_up(a, b, i, lookback=3):
    for j in range(max(1, i - lookback + 1), i + 1):
        if None not in (a[j], b[j], a[j - 1], b[j - 1]) and a[j - 1] <= b[j - 1] and a[j] > b[j]:
            return True
    return False


def _crossed_down(a, b, i, lookback=3):
    return _crossed_up(b, a, i, lookback)


def _ret(closes, n):
    if len(closes) <= n:
        return None
    return (closes[-1] / closes[-1 - n] - 1) * 100


# ---------- 主函式 ----------

def compute(bars):
    o = [b["open"] for b in bars]
    h = [b["high"] for b in bars]
    l = [b["low"] for b in bars]
    c = [b["close"] for b in bars]
    v = [b["volume"] for b in bars]
    k, d = kd(h, l, c)
    dif, dea, hist = macd(c)
    ind = {
        "ma5": sma(c, 5), "ma10": sma(c, 10), "ma20": sma(c, 20), "ma60": sma(c, 60),
        "k": k, "d": d, "dif": dif, "dea": dea, "hist": hist,
        "rsi": rsi(c), "atr": atr(h, l, c), "vol20": sma(v, 20),
    }
    a = analyze(bars, ind)
    rounded = {key: [None if x is None else round(x, 3) for x in arr] for key, arr in ind.items()}
    return {"indicators": rounded, "analysis": a, "raw": ind}


def analyze(bars, ind):
    i = len(bars) - 1
    c = [b["close"] for b in bars]
    close = c[-1]
    ma5, ma20, ma60 = ind["ma5"][i], ind["ma20"][i], ind["ma60"][i]
    signals, score = [], 0

    def add(label, text, tone):
        nonlocal score
        score += {"bull": 1, "bear": -1}.get(tone, 0)
        signals.append({"label": label, "text": text, "tone": tone})

    # 趨勢
    if None not in (ma5, ma20, ma60) and ma5 > ma20 > ma60 and close > ma20:
        trend, tone = "多頭排列", "bull"
    elif None not in (ma5, ma20, ma60) and ma5 < ma20 < ma60 and close < ma20:
        trend, tone = "空頭排列", "bear"
    else:
        trend, tone = "盤整", "neutral"
    add("均線", f"{trend}（5 / 20 / 60 日）", tone)

    if ma20 is not None and ma60 is not None:
        pos = ("站上" if close >= ma20 else "跌破") + "月線，" + ("站上" if close >= ma60 else "跌破") + "季線"
        t = "bull" if close >= ma20 and close >= ma60 else "bear" if close < ma20 and close < ma60 else "neutral"
        add("位置", pos, t)

    kk, dd = ind["k"][i], ind["d"][i]
    if kk is not None:
        if _crossed_up(ind["k"], ind["d"], i):
            txt, t = "黃金交叉", "bull"
        elif _crossed_down(ind["k"], ind["d"], i):
            txt, t = "死亡交叉", "bear"
        else:
            txt, t = ("K > D" if kk > dd else "K < D"), ("bull" if kk > dd else "bear")
        if kk > 80:
            txt += "，高檔區"
            t = "neutral" if t == "bull" else t
        elif kk < 20:
            txt += "，低檔區"
            t = "neutral" if t == "bear" else t
        add("KD", f"K {kk:.0f} / D {dd:.0f}，{txt}", t)

    hs = ind["hist"]
    if hs[i] is not None and hs[i - 1] is not None:
        if _crossed_up(ind["dif"], ind["dea"], i):
            txt, t = "DIF 上穿訊號線", "bull"
        elif _crossed_down(ind["dif"], ind["dea"], i):
            txt, t = "DIF 下穿訊號線", "bear"
        elif hs[i] > 0:
            txt, t = ("紅柱放大" if hs[i] > hs[i - 1] else "紅柱縮小"), ("bull" if hs[i] > hs[i - 1] else "neutral")
        else:
            txt, t = ("綠柱放大" if hs[i] < hs[i - 1] else "綠柱縮小"), ("bear" if hs[i] < hs[i - 1] else "neutral")
        add("MACD", txt, t)

    r = ind["rsi"][i]
    if r is not None:
        if r > 70:
            add("RSI", f"{r:.0f}，過熱", "bear")
        elif r < 30:
            add("RSI", f"{r:.0f}，超賣", "bull")
        else:
            add("RSI", f"{r:.0f}，中性", "neutral")

    va = ind["vol20"][i]
    if va:
        ratio = bars[i]["volume"] / va
        up = close >= c[-2] if len(c) > 1 else True
        if ratio >= 1.5:
            add("量能", f"量增 {ratio:.1f} 倍" + ("，價漲" if up else "，價跌"), "bull" if up else "bear")
        elif ratio <= 0.6:
            add("量能", f"量縮至 {ratio:.1f} 倍均量", "neutral")
        else:
            add("量能", f"{ratio:.1f} 倍 20 日均量", "neutral")

    lows20 = [b["low"] for b in bars[-20:]]
    highs60 = [b["high"] for b in bars[-60:]]
    verdict = "偏多" if score >= 2 else "偏空" if score <= -2 else "中性"
    return {
        "verdict": verdict,
        "score": score,
        "trend": trend,
        "signals": signals,
        "returns": {"d5": _ret(c, 5), "d20": _ret(c, 20), "d60": _ret(c, 60)},
        "levels": {
            "support": to_tick(min(lows20)),
            "ma20": to_tick(ma20),
            "ma60": to_tick(ma60),
            "resistance": to_tick(max(highs60)),
        },
    }


def strategy(bars, ind, a, regime=None, fund=None):
    """暫用規則：依趨勢狀態（多頭／洗籌碼／盤整／出貨警戒／空頭）給出不同做法。
    之後換成你的三套投資方式，回傳欄位不變即可。"""
    i = len(bars) - 1
    close = bars[i]["close"]
    at = ind["atr"][i] or close * 0.02
    ma20 = ind["ma20"][i] or close
    lv = a["levels"]
    res, sup = lv["resistance"], lv["support"]
    state = (regime or {}).get("state") or {"偏多": "bull", "偏空": "bear"}.get(a["verdict"], "range")
    strength = (regime or {}).get("strength")
    target_label = "目標"

    if state == "bull":
        entry_hi = min(close, (ind["ma5"][i] or close))
        entry_lo = max(ma20, entry_hi - 1.5 * at)
        if entry_lo >= entry_hi:  # 已經拉回到月線以下：以現價下方半個 ATR 為區間
            entry_lo = entry_hi - 0.5 * at
        t1 = res if res >= close + 1.5 * at else close + 2 * at
        out = {
            "stance": "拉回分批布局" if strength == "強" else "小量試單，拉回再加碼", "tone": "bull",
            "entry": [to_tick(entry_lo), to_tick(entry_hi)], "stop": to_tick(entry_lo - 1.5 * at),
            "targets": [to_tick(t1), to_tick(max(t1 + at, close + 4 * at))],
            "notes": ["多頭不追高，等拉回月線附近再進場",
                      "多頭強度不足（Minervini 未過）時部位減半" if strength != "強" else "趨勢強，可抱到跌破月線再出",
                      "收盤跌破停損價就出場"],
        }
    elif state in ("wash", "range"):
        entry_lo, entry_hi = sup, min(close, sup + at)
        out = {
            "stance": "低檔分批布局" if state == "wash" else "區間操作，小量", "tone": "bull" if state == "wash" else "neutral",
            "entry": [to_tick(entry_lo), to_tick(max(entry_lo, entry_hi))],
            "stop": to_tick(sup - at), "targets": [to_tick(res)],
            "notes": (["洗籌碼階段：靠近區間下緣分 2～3 批買", "放量突破區間上緣再加碼", "跌破區間低點且站不回就停損"]
                      if state == "wash" else
                      ["方向未明，只在區間下緣小量布局", "接近前高壓力先獲利了結"]),
        }
    elif state == "dist":
        target_label = "減碼價"
        out = {
            "stance": "不新增，持股逢高減碼", "tone": "bear",
            "entry": None, "stop": to_tick(sup - 0.5 * at), "targets": [to_tick(max(ma20, close))],
            "notes": ["出貨警戒：不開新倉", "反彈到月線附近先減碼", "跌破區間低點（停損價）全部出場"],
        }
    else:
        target_label = "減碼價"
        out = {
            "stance": "觀望", "tone": "bear",
            "entry": None, "stop": to_tick(sup - 0.5 * at), "targets": [to_tick(ma20)],
            "notes": ["空頭不接刀，等站回長均線再說", "持股反彈到月線附近減碼"],
        }
        y = ((fund or {}).get("valuations") or {}).get("yield") or {}
        if (fund or {}).get("category") == "stable" and y.get("bands") and close <= y["bands"][0]["price"]:
            cheap = y["bands"][0]["price"]
            target_label = "目標"
            out = {
                "stance": "配息股到便宜價：小量存股", "tone": "bull",
                "entry": [to_tick(cheap * 0.97), to_tick(cheap)], "stop": None,
                "targets": [to_tick(y["bands"][1]["price"])],
                "notes": ["空頭但股價已低於殖利率 5% 便宜價", "存股不設停損，改用分批、控制總部位",
                          "回到 4% 合理價可考慮調節"],
            }

    if out["entry"] and out["stop"] and out["targets"]:
        mid = sum(out["entry"]) / 2
        risk, reward = mid - out["stop"], out["targets"][0] - mid
        out["rr"] = round(reward / risk, 1) if risk > 0 and reward > 0 else None
    else:
        out["rr"] = None
    out["target_label"] = target_label
    out["state"] = state
    out["atr"] = round(at, 2)
    out["rule_set"] = "暫用規則 v0.2"
    return out

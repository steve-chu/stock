"""趨勢狀態：多頭／洗籌碼／盤整／出貨警戒／空頭。

三套方法各回答一個問題，最後合成一個結論：
1. Weinstein 階段分析（主幹）：長均線方向 + 股價在均線哪一側 → 多、盤、空
2. Wyckoff 量價 + 台股籌碼（只在盤整時用）：盤整是在洗籌碼吸貨，還是在出貨？
3. Minervini 趨勢模板（只在多頭時用）：這個多頭夠不夠強？

參數依股票分類調整（循環股反應快、配息股看長、成長股用 Minervini 嚴格標準）。
"""
from analysis import sma

PROFILES = {
    "cyclical": {"label": "循環股參數", "ma": 100, "slope_n": 10, "flat": 0.015, "chip_weight": 2,
                 "desc": "均線 100 日（約 20 週）、反應較快，籌碼權重加倍"},
    "stable": {"label": "配息股參數", "ma": 200, "slope_n": 20, "flat": 0.01, "chip_weight": 1,
               "desc": "均線 200 日（約 40 週），過濾低波動股的假交叉"},
    "growth": {"label": "成長股參數", "ma": 150, "slope_n": 20, "flat": 0.015, "chip_weight": 1, "strict": True,
               "desc": "均線 150 日（30 週），多頭需通過 Minervini 嚴格標準"},
    "default": {"label": "標準參數", "ma": 150, "slope_n": 20, "flat": 0.015, "chip_weight": 1,
                "desc": "Weinstein 原版 30 週均線（150 日）"},
}
CATEGORY_TO_PROFILE = {"cyclical": "cyclical", "stable": "stable", "growth": "growth", "general": "default"}

STATES = {
    "bull": {"label": "多頭", "tone": "bull"},
    "wash": {"label": "洗籌碼", "tone": "wash"},
    "range": {"label": "盤整", "tone": "neutral"},
    "dist": {"label": "出貨警戒", "tone": "warn"},
    "bear": {"label": "空頭", "tone": "bear"},
}


def _item(text, ok, draw=None):
    d = {"text": text, "ok": ok}
    if draw:
        d["draw"] = draw
    return d


def _chips(inst_rows, margin_rows, n=20):
    out = {}
    if inst_rows:
        dates = sorted({r["date"] for r in inst_rows})[-n:]
        keep = set(dates)
        net = {}
        for r in inst_rows:
            if r["date"] in keep and r.get("name") in ("Foreign_Investor", "Investment_Trust"):
                net[r["name"]] = net.get(r["name"], 0) + (r.get("buy") or 0) - (r.get("sell") or 0)
        out["foreign"] = round(net.get("Foreign_Investor", 0) / 1000)
        out["trust"] = round(net.get("Investment_Trust", 0) / 1000)
        out["days"] = len(dates)
    if margin_rows:
        rows = sorted(margin_rows, key=lambda r: r["date"])
        bal = [r.get("MarginPurchaseTodayBalance") or 0 for r in rows]
        if len(bal) > n and bal[-1 - n] > 0:
            out["margin_chg"] = (bal[-1] / bal[-1 - n] - 1) * 100
            out["margin_bal"] = bal[-1]
    return out


def judge(bars, inst_rows, margin_rows, profile_key):
    p = PROFILES.get(profile_key, PROFILES["default"])
    c = [b["close"] for b in bars]
    h = [b["high"] for b in bars]
    l = [b["low"] for b in bars]
    v = [b["volume"] for b in bars]
    i = len(bars) - 1
    N = p["ma"]
    if len(bars) < N + p["slope_n"] + 5:
        return {"state": "range", **STATES["range"], "strength": None, "profile": profile_key,
                "profile_label": p["label"], "profile_desc": p["desc"],
                "sections": [{"name": "資料不足", "used": True,
                              "items": [_item(f"需要至少 {N + p['slope_n'] + 5} 根日 K", False)]}]}

    ma = sma(c, N)
    slope = ma[i] / ma[i - p["slope_n"]] - 1
    above = c[i] > ma[i]
    flat = p["flat"]

    # ---- 1. Weinstein ----
    if above and slope > flat:
        base_state = "bull"
    elif not above and slope < -flat:
        base_state = "bear"
    else:
        base_state = "range"
    w_items = [
        _item(f"收盤{'站上' if above else '跌破'} {N} 日均線（{ma[i]:.2f}）", above,
              {"type": "series", "keys": ["trend_ma"], "line": {"price": ma[i], "label": f"MA{N}"}}),
        _item(f"{N} 日均線近 {p['slope_n']} 日{'上揚' if slope > flat else '下彎' if slope < -flat else '走平'}（{slope * 100:+.1f}%）",
              True if slope > flat else False if slope < -flat else None,
              {"type": "series", "keys": ["trend_ma"], "date": bars[i - p["slope_n"]]["date"]}),
    ]
    up_, dn_ = slope > flat, slope < -flat
    if above and up_:
        wv = ("可以抱／回檔可買", "bull", f"第 2 階段（上升）：股價在 {N} 日線上、均線往上。長線照計畫，回檔就是機會")
    elif not above and up_:
        wv = ("只照價位買", "warn", f"上升中的回檔：跌破 {N} 日線但均線還在往上。不追價，長線照恐慌價位分批；站回 {N} 日線才算回到上升")
    elif above and not up_:
        wv = ("觀察", "neutral", f"第 1 階段（打底）或反彈：站上 {N} 日線但均線還沒往上。等均線翻揚才算轉多")
    elif not above and dn_:
        wv = ("不接刀", "bear", f"第 4 階段（下跌）：跌破 {N} 日線且均線往下。只照恐慌目標區／黑天鵝價位買，不提早接")
    else:
        wv = ("緩一緩", "warn", f"第 3 階段（做頭）或盤整：跌破走平的 {N} 日線。先不加碼，看 Wyckoff 判斷是吸籌還是出貨")
    sections = [{"name": f"Weinstein 階段分析（{N} 日均線）", "key": "weinstein", "used": True, "items": w_items,
                 "what": f"看股價和 {N} 日均線的位置、均線方向，判斷現在在「打底→上升→做頭→下跌」哪一段",
                 "verdict": {"label": wv[0], "tone": wv[1], "text": wv[2]},
                 "overlay": {"series": ["trend_ma"], "shade": True}}]

    # ---- 2. Wyckoff + 籌碼（盤整時決定方向）----
    score, wy = 0, []
    look = 60
    prior = ma[i - look] if i - look >= 0 and ma[i - look] else None
    if prior:
        came_from = (ma[i] / prior - 1) * 100
        dr = {"type": "series", "keys": ["trend_ma"], "date": bars[i - look]["date"]}
        if came_from < -3:
            score += 1
            wy.append(_item(f"盤整前是下跌段（均線 {look} 日 {came_from:+.1f}%），較像打底", True, dr))
        elif came_from > 3:
            score -= 1
            wy.append(_item(f"盤整前是上漲段（均線 {look} 日 {came_from:+.1f}%），要防做頭", False, dr))
        else:
            wy.append(_item(f"盤整前趨勢不明（均線 {look} 日 {came_from:+.1f}%）", None, dr))
    rng_low = min(l[-60:-10]) if len(l) >= 60 else None
    rng_high = max(h[-60:-10]) if len(h) >= 60 else None
    wy_events = []
    if rng_low:
        broke = [j for j in range(i - 9, i + 1) if l[j] < rng_low]
        vol20 = sma(v, 20)
        dr = {"type": "lines", "lines": [{"price": rng_low, "label": "區間低點"}, {"price": rng_high, "label": "區間高點"}],
              "date": bars[broke[0]]["date"] if broke else bars[i - 59]["date"]}
        if broke:
            wy_events.append({"date": bars[broke[0]]["date"], "text": "跌破區間", "pos": "below"})
        if broke and c[i] > rng_low:
            quiet = all(v[j] < (vol20[j] or v[j] + 1) for j in broke)
            score += 1
            wy_events.append({"date": bars[i]["date"], "text": "站回", "pos": "above"})
            wy.append(_item(f"跌破區間低點 {rng_low:.2f} 後站回（Spring）{'，跌破時量縮' if quiet else ''}", True, dr))
        elif broke:
            score -= 1
            wy.append(_item(f"跌破區間低點 {rng_low:.2f} 且未站回", False, dr))
        else:
            wy.append(_item(f"近 10 日未跌破區間低點 {rng_low:.2f}", None, dr))
    up = sum(v[j] for j in range(i - 39, i + 1) if c[j] >= c[j - 1])
    dn = sum(v[j] for j in range(i - 39, i + 1) if c[j] < c[j - 1])
    if dn:
        r = up / dn
        dr = {"type": "range", "date": bars[i - 39]["date"]}
        if r >= 1.2:
            score += 1
            wy.append(_item(f"近 40 日上漲日量是下跌日量 {r:.1f} 倍（買盤承接）", True, dr))
        elif r <= 0.8:
            score -= 1
            wy.append(_item(f"近 40 日上漲日量只有下跌日量 {r:.1f} 倍（賣壓重）", False, dr))
        else:
            wy.append(_item(f"近 40 日漲跌量比 {r:.1f}，均衡", None, dr))

    ch = _chips(inst_rows, margin_rows)
    wgt = p["chip_weight"]
    if "foreign" in ch:
        inst = ch["foreign"] + ch["trust"]
        ok = inst > 0
        score += wgt if ok else -wgt
        wy.append(_item(f"近 {ch['days']} 日外資 {ch['foreign']:+,} 張、投信 {ch['trust']:+,} 張（合計{'買超' if ok else '賣超'}）", ok,
                        {"type": "range", "date": bars[max(0, i - ch["days"] + 1)]["date"]}))
    if "margin_chg" in ch:
        m = ch["margin_chg"]
        if m <= -5:
            score += wgt
            wy.append(_item(f"融資餘額 20 日減少 {abs(m):.1f}%（散戶籌碼被洗出）", True))
        elif m >= 5:
            score -= wgt
            wy.append(_item(f"融資餘額 20 日增加 {m:.1f}%（籌碼變凌亂）", False))
        else:
            wy.append(_item(f"融資餘額 20 日變化 {m:+.1f}%", None))
    if not ch:
        wy.append(_item("抓不到法人、融資資料，只用量價判斷", None))
    if base_state != "range":
        yv = ("只當參考", "neutral", "現在不是盤整，這組主要用在盤整時判斷方向；分數可當籌碼好壞的參考")
    elif score >= 1:
        yv = ("偏買", "bull", "盤整偏向吸籌（主力在收貨）：靠近區間低點或跌破又站回時可以分批")
    elif score <= -1:
        yv = ("只照價位買", "warn", "盤整偏向出貨（主力在倒貨）：不追價、回升段先不加碼；長線只照恐慌價位分批（試單小量）")
    else:
        yv = ("等方向", "neutral", "吸籌、出貨訊號互相抵銷：等跌破或突破區間再決定")
    sections.append({"name": f"Wyckoff 量價 + 籌碼（分數 {score:+d}）", "key": "wyckoff", "used": base_state == "range", "items": wy,
                     "what": "盤整時用量價和法人、融資的進出，判斷主力是在收貨（吸籌）還是倒貨（出貨）",
                     "verdict": {"label": yv[0], "tone": yv[1], "text": yv[2]},
                     "overlay": {"lines": [x for x in ([{"price": rng_low, "label": "區間低點"}, {"price": rng_high, "label": "區間高點"}] if rng_low else [])],
                                 "markers": wy_events, "from": bars[max(0, i - 59)]["date"]}})

    # ---- 3. Minervini ----
    ma50, ma150, ma200 = sma(c, 50), sma(c, 150), sma(c, 200)
    strength, mi, swing = None, [], None
    if ma200[i] is not None and ma200[i - 20] is not None:
        hi52, lo52 = max(h[-250:]), min(l[-250:])
        S = lambda *k: {"type": "series", "keys": list(k)}
        mi = [
            _item("收盤在 150 日與 200 日均線之上", c[i] > ma150[i] and c[i] > ma200[i], S("ma150", "ma200")),
            _item("150 日均線 > 200 日均線", ma150[i] > ma200[i], S("ma150", "ma200")),
            _item("200 日均線至少上揚 1 個月", ma200[i] > ma200[i - 20], {**S("ma200"), "date": bars[i - 20]["date"]}),
            _item("50 日均線 > 150 日、200 日均線", ma50[i] > ma150[i] and ma50[i] > ma200[i], S("ma50", "ma150", "ma200")),
            _item("收盤在 50 日均線之上", c[i] > ma50[i], S("ma50")),
            _item(f"比 52 週低點 {lo52:.2f} 高 30% 以上", c[i] >= lo52 * 1.3,
                  {"type": "lines", "lines": [{"price": lo52, "label": "52週低"}, {"price": lo52 * 1.3, "label": "低點+30%"}]}),
            _item(f"距 52 週高點 {hi52:.2f} 在 25% 以內", c[i] >= hi52 * 0.75,
                  {"type": "lines", "lines": [{"price": hi52, "label": "52週高"}, {"price": hi52 * 0.75, "label": "高點-25%"}]}),
        ]
        passed = sum(1 for x in mi if x["ok"])
        need_strong = 7 if p.get("strict") else 6
        strength = "強" if passed >= need_strong else "中" if passed >= 4 else "弱"
        swing = swing_label(base_state, passed, need_strong)
        mv = (("很強，別太早賣光", "bull", "強勢股：熱的時候用多頭危機訊號分批減碼，不要一次賣光") if passed >= need_strong
              else ("轉弱中", "warn", "強勢條件掉了幾項：回檔別急著接，先看恐慌目標區") if passed >= 4
              else ("弱", "bear", "已經不是強勢股：長線只照恐慌段價位，不提早買"))
        sections.append({"name": f"Minervini 趨勢模板（{passed}/7）", "key": "minervini", "used": base_state == "bull",
                         "items": mi, "swing": swing,
                         "what": "強勢股「突破追買」用的 7 項檢查。你不追突破，所以只拿來看這檔強不強，不當買點",
                         "verdict": {"label": mv[0], "tone": mv[1], "text": mv[2]},
                         "overlay": {"series": ["ma50", "ma150", "ma200"],
                                     "lines": [{"price": hi52, "label": "52週高"}, {"price": lo52, "label": "52週低"}],
                                     "markers": _minervini_days(c, h, l, ma50, ma150, ma200)}})

    if base_state == "range":
        state = "wash" if score >= 1 else "dist" if score <= -1 else "range"
    else:
        state = base_state
    summary = {
        "bull": f"長均線上揚且股價在上方，多頭強度：{strength or '—'}",
        "bear": "長均線下彎且股價在下方，空頭",
        "wash": "長均線走平的盤整，量價和籌碼偏向主力吸籌",
        "dist": "長均線走平的盤整，量價和籌碼偏向出貨，留意轉空",
        "range": "長均線走平的盤整，吸籌、出貨訊號互相抵銷",
    }[state]
    return {
        "state": state, **STATES[state], "strength": strength if state == "bull" else None,
        "summary": summary, "wyckoff_score": score, "chips": ch,
        "profile": profile_key, "profile_label": p["label"], "profile_desc": p["desc"],
        "ma_period": N, "ma_value": round(ma[i], 2), "sections": sections, "swing": swing,
        "slope_n": p["slope_n"], "flat": p["flat"],
        "stages": _stages(c, ma, p),
    }


def swing_label(base_state, passed, need_strong=6):
    """給 30% 短線波段用的標籤。"""
    if base_state == "bull" and passed >= need_strong:
        return {"label": "強勢股・列入波段觀察", "tone": "bull", "code": "good",
                "text": f"多頭且 Minervini 通過 {passed}/7：這是「股票很強」，不是買點；買點看短線波段卡片"}
    if base_state == "bull" and passed >= 4:
        return {"label": "觀察中", "tone": "neutral", "code": "watch",
                "text": f"多頭但只通過 {passed}/7，強度還不夠"}
    return {"label": "不適合參考", "tone": "muted", "code": "no",
            "text": "非多頭或條件不足，Minervini 不適用；長線請看散戶退場、恐慌區間"}


def _criteria_ok(c, h, l, ma50, ma150, ma200, j):
    if None in (ma50[j], ma150[j], ma200[j]) or j < 250 or ma200[j - 20] is None:
        return 0
    hi52, lo52 = max(h[j - 249:j + 1]), min(l[j - 249:j + 1])
    return sum([c[j] > ma150[j] and c[j] > ma200[j], ma150[j] > ma200[j], ma200[j] > ma200[j - 20],
                ma50[j] > ma150[j] and ma50[j] > ma200[j], c[j] > ma50[j], c[j] >= lo52 * 1.3, c[j] >= hi52 * 0.75])


def _minervini_days(c, h, l, ma50, ma150, ma200, n=500):
    """條件 7/7 全部成立的每一段，標出第一天。"""
    out, prev = [], False
    for j in range(max(250, len(c) - n), len(c)):
        ok = _criteria_ok(c, h, l, ma50, ma150, ma200, j) == 7
        if ok and not prev:
            out.append({"idx": j, "text": "7/7", "pos": "below"})
        prev = ok
    return out


def _stages(c, ma, p, n=500):
    """每一根 K 的 Weinstein 狀態，給圖上底色用。"""
    out = []
    for j in range(max(0, len(c) - n), len(c)):
        if ma[j] is None or j < p["slope_n"] or ma[j - p["slope_n"]] is None:
            out.append(None)
            continue
        sl = ma[j] / ma[j - p["slope_n"]] - 1
        if c[j] > ma[j] and sl > p["flat"]:
            out.append("bull")
        elif c[j] < ma[j] and sl < -p["flat"]:
            out.append("bear")
        else:
            out.append("range")
    return out


def swing_status(bars):
    """自選股清單用：只用日 K（不連網）快速判斷 Minervini 波段標籤。"""
    if len(bars) < 270:
        return None
    c = [b["close"] for b in bars]
    h = [b["high"] for b in bars]
    l = [b["low"] for b in bars]
    ma50, ma150, ma200 = sma(c, 50), sma(c, 150), sma(c, 200)
    i = len(c) - 1
    sl = ma150[i] / ma150[i - 20] - 1
    base = "bull" if c[i] > ma150[i] and sl > 0.015 else "other"
    return swing_label(base, _criteria_ok(c, h, l, ma50, ma150, ma200, i))

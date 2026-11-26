"""買賣策略 v0.5：長線（70%）和短線波段（30%）分成兩套。

長線：不設價格停損。體質合格 + 進入恐慌區或估值便宜 + 散戶退場 → 在恐慌區分 3 批布局；
      過熱（估值昂貴、PBR 高檔、漲多、散戶沒走）→ 不追高、分批減碼；
      出場看「基本面停損」（營收連續年減、EPS 明顯衰退），不看價格。
短線：只在多頭 + Minervini 條件成立時做；拉回月線附近、並出現確認訊號才進場；
      MACD/KD 剛死亡交叉不進場；停損放在近期低點下方再留緩衝，收盤連續 2 天跌破才出場；
      第一個壓力區賣一半，剩下跌破月線出場；20 個交易日沒到目標就出場；
      部位大小依「每筆最多虧總資金 X%」計算。
"""

from analysis import _crossed_down, _crossed_up, to_tick

FEE_RT = 0.001425 * 2 + 0.003  # 買賣手續費 + 證交稅（約略）


def _chk(text, ok, value=None):
    return {"text": text, "ok": ok, "value": value}


# ---------- 長線 ----------

def _qty(amount, price):
    sh = int(amount // price) if price > 0 else 0
    lots, odd = divmod(sh, 1000)
    txt = (f"{lots} 張" if lots else "") + (f"{' ' if lots else ''}{odd} 股" if odd else "")
    return sh, (txt or "0 股")


def long_plan(bars, a, regime, fund, retail, zones, danger=None, ma20=None, elig=None, tech=None,
              budget=None):
    """長線 v1.0：資格（合格／觀察／論點警訊）→ 兩段式分批（恐慌段逆勢 50%＋回升段順勢 50%）。"""
    close = bars[-1]["close"]
    f = fund if fund and not fund.get("error") else {}
    vals = f.get("valuations") or {}
    primary = vals.get(f.get("primary_method")) or {}
    r = retail if retail and not retail.get("error") else {}
    z = zones if zones and not zones.get("error") else {}
    el = elig or {"status": "觀察", "tone": "neutral", "warns": [], "core": False}
    tq = tech or {}

    dg = danger if danger and not danger.get("error") else {}
    dlv = dg.get("level") if dg.get("applies") and not dg.get("late") else "healthy"   # 跌深後才亮的危機不算
    crash = dg.get("crash") or {}

    panic = z.get("panic") or []
    strong = [p for p in panic if p["strength"] >= 2]
    in_zone = any(p["lo"] * 0.98 <= close <= p["hi"] * 1.02 for p in strong)
    cheap = primary.get("zone") in ("便宜", "合理偏低")
    rc = r.get("count", 0)
    fear = [
        _chk("股價在恐慌區（≥2 種方法重疊）", in_zone),
        _chk("估值便宜或合理偏低", cheap if primary else None, primary.get("zone") or ("ETF 不適用" if el.get("etf") else None)),
        _chk("散戶退場訊號 ≥ 2", None if not r else rc >= 2, None if not r else f"{rc}/{r.get('total', 0)}"),
    ]

    c = [b["close"] for b in bars]
    hi60 = max(b["high"] for b in bars[-60:])
    dd = 1 - close / hi60
    ddm = (z.get("dd_median") or 0) / 100
    dd_min = max(0.08, ddm * 0.5)                      # 「有意義的回檔」門檻
    ma20v = ma20 or (sum(c[-20:]) / 20)
    ma60v = sum(c[-60:]) / 60 if len(c) >= 60 else None
    ma60p = sum(c[-65:-5]) / 60 if len(c) >= 65 else None
    falling = close < ma20v and dd >= dd_min           # 短期下跌中

    # ---- 恐慌目標區：「到得了」的恐慌區裡最深的一層（退可守的底線；再往下是黑天鵝） ----
    def reachable(t):
        d = t["mid"] / close - 1
        if d < -0.30:
            return False
        rp = t.get("reach") or {}
        if rp.get("of", 0) >= 3 and rp.get("pct") is not None:
            return rp["pct"] >= 30
        return d >= -0.25
    tiers = sorted([t for t in (z.get("panic") or z.get("tiers") or []) if t["mid"] < close * 0.97], key=lambda t: -t["mid"])
    ok_t = [t for t in tiers if reachable(t)]
    rpct = lambda t: (t.get("reach") or {}).get("pct") or 0
    target = min(ok_t, key=lambda t: t["mid"]) if ok_t else None   # 最深、但仍到得了的那層
    low_prob = False
    if not target:   # 沒有「到得了」的，退而求其次：30% 內最近的一層，標示機率偏低
        near = [t for t in tiers if t["mid"] >= close * 0.70]
        if near:
            target, low_prob = near[0], True
            ok_t = [target]
    swan = [t for t in tiers if not target or t["mid"] < target["mid"] * 0.97]

    # ---- 下跌段（逆勢，共 50%）：從現在一路分批到恐慌目標區，越低買越多 ----
    pts = []
    if falling and dlv != "crisis" and (regime or {}).get("state") != "bear":   # 第 4 階段下跌不提早接
        pts.append({"mid": close, "label": "試單：短期下跌中先買一點", "reach": None})
    if target:
        mids = [t for t in ok_t if t["mid"] > target["mid"] * 1.05 and t["mid"] < (pts[0]["mid"] if pts else close) * 0.97]
        mids = sorted(mids, key=lambda t: (-t["strength"], -rpct(t)))[:1]
        start = pts[0]["mid"] if pts else (mids[0]["mid"] if mids else None)
        if mids and pts:
            pts.append(mids[0])
        elif mids:
            pts.append(mids[0])
        elif start and start / target["mid"] > 1.12:
            pts.append({"mid": (start * target["mid"]) ** 0.5, "label": "中途", "reach": None})
        pts.append({**target, "label": "恐慌目標區"})
    pts = pts[:3]

    # ---- 回升段（順勢）：還沒跌到目標就反轉時，用這段跟上 ----
    # 跌破過年線（至少破 3%，貼著年線晃不算）：看半年線、年線
    deep = bool(tq.get("ma240")) and any(c[-k] < tq["ma240"] * 0.97 for k in range(1, min(120, len(c)) + 1))
    if deep:
        lv = [("站回半年線 MA120", tq.get("ma120"), True),
              ("站回年線且年線上揚", tq.get("ma240"), bool(tq.get("ma240_up")))]
        hi120 = max(b["high"] for b in bars[-120:])
        fell = min(c[-120:]) <= hi120 * (1 - dd_min)      # 真的有跌過一段，才有「回升」可言
    else:         # 一般回檔：看月線、季線
        lv = [("止跌：站回月線 MA20", ma20v, True),
              ("轉強：站回季線 MA60 且季線上揚", ma60v, bool(ma60v and ma60p and ma60v > ma60p))]
        lo40 = min(c[-40:])
        hi80 = max(b["high"] for b in bars[-80:])
        fell = lo40 <= hi80 * (1 - dd_min)
    trend_bad = (regime or {}).get("state") in ("dist", "bear")
    rec = []
    for w, p, ok in (lv if fell else []):   # 沒有回檔過，就沒有「回升」可言
        hit = bool(p and fell and ok and p < close <= p * 1.05)
        rec.append({"stage": "回升段", "why": w, "price": p,
                    "met": hit and not trend_bad, "hold": hit and trend_bad})

    rows = [{"stage": "恐慌段", "why": t["label"], "price": t["mid"], "reach": t.get("reach"),
             "met": t["mid"] >= close * 0.999} for t in pts] + rec
    swan_rows = []
    for t in swan[:3]:
        rp = (t.get("reach") or {}).get("pct")
        deep_ok = t["mid"] >= close * 0.70 and (rp is None or rp > 0)
        swan_rows.append({"stage": "深跌備用" if deep_ok else "黑天鵝", "why": t["label"], "price": t["mid"],
                          "reach": t.get("reach"), "met": False})
    cnt = {}
    for t in rows + swan_rows:
        cnt[t["stage"]] = cnt.get(t["stage"], 0) + 1
        t["n"] = cnt[t["stage"]]
        t["price"] = to_tick(t["price"]) if t["price"] else None
        t["dist"] = round((t["price"] / close - 1) * 100, 1) if t["price"] else None
    tgt = None
    if target:
        tgt = {"lo": target["lo"], "hi": target["hi"], "mid": to_tick(target["mid"]),
               "dist": round((target["mid"] / close - 1) * 100, 1), "strength": target["strength"],
               "methods": target["methods"], "reach": target.get("reach"), "low_prob": low_prob}
    pull = {"dd": round(dd * 100, 1), "dd_min": round(dd_min * 100, 1), "falling": falling, "mode": "年線" if deep else "月線／季線"}

    show = el["status"] not in ("論點警訊", "循環股") and (el["core"] or el["status"] == "合格")
    fear_rows = [t for t in rows if t["stage"] == "恐慌段"]
    met_f = [t for t in fear_rows if t["met"]]
    met_r = [t for t in rec if t["met"]]
    held = [t for t in rec if t.get("hold")]
    nxt_dn = next((t for t in fear_rows if not t["met"] and t["price"] and t["price"] < close), None)
    nxt_up = min((t for t in rec if not t["met"] and t["price"] and t["price"] > close), key=lambda t: t["price"], default=None)
    nxt = []
    if nxt_dn:
        nxt.append(f"跌到 {nxt_dn['price']:g} 加碼")
    if nxt_up:
        nxt.append(f"站回 {nxt_up['price']:g} 加碼")
    if el["status"] == "循環股":
        action, tone = "循環股不在這個平台的長線範圍，請用循環股工具判斷", "muted"
    elif el["status"] == "論點警訊":
        action, tone = "論點警訊：先不加碼，確認你看好的理由還成立；有持股的話短線 30% 部位減碼", "warn"
    elif not el["core"] and el["status"] != "合格":
        action, tone = "不在長期名單、體質也不到合格：不做長線", "muted"
    elif crash.get("on"):
        action, tone = "股災警報：短線 30% 部位減碼，資金可轉其他商品；長線 70% 不動", "bear"
    elif dlv in ("watch", "crisis"):
        action, tone = ("高檔轉弱：停止加碼，持股不動（等跌到恐慌價位，或重新站穩月線）" if dg.get("cooling")
                        else f"過熱{'危機' if dlv == 'crisis' else '留意'}：停止加碼，持股不動"), "warn"
    elif met_f:
        t = met_f[-1]
        action, tone = f"可以加碼：恐慌{t['n']}（{t['why']}）", "bull"
    elif met_r:
        t = met_r[-1]
        action, tone = f"可以加碼：回升{t['n']}（{t['why']}）", "bull"
    elif held:
        action, tone = "回升訊號出現，但中期還在出貨／下跌：先不追", "neutral"
    elif not falling and dd >= dd_min:
        action, tone = f"已從高點回檔 {dd * 100:.0f}%，但短期止跌反彈（站上月線）：等下一個價位或回升段", "neutral"
    elif not falling:
        action, tone = f"還沒明顯回檔（距高點 −{dd * 100:.0f}%）：等待", "neutral"
    else:
        action, tone = "等待下一個價位", "neutral"
    decision = {"headline": action, "tone": tone, "next": nxt}

    notes = ["進可攻：短期下跌先買試單，如果還沒到目標區就反轉，用回升段跟上",
             "退可守：分批在越來越低的價位加碼，平均成本往下；跌破目標區的黑天鵝價位才動用備用資金",
             "散戶退場、估值便宜不是買的門檻，而是加分：條件越多，越接近真正的恐慌底",
             "長線持股只增不減；過熱只停止加碼；股災警報才減短線 30% 部位，轉到其他商品"]
    return {"action": action, "tone": tone, "eligibility": el,
            "danger": {"level": dlv, "label": dg.get("label"), "count": dg.get("count"), "total": dg.get("total")},
            "fear": fear, "tranches": rows if show else [], "swan": swan_rows if show else [],
            "target": tgt, "pullback": pull, "hidden_reason": None if show else action, "decision": decision,
            "notes": notes, "crash": crash}


# ---------- 短線波段 ----------

def swing_plan(bars, ind, a, regime, zones, prefs, danger=None):
    i = len(bars) - 1
    close = bars[i]["close"]
    at = ind["atr"][i] or close * 0.02
    ma20 = ind["ma20"][i] or close
    reg = regime if regime and not regime.get("error") else {}
    state = reg.get("state")
    swing = reg.get("swing") or {}
    code = swing.get("code")

    gate = state == "bull" and code in ("good", "watch")
    near = close <= ma20 + 1.0 * at
    k, d, dif, dea = ind["k"], ind["d"], ind["dif"], ind["dea"]
    kd_gold = _crossed_up(k, d, i, 2)
    reclaim = i > 0 and close > bars[i - 1]["high"]
    macd_dead = _crossed_down(dif, dea, i, 3)
    kd_dead = _crossed_down(k, d, i, 3)
    confirmed = kd_gold or reclaim
    blocked = macd_dead or kd_dead
    dg = danger if danger and not danger.get("error") else {}
    risky = dg.get("level") in ("watch", "crisis")

    entry = close if confirmed else ma20 + 0.3 * at
    low20 = min(b["low"] for b in bars[-20:])
    stop = min(low20 - 0.5 * at, entry - 2 * at)
    res = [p for p in ((zones or {}).get("resist") or []) if p["lo"] > entry * 1.02]
    t1 = res[0]["lo"] if res else max(max(b["high"] for b in bars[-60:]), entry + 3 * at)

    risk_ps = entry - stop
    pf = prefs or {}
    size = None
    if risk_ps > 0:
        per_share_loss = risk_ps + entry * FEE_RT
        if pf.get("capital"):
            max_loss = pf["capital"] * pf.get("risk_pct", 1) / 100
            shares = int(max_loss // per_share_loss)
            lots, odd = divmod(shares, 1000)
            qty = (f"{lots} 張" if lots else "") + (f"{' ' if lots else ''}{odd} 股" if odd else "")
            qty = qty or "0 股（停損距離太大或資金太少）"
            size = {"shares": shares, "lots": lots, "max_loss": round(max_loss), "amount": round(shares * entry),
                    "text": f"最多買 {qty}{'（零股）' if shares and not lots else ''}，約 {round(shares * entry):,} 元；"
                            f"虧到停損約 {round(shares * per_share_loss):,} 元"}
        else:
            per_m = int(1_000_000 * pf.get("risk_pct", 1) / 100 / per_share_loss)
            qty = f"{per_m / 1000:.1f} 張" if per_m >= 1000 else f"{per_m} 股（零股）"
            size = {"text": f"每 100 萬資金最多買約 {qty}（每筆最多虧 {pf.get('risk_pct', 1):g}%）。設定資金後會直接算張數"}

    checks = [
        _chk("多頭（Weinstein）", state == "bull", reg.get("label")),
        _chk("Minervini 條件", code in ("good", "watch") if code else None, swing.get("label")),
        _chk("拉回到月線附近（不追高）", near, f"月線 {ma20:.2f}"),
        _chk("確認訊號：KD 黃金交叉或收盤站上前一天高點", confirmed),
        _chk("沒有剛死亡交叉（MACD／KD 3 日內）", not blocked),
        _chk("沒有多頭危機訊號（<2 個）", None if not dg else not risky,
             None if not dg else f"{dg.get('count')}/{dg.get('total')}"),
    ]
    if not gate:
        action, tone = "不做：非多頭或 Minervini 條件不足", "muted"
    elif risky:
        action, tone = "不追：多頭出現危機訊號", "warn"
    elif blocked:
        action, tone = "等待：動能剛轉弱", "neutral"
    elif not near:
        action, tone = "等拉回：離月線太遠，不追", "neutral"
    elif confirmed:
        action, tone = "可進場：拉回後已確認", "bull"
    else:
        action, tone = "在進場區，等確認訊號", "neutral"

    rr = round((t1 - entry) / risk_ps, 1) if risk_ps > 0 and t1 > entry else None
    return {
        "action": action, "tone": tone, "checks": checks,
        "entry": to_tick(entry), "stop": to_tick(stop), "target1": to_tick(t1), "rr": rr,
        "stop_pct": round((stop / entry - 1) * 100, 1), "size": size, "atr": round(at, 2),
        "rules": ["收盤連續 2 天低於停損價才出場（盤中跌破不算）",
                  "到第一個壓力區先賣一半，剩下跌破月線再出",
                  "買進後 20 個交易日沒到壓力區就出場（時間停損）"],
    }


def build(bars, ind, a, regime, fund, retail, zones, prefs, danger=None, elig=None, tech=None, budget=None):
    lp = long_plan(bars, a, regime, fund, retail, zones, danger, ind["ma20"][-1], elig, tech, budget)
    sp = swing_plan(bars, ind, a, regime, zones, prefs, danger)
    lines = [{"price": t["price"], "label": f"{t['stage'][:2]}{t['n']}", "kind": "tranche"} for t in lp["tranches"] if t["price"]]
    if sp["tone"] != "muted":
        lines += [{"price": sp["stop"], "label": "波段停損", "kind": "stop"},
                  {"price": sp["target1"], "label": "壓力1 賣一半", "kind": "target"}]
    return {"long": lp, "swing": sp, "lines": lines, "rule_set": "規則 v1.0"}

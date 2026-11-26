"""散戶退場訊號：散戶是不是正在離開這檔股票。

每一條訊號 exiting=True 代表「散戶正在退場」（對長線布局是好事）。
"""
from analysis import sma


def _pct_rank(vals, x):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return sum(1 for v in vals if v <= x) / len(vals) * 100


def judge(bars, margin_rows):
    sig = []
    c = [b["close"] for b in bars]
    o = [b["open"] for b in bars]
    v = [b["volume"] for b in bars]
    i = len(bars) - 1

    rows = sorted(margin_rows or [], key=lambda r: r["date"])
    bal = [r.get("MarginPurchaseTodayBalance") or 0 for r in rows]
    lim = [r.get("MarginPurchaseLimit") or 0 for r in rows]
    short = [r.get("ShortSaleTodayBalance") or 0 for r in rows]

    # 1. 融資餘額變化
    if len(bal) > 60 and bal[-61] > 0 and bal[-21] > 0:
        c20 = (bal[-1] / bal[-21] - 1) * 100
        c60 = (bal[-1] / bal[-61] - 1) * 100
        sig.append({"label": "融資餘額", "value": f"{bal[-1]:,} 張",
                    "text": f"20 日 {c20:+.1f}%、60 日 {c60:+.1f}%",
                    "exiting": c20 <= -5 or c60 <= -10, "key": "margin"})
    elif len(bal) > 20 and bal[-21] > 0:
        c20 = (bal[-1] / bal[-21] - 1) * 100
        sig.append({"label": "融資餘額", "value": f"{bal[-1]:,} 張", "text": f"20 日 {c20:+.1f}%",
                    "exiting": c20 <= -5, "key": "margin"})

    # 2. 融資使用率（相對自己近一年的位置）
    use = [b / l * 100 if l else None for b, l in zip(bal, lim)]
    if use and use[-1] is not None:
        rank = _pct_rank(use[-250:], use[-1])
        sig.append({"label": "融資使用率", "value": f"{use[-1]:.1f}%",
                    "text": f"在近一年第 {rank:.0f} 百分位" + ("（散戶槓桿偏低）" if rank <= 25 else "（散戶槓桿偏高）" if rank >= 75 else ""),
                    "exiting": rank <= 25, "key": "margin_use"})

    # 3. 融券變化（散戶空單回補完 = 沒人再看空）
    if len(short) > 20 and short[-21] > 0:
        s20 = (short[-1] / short[-21] - 1) * 100
        sig.append({"label": "融券餘額", "value": f"{short[-1]:,} 張", "text": f"20 日 {s20:+.1f}%",
                    "exiting": s20 <= -20, "key": "short"})

    # 4. 成交量萎縮
    v5, v60 = sma(v, 5), sma(v, 60)
    if v60[i]:
        r = v5[i] / v60[i]
        sig.append({"label": "成交量", "value": f"{r:.2f} 倍",
                    "text": "近 5 日均量 ÷ 60 日均量" + ("，明顯量縮" if r <= 0.6 else ""),
                    "exiting": r <= 0.6, "key": "volume"})

    # 5. 爆量長黑後量縮（恐慌殺盤、散戶認賠）
    v20 = sma(v, 20)
    cap = None
    for j in range(max(21, i - 40), i - 2):
        drop = (c[j] / c[j - 1] - 1) * 100
        if v20[j - 1] and v[j] >= 2 * v20[j - 1] and drop <= -4 and c[j] < o[j]:
            cap = j
    if cap is not None:
        after = v[cap + 1:i + 1]
        avg_after = sum(after) / len(after)
        held = min(b["low"] for b in bars[cap + 1:i + 1]) >= bars[cap]["low"] * 0.97
        ok = avg_after <= 0.6 * v[cap] and held
        sig.append({"label": "恐慌殺盤", "value": bars[cap]["date"],
                    "text": f"爆量 {v[cap] / v20[cap - 1]:.1f} 倍、跌 {(c[cap] / c[cap - 1] - 1) * 100:.1f}%；之後"
                            + ("量縮且守住低點，賣壓可能宣洩完" if ok else "仍未止穩"),
                    "exiting": ok, "key": "capitulation", "date": bars[cap]["date"]})
    else:
        sig.append({"label": "恐慌殺盤", "value": "—", "text": "近 40 日沒有爆量長黑", "exiting": False,
                    "key": "capitulation"})

    n = sum(1 for s in sig if s["exiting"])
    level = "明顯" if n >= 3 else "部分" if n >= 1 else "沒有"
    return {"signals": sig, "count": n, "total": len(sig),
            "summary": f"散戶退場訊號 {n}/{len(sig)}：{level}",
            "tone": "bull" if n >= 3 else "neutral" if n >= 1 else "bear",
            "note": "大盤融資維持率、散戶持股比例（股權分散表）需要另外的資料來源，尚未納入"}

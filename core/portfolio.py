"""持股：平均成本、損益兩平價、各價位賣出的淨損益（已扣手續費與證交稅）。

費用假設（可在 .env 調整）：
- 手續費 0.1425%，FEE_DISCOUNT 折扣（1 = 不打折），整股最低 20 元、零股最低 1 元
- 證交稅賣出 0.3%，ETF（代號 00 開頭）0.1%
"""
import math
import os

FEE_RATE = 0.001425
FEE_DISCOUNT = float(os.environ.get("FEE_DISCOUNT", "1") or 1)
MIN_FEE_LOT = 20
MIN_FEE_ODD = 1


def tax_rate(stock_id):
    return 0.001 if stock_id.startswith("00") else 0.003


def fee(amount, shares):
    f = math.floor(amount * FEE_RATE * FEE_DISCOUNT)
    return max(f, MIN_FEE_LOT if shares >= 1000 else MIN_FEE_ODD)


def tax(amount, stock_id):
    return math.floor(amount * tax_rate(stock_id))


def sell_net(stock_id, price, shares):
    amt = price * shares
    return amt - fee(amt, shares) - tax(amt, stock_id)


def replay(stock_id, trades):
    """依時間順序重算持股。賣超過持有股數會回傳錯誤。"""
    shares, cost, realized, rows = 0, 0.0, 0.0, []
    for t in sorted(trades, key=lambda x: (x["date"], x["id"])):
        amt = t["price"] * t["shares"]
        if t["side"] == "buy":
            f = fee(amt, t["shares"])
            shares += t["shares"]
            cost += amt + f
            rows.append({**t, "fee": f, "tax": 0, "amount": round(amt + f)})
        else:
            if t["shares"] > shares:
                return None, f"{t['date']} 賣出 {t['shares']} 股，超過當時持有 {shares} 股"
            avg = cost / shares
            f, tx = fee(amt, t["shares"]), tax(amt, stock_id)
            pnl = amt - f - tx - avg * t["shares"]
            realized += pnl
            cost -= avg * t["shares"]
            shares -= t["shares"]
            rows.append({**t, "fee": f, "tax": tx, "amount": round(amt - f - tx), "pnl": round(pnl)})
        if shares == 0:
            cost = 0.0
    return {"shares": shares, "cost": cost, "realized": round(realized), "rows": rows}, None


def compute(stock_id, trades, close, levels, tick_fn):
    if not trades:
        return {"has_position": False, "trades": [], "realized": 0,
                "fee_note": _fee_note(stock_id)}
    st, err = replay(stock_id, trades)
    if err:
        return {"has_position": False, "error": err, "trades": trades, "realized": 0,
                "fee_note": _fee_note(stock_id)}
    out = {"has_position": st["shares"] > 0, "trades": list(reversed(st["rows"])),
           "realized": st["realized"], "fee_note": _fee_note(stock_id)}
    if st["shares"] <= 0:
        return out
    s, cost = st["shares"], st["cost"]
    keep = 1 - FEE_RATE * FEE_DISCOUNT - tax_rate(stock_id)
    breakeven = cost / (s * keep)
    t = tick_fn(breakeven)
    breakeven = math.ceil(breakeven / t - 1e-9) * t

    def scen(label, price, kind):
        if price is None:
            return None
        net = sell_net(stock_id, price, s) - cost
        return {"label": label, "price": round(price, 2), "kind": kind,
                "net": round(net), "pct": round(net / cost * 100, 2),
                "dist": round((price / close - 1) * 100, 2)}

    scenarios = [scen(*x) for x in levels] + [scen("損益兩平", breakeven, "breakeven")]
    scenarios = sorted([x for x in scenarios if x], key=lambda x: (x["price"], x["kind"] != "now"))
    net_now = sell_net(stock_id, close, s) - cost

    hint = None
    stop = next((x for x in scenarios if x["kind"] == "stop"), None)
    above = [x for x in scenarios if x["kind"] in ("resistance", "target") and x["price"] > close * 1.002]
    if stop and above:
        upside, downside = above[0]["dist"], -stop["dist"]
        if downside > 0:
            ratio = upside / downside
            if ratio < 1:
                hint = {"tone": "bear", "text": f"離上方壓力 {upside:.1f}%、離停損 {downside:.1f}%，上檔空間小於下檔風險，不宜加碼"}
            elif ratio >= 2:
                hint = {"tone": "bull", "text": f"離上方壓力 {upside:.1f}%、離停損 {downside:.1f}%，風險報酬 1:{ratio:.1f}，加碼條件較好"}
            else:
                hint = {"tone": "neutral", "text": f"離上方壓力 {upside:.1f}%、離停損 {downside:.1f}%，風險報酬 1:{ratio:.1f}，普通"}
    elif not above:
        hint = {"tone": "neutral", "text": "股價已在所有壓力之上，用停損價或月線移動停利"}
    out.update({
        "shares": s, "lots": s / 1000, "avg_cost": round(cost / s, 4), "total_cost": round(cost),
        "breakeven": round(breakeven, 2), "market_value": round(close * s),
        "unrealized": round(net_now), "unrealized_pct": round(net_now / cost * 100, 2),
        "scenarios": scenarios, "hint": hint,
    })
    return out


def _fee_note(stock_id):
    d = "不打折" if FEE_DISCOUNT >= 1 else f"{FEE_DISCOUNT * 10:g} 折"
    return f"手續費 0.1425%（{d}）、證交稅 {tax_rate(stock_id) * 100:g}%"

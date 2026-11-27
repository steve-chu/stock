"""手機上的持股計算（JS）要和電腦版 portfolio.py 算出一模一樣的結果。"""
import json
import os
import random
import subprocess

from helpers import ROOT

NODE = r"""
const fs = require('fs');
global.window = { fetch: async () => { throw new Error('no net'); } };
global.document = { baseURI: 'http://x/' };
global.location = { origin: 'http://x' };
global.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
eval(fs.readFileSync(process.argv[1], 'utf8'));
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = cases.map(c => window.kpPortfolio.compute(c.sid, c.trades, c.close, c.levels));
process.stdout.write(JSON.stringify(out));
"""


def make_cases(n=3000, seed=7):
    rnd = random.Random(seed)
    cases = []
    for i in range(n):
        sid = rnd.choice(["2330", "0050", "2317", "00878", "6669"])
        price = rnd.choice([8.5, 23.4, 92.85, 216.5, 1120, 2145])
        trades, held, tid = [], 0, 0
        for d in range(rnd.randint(0, 6)):
            tid += 1
            side = "sell" if held and rnd.random() < .35 else "buy"
            sh = rnd.choice([1, 50, 999, 1000, 2000, 3000])
            if side == "sell":
                sh = min(sh, held) if rnd.random() < .9 else held + 1000   # 偶爾故意賣超過
            p = round(price * rnd.uniform(.85, 1.15), 2)
            trades.append({"id": tid, "stock_id": sid, "date": f"2026-0{1 + d}-1{rnd.randint(0, 9)}", "side": side, "price": p, "shares": sh})
            held += sh if side == "buy" else -sh
        levels = [["停損", round(price * .9, 2), "stop"], ["月線", round(price * .97, 2), "ma"],
                  ["壓力", round(price * 1.08, 2), "resistance"], ["目標", round(price * 1.2, 2), "target"]][: rnd.randint(0, 4)]
        cases.append({"sid": sid, "trades": trades, "close": price, "levels": levels})
    return cases


def test_js_matches_python(app_repo):
    import analysis
    import portfolio
    cases = make_cases()
    js = json.loads(subprocess.run(["node", "-e", NODE, os.path.join(ROOT, "web", "static-api.js")],
                                   input=json.dumps(cases), capture_output=True, text=True, check=True).stdout)
    keys = ("has_position", "realized", "shares", "avg_cost", "total_cost", "breakeven", "market_value", "unrealized", "unrealized_pct")
    for c, j in zip(cases, js):
        py = portfolio.compute(c["sid"], c["trades"], c["close"], [tuple(x) for x in c["levels"]], analysis.tick)
        assert bool(py.get("error")) == bool(j.get("error")), (c, py.get("error"), j.get("error"))
        for k in keys:
            assert py.get(k) == j.get(k), f"{k}: 電腦版 {py.get(k)} ≠ 手機 {j.get(k)}；{c}"
        if py.get("scenarios"):
            assert [(s["price"], s["net"], s["kind"]) for s in py["scenarios"]] == [(s["price"], s["net"], s["kind"]) for s in j["scenarios"]]
        assert (py.get("hint") or {}).get("tone") == (j.get("hint") or {}).get("tone")

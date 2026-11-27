"""電腦版 API：每個網址都打一次，每檔自選股都完整分析一次。手機版的資料就是從這些函式來的。"""
import pytest

from helpers import stock_ids


@pytest.fixture(scope="module")
def client(app_repo):
    from fastapi.testclient import TestClient
    import build
    return TestClient(build.core.app)


def test_status(client):
    r = client.get("/api/status")
    assert r.status_code == 200 and "expected_date" in r.json()


def test_watchlist(client):
    q = client.get("/api/watchlist").json()["quotes"]
    assert {x["stock_id"] for x in q} >= set(stock_ids()[:5])
    for x in q:
        assert x["close"] > 0 and x["name"], x


@pytest.mark.parametrize("sid", stock_ids())
def test_stock_full_analysis(client, sid):
    r = client.get(f"/api/stock/{sid}")
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert len(d["bars"]) > 200, "K 線太少"
    for k in ("analysis", "strategy", "regime", "fundamentals", "danger", "longterm", "zones", "portfolio", "indicators"):
        assert k in d, f"少了 {k}"
    b = d["bars"][-1]
    assert b["low"] <= b["close"] <= b["high"]


@pytest.mark.parametrize("sid", stock_ids()[:3])
def test_bars_week_month(client, sid):
    for tf in ("W", "M"):
        r = client.get(f"/api/bars/{sid}", params={"tf": tf})
        assert r.status_code == 200 and len(r.json()["bars"]) > 10


def test_replay_as_of(client):
    sid = stock_ids()[0]
    bars = client.get(f"/api/stock/{sid}").json()["bars"]
    r = client.get(f"/api/stock/{sid}", params={"as_of": bars[-60]["date"]})
    d = r.json()
    assert r.status_code == 200 and d["analysis_date"] == bars[-60]["date"] and d["replay"]["as_of"] == bars[-60]["date"]
    assert "forward" in d["replay"], "回看要附上之後的實際走勢"


def test_longbt_one_and_all(client):
    stock = [s for s in stock_ids() if not s.startswith("00")][0]
    r = client.get(f"/api/longbt/{stock}")
    assert r.status_code == 200 and "summary" in r.json()
    assert client.get("/api/longbt/0050").status_code in (200, 400)   # ETF 不做回測（回錯誤訊息）
    assert client.get("/api/longbt").status_code == 200


def test_search(client):
    assert client.get("/api/search", params={"q": "台積"}).status_code == 200


def test_trades_buy_sell_delete_csv(client):
    sid = stock_ids()[0]
    close = client.get(f"/api/stock/{sid}").json()["bars"][-1]["close"]
    a = client.post("/api/trades", json={"stock_id": sid, "date": "2026-01-05", "side": "buy", "price": close, "shares": 2000})
    assert a.status_code == 200, a.text
    pf = client.get(f"/api/stock/{sid}").json()["portfolio"]
    assert pf["has_position"] and pf["shares"] == 2000 and pf["breakeven"] > close
    b = client.post("/api/trades", json={"stock_id": sid, "date": "2026-01-06", "side": "sell", "price": close, "shares": 5000})
    assert b.status_code == 400, "賣超過持有應該被擋"
    assert "超過" in b.text
    assert client.get("/api/trades.csv").status_code == 200
    assert client.delete(f"/api/trades/{a.json()['id']}").status_code == 200
    assert not client.get(f"/api/stock/{sid}").json()["portfolio"]["has_position"]


def test_settings_prefs_core(client):
    sid = stock_ids()[0]
    assert client.put(f"/api/core/{sid}", json={"core": True, "reason": "測試", "invalidation": ""}).status_code == 200
    assert client.put("/api/prefs", json={}).status_code in (200, 422)
    assert client.put(f"/api/settings/{sid}", json={}).status_code in (200, 422)


def test_watchlist_add_remove(client):
    have = {q["stock_id"] for q in client.get("/api/watchlist").json()["quotes"]}
    sid = stock_ids()[-1]
    assert client.delete(f"/api/watchlist/{sid}").status_code == 200
    assert sid not in {q["stock_id"] for q in client.get("/api/watchlist").json()["quotes"]}
    assert client.post("/api/watchlist", json={"stock_id": sid}).status_code == 200
    assert {q["stock_id"] for q in client.get("/api/watchlist").json()["quotes"]} == have
    assert client.post("/api/watchlist", json={"stock_id": "??"}).status_code == 400

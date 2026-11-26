"""資料層：從 FinMind 抓台股資料，存進本機 SQLite 快取。

更新規則（盡量少用 API）：
- 先看「應該要有的最新收盤日」：平日 CLOSE_READY（預設 15:00）之後是今天，之前是上一個交易日；
  週六、週日一律是週五。資料庫已經有這天的收盤，就完全不抓。
- 還沒有最新收盤時，才看距離上次抓多久：開 app 自動更新 30 分鐘、點個股 10 分鐘。
- 營收、EPS、股利：一天最多抓一次，週末不抓。
- 網路請求不拿鎖，只有寫入資料庫那一下才上鎖；連線用完就關，並開啟 WAL 讓讀寫可同時進行。
- DEMO=1 時改用隨機示範資料（存在另一個 DB，不會和真資料混在一起）。
"""
import datetime as dt
import glob
import json
import math
import os
import random
import sqlite3
import threading
import time
from contextlib import contextmanager

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

DEMO = os.environ.get("DEMO", "0") == "1"
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
CLOSE_READY = os.environ.get("CLOSE_READY", "15:00")
OPEN_INTERVAL = int(os.environ.get("OPEN_REFRESH_MINUTES", "30")) * 60   # 開 app 自動更新
CLICK_INTERVAL = int(os.environ.get("CLICK_REFRESH_MINUTES", "10")) * 60  # 點個股
PERIODIC_TTL = 24 * 3600
HISTORY_DAYS = 365 * 5   # 分析用：最近 5 年日 K（回看一年前時，之前仍有足夠歷史）
LONG_DAYS = 365 * 20     # 週 K、月 K 用：第一次切到週／月 K 時往前補抓一次，最多 20 年
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "demo.db" if DEMO else "market.db")

DEFAULT_WATCHLIST = ["2330", "2408", "2344", "2337", "6770", "2454", "3260", "8299"]
CORE_SEED = [("2330", ""), ("2317", ""), ("2454", ""), ("2308", ""), ("0050", ""), ("00713", "")]


def is_etf(stock_id):
    return stock_id.startswith("00")

FALLBACK_NAMES = {
    "2330": ("台積電", "半導體業"), "2408": ("南亞科", "半導體業"),
    "2344": ("華邦電", "半導體業"), "2337": ("旺宏", "半導體業"),
    "6770": ("力積電", "半導體業"), "2454": ("聯發科", "半導體業"),
    "3260": ("威剛", "半導體業"), "8299": ("群聯", "半導體業"),
    "2303": ("聯電", "半導體業"), "2317": ("鴻海", "其他電子業"),
    "3711": ("日月光投控", "半導體業"), "2382": ("廣達", "電腦及週邊設備業"),
    "2412": ("中華電", "通信網路業"), "2886": ("兆豐金", "金融保險業"),
    "2308": ("台達電", "電子零組件業"), "0050": ("元大台灣50", "ETF"), "00713": ("元大台灣高息低波", "ETF"),
}

# 資料集：(回推天數, 類型) daily = 每個交易日更新；periodic = 月/季/年才變
DATASETS = {
    "TaiwanStockMonthRevenue": (365 * 7 + 120, "periodic"),
    "TaiwanStockFinancialStatements": (365 * 8, "periodic"),
    "TaiwanStockDividend": (365 * 8, "periodic"),
    "TaiwanStockPER": (365 * 6, "daily"),
    "TaiwanStockInstitutionalInvestorsBuySell": (730, "daily"),   # 2 年：回看一年前也有籌碼
    "TaiwanStockMarginPurchaseShortSale": (730, "daily"),
}

_wlock = threading.Lock()  # 只保護「寫入」，不包網路請求


class SourceError(Exception):
    pass


@contextmanager
def db():
    os.makedirs(DATA_DIR, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db():
    with _wlock, db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS prices(
                stock_id TEXT, date TEXT, open REAL, high REAL, low REAL,
                close REAL, volume INTEGER, PRIMARY KEY(stock_id, date));
            CREATE TABLE IF NOT EXISTS fetch_log(stock_id TEXT PRIMARY KEY, fetched_at REAL);
            CREATE TABLE IF NOT EXISTS stock_info(
                stock_id TEXT PRIMARY KEY, name TEXT, industry TEXT, market TEXT);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS watchlist(stock_id TEXT PRIMARY KEY, sort INTEGER);
            CREATE TABLE IF NOT EXISTS ds_cache(
                dataset TEXT, stock_id TEXT, fetched_at REAL, payload TEXT,
                PRIMARY KEY(dataset, stock_id));
            CREATE TABLE IF NOT EXISTS trades(
                id INTEGER PRIMARY KEY AUTOINCREMENT, stock_id TEXT, date TEXT,
                side TEXT, price REAL, shares INTEGER, created_at REAL);
            CREATE TABLE IF NOT EXISTS stock_settings(
                stock_id TEXT PRIMARY KEY, category TEXT, trend_profile TEXT);
            CREATE TABLE IF NOT EXISTS core_list(
                stock_id TEXT PRIMARY KEY, reason TEXT, invalidation TEXT, added_at REAL);
            """
        )
        if not c.execute("SELECT value FROM meta WHERE key='core_seeded'").fetchone():
            # 我的長期名單（使用者指定）；不在自選股的一併加入
            for sid, why in CORE_SEED:
                c.execute("INSERT OR IGNORE INTO core_list VALUES(?,?,?,?)", (sid, why, "", time.time()))
                n = c.execute("SELECT COALESCE(MAX(sort), -1) + 1 FROM watchlist").fetchone()[0]
                c.execute("INSERT OR IGNORE INTO watchlist VALUES(?,?)", (sid, n))
            c.execute("INSERT OR REPLACE INTO meta VALUES('core_seeded','1')")
        cols = [r[1] for r in c.execute("PRAGMA table_info(ds_cache)")]
        if "last_date" not in cols:  # v0.2 → v0.3
            c.execute("ALTER TABLE ds_cache ADD COLUMN last_date TEXT")
        if "span" not in cols:  # v0.4：記錄抓了幾天，範圍變大時補抓一次
            c.execute("ALTER TABLE ds_cache ADD COLUMN span INTEGER DEFAULT 0")
        if c.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] == 0:
            c.executemany("INSERT INTO watchlist VALUES(?,?)",
                          [(s, i) for i, s in enumerate(DEFAULT_WATCHLIST)])


def backup_db(keep=7):
    """每天第一次啟動備份一份到 data/backup，保留最近 7 份。"""
    if not os.path.exists(DB_PATH):
        return
    bdir = os.path.join(DATA_DIR, "backup")
    os.makedirs(bdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(DB_PATH))[0]
    target = os.path.join(bdir, f"{stem}-{dt.date.today():%Y%m%d}.db")
    if os.path.exists(target):
        return
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    for old in sorted(glob.glob(os.path.join(bdir, f"{stem}-*.db")))[:-keep]:
        os.remove(old)


# ---------- 更新規則 ----------

def expected_date(now=None):
    """資料庫「應該要有」的最新收盤日。"""
    now = now or dt.datetime.now()
    d = now.date()
    hh, mm = (int(x) for x in CLOSE_READY.split(":"))
    if d.weekday() < 5 and now.time() >= dt.time(hh, mm):
        return d
    d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def _price_state(stock_id):
    with db() as c:
        last = c.execute("SELECT MAX(date) FROM prices WHERE stock_id=?", (stock_id,)).fetchone()[0]
        row = c.execute("SELECT fetched_at FROM fetch_log WHERE stock_id=?", (stock_id,)).fetchone()
    return last, (row[0] if row else None)


def price_needs_refresh(stock_id, min_interval, force=False):
    last, fetched = _price_state(stock_id)
    if last is None:
        return True
    if last >= expected_date().isoformat():
        return False  # 已有最新收盤：完全不抓（週末就是週五收盤）
    if force:
        return True
    return fetched is None or time.time() - fetched > min_interval


# ---------- FinMind ----------

def _finmind(dataset, **params):
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    try:
        r = requests.get(FINMIND_URL, params={"dataset": dataset, **params},
                         headers=headers, timeout=20)
    except requests.RequestException as e:
        raise SourceError(f"連不上 FinMind：{e.__class__.__name__}") from e
    try:
        js = r.json()
    except ValueError:
        raise SourceError(f"FinMind 回應無法解析（HTTP {r.status_code}）")
    if r.status_code != 200 or js.get("status") != 200:
        raise SourceError(f"FinMind {dataset}：{js.get('msg') or r.status_code}")
    return js.get("data") or []


# ---------- 日 K ----------

def refresh_prices(stock_id):
    """抓新日 K（網路請求不上鎖）。回傳新增筆數。"""
    last, _ = _price_state(stock_id)
    today = dt.date.today()
    start = dt.date.fromisoformat(last) - dt.timedelta(days=5) if last else today - dt.timedelta(days=HISTORY_DAYS)
    if DEMO:
        rows = _demo_bars(stock_id, start, expected_date())
    else:
        data = _finmind("TaiwanStockPrice", data_id=stock_id,
                        start_date=start.isoformat(), end_date=today.isoformat())
        rows = [
            (stock_id, d["date"], d["open"], d["max"], d["min"], d["close"],
             int(d.get("Trading_Volume") or 0))
            for d in data if d.get("close") and d.get("open")
        ]
    if not rows and not last:
        raise SourceError(f"查無 {stock_id} 的股價資料")
    with _wlock, db() as c:
        c.executemany("INSERT OR REPLACE INTO prices VALUES(?,?,?,?,?,?,?)", rows)
        c.execute("INSERT OR REPLACE INTO fetch_log VALUES(?,?)", (stock_id, time.time()))
    return len([r for r in rows if not last or r[1] > last])


def backfill_prices(stock_id):
    """v0.5 起日 K 存 5 年：舊資料庫只有 3 年的話，往前補抓一次。"""
    key = f"backfill:{stock_id}:{HISTORY_DAYS}"
    if meta_get(key):
        return
    with db() as c:
        first = c.execute("SELECT MIN(date) FROM prices WHERE stock_id=?", (stock_id,)).fetchone()[0]
    want = dt.date.today() - dt.timedelta(days=HISTORY_DAYS)
    if first and dt.date.fromisoformat(first) > want + dt.timedelta(days=40):
        if DEMO:
            rows = [r for r in _demo_bars(stock_id, want, dt.date.fromisoformat(first)) if r[1] < first]
        else:
            data = _finmind("TaiwanStockPrice", data_id=stock_id, start_date=want.isoformat(), end_date=first)
            rows = [(stock_id, d["date"], d["open"], d["max"], d["min"], d["close"], int(d.get("Trading_Volume") or 0))
                    for d in data if d.get("close") and d.get("open") and d["date"] < first]
        with _wlock, db() as c:
            c.executemany("INSERT OR REPLACE INTO prices VALUES(?,?,?,?,?,?,?)", rows)
    meta_set(key, "1")


def backfill_long(stock_id):
    """週 K、月 K 需要長歷史：每檔只往前補抓一次（分段抓，每段 5 年），之後只更新新資料。"""
    key = f"backfill_long:{stock_id}:{LONG_DAYS}"
    if meta_get(key):
        return False
    with db() as c:
        first = c.execute("SELECT MIN(date) FROM prices WHERE stock_id=?", (stock_id,)).fetchone()[0]
    if not first:
        return False
    want = dt.date.today() - dt.timedelta(days=LONG_DAYS)
    end = dt.date.fromisoformat(first)
    rows = []
    while end > want + dt.timedelta(days=10):
        start = max(want, end - dt.timedelta(days=365 * 5))
        if DEMO:
            chunk = [r for r in _demo_bars(stock_id, start, end) if r[1] < end.isoformat()]
        else:
            data = _finmind("TaiwanStockPrice", data_id=stock_id, start_date=start.isoformat(),
                            end_date=(end - dt.timedelta(days=1)).isoformat())
            chunk = [(stock_id, d["date"], d["open"], d["max"], d["min"], d["close"], int(d.get("Trading_Volume") or 0))
                     for d in data if d.get("close") and d.get("open") and d["date"] < end.isoformat()]
        rows += chunk
        if not chunk:  # 更早已經沒有資料（上市較晚）
            break
        end = start
    if rows:
        with _wlock, db() as c:
            c.executemany("INSERT OR REPLACE INTO prices VALUES(?,?,?,?,?,?,?)", rows)
    meta_set(key, "1")
    return bool(rows)


GAP = 0.115


def adjust_splits(bars, skip_head=0, known=None):
    """還原分割／減資：台股漲跌幅限制 10%，開盤跳空超過 11.5% 一定是股票分割、減資這類事件。
    把事件之前的價格乘上跳空比例（成交量反向調整），讓前後可以比較。例：0050 2025-06-18 一拆四。
    （除息的跳空在 10% 以內，不會被當成分割。）
    known = {日期: 股數倍數}：財報股數已確認的事件用確切倍數；開盤價可能偏離參考價上下 10%，只當備用。"""
    if len(bars) < 2:
        return bars
    known = known or {}
    f, out = 1.0, [None] * len(bars)
    for i in range(len(bars) - 1, -1, -1):
        b = bars[i]
        out[i] = b if f == 1.0 else {**b, "open": round(b["open"] * f, 4), "high": round(b["high"] * f, 4),
                                     "low": round(b["low"] * f, 4), "close": round(b["close"] * f, 4),
                                     "volume": int(b["volume"] / f)}
        if i > skip_head and bars[i - 1]["close"]:
            r = (b["open"] or b["close"]) / bars[i - 1]["close"]
            if r < 1 - GAP or r > 1 + GAP:
                f *= 1 / known[b["date"]] if known.get(b["date"]) else r
    return out


def known_splits(stock_id):
    """已經用財報股數確認過的除權／分割／減資：{日期: 股數倍數}（fundamentals 確認後存進 meta）。"""
    try:
        return {k: float(v) for k, v in json.loads(meta_get(f"splits:{stock_id}") or "{}").items()}
    except Exception:
        return {}


def price_events(stock_id, until=None, skip_head=5):
    """原始股價裡的大跳空（> 11.5%，漲跌幅限制外，只可能是除權、分割、減資）。
    k_p = 前一天收盤 ÷ 當天開盤 ≈ 股數變幾倍（開盤會偏離參考價，所以只是概略值）。"""
    with db() as c:
        rows = c.execute("SELECT date, open, close FROM prices WHERE stock_id=? AND date <= ? ORDER BY date",
                         (stock_id, until or "9999-12-31")).fetchall()
    out = []
    for i in range(max(1, skip_head + 1), len(rows)):
        prev, cur = rows[i - 1]["close"], rows[i]["open"] or rows[i]["close"]
        if prev and cur:
            r = cur / prev
            if r < 1 - GAP or r > 1 + GAP:
                out.append({"date": rows[i]["date"], "prev": prev, "open": cur, "k_p": round(prev / cur, 4)})
    return out


def has_dataset(stock_id, dataset):
    with db() as c:
        return c.execute("SELECT 1 FROM ds_cache WHERE stock_id=? AND dataset=?", (stock_id, dataset)).fetchone() is not None


def raw_closes(stock_id, until=None):
    """未還原的收盤價（算「當時」的殖利率要用當時真正的股價）。"""
    with db() as c:
        rows = c.execute("SELECT date, close FROM prices WHERE stock_id=? AND date <= ? ORDER BY date",
                         (stock_id, until or "9999-12-31")).fetchall()
    return [(r[0], r[1]) for r in rows]


def long_bars(stock_id):
    """全部日 K（含長歷史），只給週 K、月 K 合成用。"""
    with db() as c:
        rows = c.execute("SELECT date, open, high, low, close, volume FROM prices WHERE stock_id=? ORDER BY date",
                         (stock_id,)).fetchall()
    return adjust_splits([dict(r) for r in rows], skip_head=5, known=known_splits(stock_id))


def get_prices(stock_id, min_interval=CLICK_INTERVAL, force=False, refresh=True):
    warning, updated = None, False
    if refresh:
        try:
            backfill_prices(stock_id)
        except SourceError as e:
            warning = str(e)
    if refresh and price_needs_refresh(stock_id, min_interval, force):
        try:
            updated = refresh_prices(stock_id) > 0
        except SourceError as e:
            warning = str(e)
    since = (dt.date.today() - dt.timedelta(days=HISTORY_DAYS)).isoformat()
    with db() as c:  # 分析只用最近 5 年（長歷史只給週 K、月 K）
        bars = c.execute("SELECT date, open, high, low, close, volume FROM prices "
                         "WHERE stock_id=? AND date >= ? ORDER BY date", (stock_id, since)).fetchall()
        row = c.execute("SELECT fetched_at FROM fetch_log WHERE stock_id=?", (stock_id,)).fetchone()
    if not bars:
        raise SourceError(warning or f"查無 {stock_id} 的股價資料")
    last = bars[-1]["date"]
    return {"bars": adjust_splits([dict(b) for b in bars], known=known_splits(stock_id)), "fetched_at": row[0] if row else None,
            "warning": warning, "updated": updated,
            "up_to_date": last >= expected_date().isoformat()}


def cached_bars(stock_id, n=300):
    """只讀資料庫的最近 n 根日 K（自選股標籤用）。"""
    with db() as c:
        rows = c.execute("SELECT date, open, high, low, close, volume FROM prices WHERE stock_id=? "
                         "ORDER BY date DESC LIMIT ?", (stock_id, n)).fetchall()
    return adjust_splits([dict(r) for r in reversed(rows)], known=known_splits(stock_id))


def meta_get(key):
    with db() as c:
        r = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r[0] if r else None


def meta_set(key, value):
    with _wlock, db() as c:
        c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, value))


PREF_DEFAULTS = {"risk_pct": 1.0, "cash_pct": 20.0, "stock_pct": 15.0, "sector_pct": 40.0}


def prefs():
    if not meta_get("migr:rev_rule_trend"):   # v1.16：營收規則預設改成「趨勢」（只切換一次，之後照你在選單選的）
        meta_set("pref:rev_rule", "trend")
        meta_set("migr:rev_rule_trend", "1")
    out = {"rev_rule": meta_get("pref:rev_rule") or "trend"}
    for k in ("capital", "long_capital"):
        v = meta_get(f"pref:{k}")
        out[k] = float(v) if v else None
    for k, d in PREF_DEFAULTS.items():
        v = meta_get(f"pref:{k}")
        out[k] = float(v) if v else d
    return out


def prefs_save(**kw):
    for k, v in kw.items():
        if v is not None:
            meta_set(f"pref:{k}", str(v))
    return prefs()


# ---------- 我的長期名單 ----------

def core_get(stock_id):
    with db() as c:
        r = c.execute("SELECT reason, invalidation FROM core_list WHERE stock_id=?", (stock_id,)).fetchone()
    return {"core": bool(r), "reason": r["reason"] if r else "", "invalidation": r["invalidation"] if r else ""}


def core_ids():
    with db() as c:
        return {r[0] for r in c.execute("SELECT stock_id FROM core_list")}


def core_save(stock_id, core, reason=None, invalidation=None):
    with _wlock, db() as c:
        if not core:
            c.execute("DELETE FROM core_list WHERE stock_id=?", (stock_id,))
        else:
            cur = c.execute("SELECT reason, invalidation FROM core_list WHERE stock_id=?", (stock_id,)).fetchone()
            c.execute("INSERT OR REPLACE INTO core_list VALUES(?,?,?,?)",
                      (stock_id, reason if reason is not None else (cur["reason"] if cur else ""),
                       invalidation if invalidation is not None else (cur["invalidation"] if cur else ""), time.time()))
    return core_get(stock_id)


def cached_quote_bars(stock_id, n=31):
    with db() as c:
        rows = c.execute("SELECT date, close FROM prices WHERE stock_id=? ORDER BY date DESC LIMIT ?",
                         (stock_id, n)).fetchall()
    return [dict(r) for r in reversed(rows)]


# ---------- 其他資料集 ----------

def _dataset_needs(row, kind, force, back_days=0):
    if not row:
        return True
    if (row["span"] or 0) < back_days:
        return True
    age = time.time() - row["fetched_at"]
    if kind == "daily":
        if row["last_date"] and row["last_date"] >= expected_date().isoformat():
            return False
        return force or age > CLICK_INTERVAL
    if dt.date.today().weekday() >= 5:  # 週末不更新月/季資料
        return False
    return age > (3600 if force else PERIODIC_TTL)


# 財報只存 EPS 和「歸屬母公司淨利」：淨利 ÷ EPS = 股數，用來確認除權、分割後股數變幾倍
FS_TYPES = ("EPS", "EquityAttributableToOwnersOfParent")

KEEP = {  # 只存用得到的欄位，資料庫小很多
    "TaiwanStockMonthRevenue": ("date", "revenue", "revenue_year", "revenue_month"),
    "TaiwanStockFinancialStatements": ("date", "type", "value"),
    "TaiwanStockDividend": ("date", "year", "AnnouncementDate", "CashEarningsDistribution", "CashStatutorySurplus",
                            "CashExDividendTradingDate"),
    "TaiwanStockPER": ("date", "PER", "PBR", "dividend_yield"),
    "TaiwanStockInstitutionalInvestorsBuySell": ("date", "name", "buy", "sell"),
    "TaiwanStockMarginPurchaseShortSale": ("date", "MarginPurchaseTodayBalance", "MarginPurchaseLimit", "ShortSaleTodayBalance"),
}


def _slim(dataset, data):
    if dataset == "TaiwanStockFinancialStatements":
        data = [d for d in data if d.get("type") in FS_TYPES]
    elif dataset == "TaiwanStockInstitutionalInvestorsBuySell":
        data = [d for d in data if d.get("name") in ("Foreign_Investor", "Investment_Trust")]
    keys = KEEP.get(dataset)
    return [{k: d.get(k) for k in keys if k in d} for d in data] if keys else data


def get_dataset(dataset, stock_id, force=False):
    """回傳 (rows, warning)。"""
    back_days, kind = DATASETS[dataset]
    with db() as c:
        row = c.execute("SELECT fetched_at, payload, last_date, span FROM ds_cache WHERE dataset=? AND stock_id=?",
                        (dataset, stock_id)).fetchone()
    schema_old = False   # v1.12：股利多存「除息日」，舊快取沒有這欄就補抓一次
    if row and dataset == "TaiwanStockDividend":
        rows0 = json.loads(row["payload"])
        schema_old = bool(rows0) and all("CashExDividendTradingDate" not in r for r in rows0)
    if row and dataset == "TaiwanStockFinancialStatements" and not meta_get(f"fsv2:{stock_id}"):
        schema_old = True   # v1.19：財報多存淨利（確認除權股數用），舊快取補抓一次
    if not schema_old and not _dataset_needs(row, kind, force, back_days):
        return json.loads(row["payload"]), None
    full_start = (dt.date.today() - dt.timedelta(days=back_days)).isoformat()
    # 每日資料（本益比、法人、融資）：已有完整範圍時，只抓最後一天往前 5 天之後的新資料再合併
    incremental = kind == "daily" and row and (row["span"] or 0) >= back_days and row["last_date"]
    start = ((dt.date.fromisoformat(row["last_date"]) - dt.timedelta(days=5)).isoformat()
             if incremental else full_start)
    try:
        data = _demo_dataset(dataset, stock_id, start) if DEMO else \
            _finmind(dataset, data_id=stock_id, start_date=start)
    except SourceError as e:
        return (json.loads(row["payload"]) if row else []), str(e)
    data = _slim(dataset, data)
    if incremental:
        new = [d for d in data if str(d.get("date", ""))[:10] >= start]
        old = [d for d in json.loads(row["payload"]) if full_start <= str(d.get("date", ""))[:10] < start]
        data = old + new
    last_date = max((str(d.get("date", ""))[:10] for d in data), default=None)
    with _wlock, db() as c:
        c.execute("INSERT OR REPLACE INTO ds_cache(dataset, stock_id, fetched_at, payload, last_date, span) "
                  "VALUES(?,?,?,?,?,?)",
                  (dataset, stock_id, time.time(), json.dumps(data, ensure_ascii=False), last_date, back_days))
    if dataset == "TaiwanStockFinancialStatements":
        meta_set(f"fsv2:{stock_id}", "1")
    return data, None


def div_series(stock_id, bars):
    """現金股利（除息日, 每股金額），換算成和 bars 一樣的還原基準（分割、除權後的股數），算含息報酬用。
    換算倍數 = 除息前一天的原始收盤 ÷ 還原收盤，和 K 線圖用的完全一樣。只讀資料庫。"""
    import bisect
    rows = get_dataset_cached("TaiwanStockDividend", stock_id)
    if not rows or not bars:
        return []
    raw = dict(raw_closes(stock_id))
    dates = [b["date"] for b in bars]
    out = []
    for r in rows:
        try:
            cash = float(r.get("CashEarningsDistribution") or 0) + float(r.get("CashStatutorySurplus") or 0)
        except (TypeError, ValueError):
            continue
        ex = str(r.get("CashExDividendTradingDate") or "")[:10]
        if cash <= 0 or len(ex) != 10:
            continue
        i = bisect.bisect_left(dates, ex) - 1
        if i < 0 or not raw.get(dates[i]) or not bars[i]["close"]:
            continue
        out.append((ex, cash / (raw[dates[i]] / bars[i]["close"])))
    return sorted(out)


def get_dataset_cached(dataset, stock_id):
    with db() as c:
        row = c.execute("SELECT payload FROM ds_cache WHERE dataset=? AND stock_id=?", (dataset, stock_id)).fetchone()
    return json.loads(row["payload"]) if row else []


# ---------- 股票清單（搜尋用，7 天更新一次） ----------

def ensure_stock_info():
    with db() as c:
        row = c.execute("SELECT value FROM meta WHERE key='stock_info_at'").fetchone()
    if row and time.time() - float(row[0]) < 7 * 86400:
        return
    try:
        if DEMO:
            rows = [(k, v[0], v[1], "twse") for k, v in FALLBACK_NAMES.items()]
        else:
            seen = {}
            for d in _finmind("TaiwanStockInfo"):
                sid = d.get("stock_id")
                if sid and sid not in seen:
                    seen[sid] = (sid, d.get("stock_name"), d.get("industry_category"), d.get("type"))
            rows = list(seen.values())
    except SourceError:
        return
    if rows:
        with _wlock, db() as c:
            c.execute("DELETE FROM stock_info")
            c.executemany("INSERT INTO stock_info VALUES(?,?,?,?)", rows)
            c.execute("INSERT OR REPLACE INTO meta VALUES('stock_info_at', ?)", (str(time.time()),))


def stock_meta(stock_id):
    with db() as c:
        r = c.execute("SELECT name, industry, market FROM stock_info WHERE stock_id=?",
                      (stock_id,)).fetchone()
    if r:
        return {"name": r["name"], "industry": r["industry"], "market": r["market"]}
    name, ind = FALLBACK_NAMES.get(stock_id, (stock_id, ""))
    return {"name": name, "industry": ind, "market": ""}


def search_stocks(q, limit=12):
    q = (q or "").strip()
    if not q:
        return []
    with db() as c:
        rows = c.execute(
            "SELECT stock_id, name, industry FROM stock_info WHERE stock_id LIKE ? OR name LIKE ? "
            "ORDER BY (stock_id = ?) DESC, LENGTH(stock_id), stock_id LIMIT ?",
            (q + "%", "%" + q + "%", q, limit)).fetchall()
    return [dict(r) for r in rows]


# ---------- 自選股 ----------

def watchlist_ids():
    with db() as c:
        return [r[0] for r in c.execute("SELECT stock_id FROM watchlist ORDER BY sort")]


def watchlist_add(stock_id):
    with _wlock, db() as c:
        n = c.execute("SELECT COALESCE(MAX(sort), -1) + 1 FROM watchlist").fetchone()[0]
        c.execute("INSERT OR IGNORE INTO watchlist VALUES(?,?)", (stock_id, n))


def watchlist_remove(stock_id):
    with _wlock, db() as c:
        c.execute("DELETE FROM watchlist WHERE stock_id=?", (stock_id,))


# ---------- 交易紀錄 ----------

def trades(stock_id=None):
    with db() as c:
        if stock_id:
            rows = c.execute("SELECT * FROM trades WHERE stock_id=? ORDER BY date, id", (stock_id,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM trades ORDER BY stock_id, date, id").fetchall()
        return [dict(r) for r in rows]


def trade_add(stock_id, date, side, price, shares):
    with _wlock, db() as c:
        cur = c.execute("INSERT INTO trades(stock_id, date, side, price, shares, created_at) "
                        "VALUES(?,?,?,?,?,?)", (stock_id, date, side, price, shares, time.time()))
        return cur.lastrowid


def trade_delete(trade_id):
    with _wlock, db() as c:
        c.execute("DELETE FROM trades WHERE id=?", (trade_id,))


# ---------- 個股設定 ----------

def settings(stock_id):
    with db() as c:
        r = c.execute("SELECT category, trend_profile FROM stock_settings WHERE stock_id=?",
                      (stock_id,)).fetchone()
    return {"category": (r["category"] if r else None) or "auto",
            "trend_profile": (r["trend_profile"] if r else None) or "auto"}


def settings_save(stock_id, category=None, trend_profile=None):
    cur = settings(stock_id)
    if category is not None:
        cur["category"] = category
    if trend_profile is not None:
        cur["trend_profile"] = trend_profile
    with _wlock, db() as c:
        c.execute("INSERT OR REPLACE INTO stock_settings VALUES(?,?,?)",
                  (stock_id, cur["category"], cur["trend_profile"]))
    return cur


# ---------- 示範資料 ----------

DEMO_KIND = {
    "2408": "cyclical", "2344": "cyclical", "2337": "cyclical", "6770": "cyclical", "3260": "cyclical",
    "2330": "growth", "2454": "growth", "8299": "growth", "2382": "growth",
    "2303": "stable", "2317": "stable", "3711": "stable", "2412": "stable", "2886": "stable",
}


def _rnd(stock_id, salt=0):
    return random.Random((int(stock_id) if stock_id.isdigit() else abs(hash(stock_id))) * 31 + salt)


def _demo_bars(stock_id, start, end):
    rnd = _rnd(stock_id)
    price = rnd.uniform(30, 900)
    drift = rnd.uniform(-0.0004, 0.0012)
    day = dt.date.today() - dt.timedelta(days=LONG_DAYS)
    rows = []
    while day <= end:
        if day.weekday() < 5:
            ret = drift + rnd.gauss(0, 0.019)
            o = price * (1 + rnd.gauss(0, 0.006))
            cl = max(1.0, price * (1 + ret))
            hi = max(o, cl) * (1 + abs(rnd.gauss(0, 0.008)))
            lo = min(o, cl) * (1 - abs(rnd.gauss(0, 0.008)))
            vol = int(rnd.uniform(2e6, 3e7) * (1 + 6 * abs(ret)))
            if day >= start:
                rows.append((stock_id, day.isoformat(), round(o, 2), round(hi, 2),
                             round(lo, 2), round(cl, 2), vol))
            price = cl
        day += dt.timedelta(days=1)
    return rows


def _latest_reported_quarter(today):
    """台股季報公布期限：Q1 5/15、Q2 8/14、Q3 11/14、Q4 隔年 3/31。"""
    y = today.year
    if today >= dt.date(y, 11, 14): return y, 3
    if today >= dt.date(y, 8, 14): return y, 2
    if today >= dt.date(y, 5, 15): return y, 1
    if today >= dt.date(y, 3, 31): return y - 1, 4
    return y - 1, 3


def _demo_eps(stock_id):
    kind = DEMO_KIND.get(stock_id, "stable")
    rnd = _rnd(stock_id, 7)
    ly, lq = _latest_reported_quarter(dt.date.today())
    out, t = [], 0
    for y in range(ly - 6, ly + 1):
        for q in range(1, 5):
            if (y, q) > (ly, lq):
                break
            if kind == "cyclical":
                v = 1.2 + 2.6 * math.sin(2 * math.pi * t / 14 + rnd.uniform(-.2, .2)) + rnd.gauss(0, .25)
            elif kind == "growth":
                v = 2.0 * (1.22 ** (t / 4)) * (1 + rnd.gauss(0, .06))
            else:
                v = 1.3 + rnd.gauss(0, .12)
            out.append((y, q, round(v, 2)))
            t += 1
    return kind, out


def _demo_dataset(dataset, stock_id, start):
    kind, eps = _demo_eps(stock_id)
    rnd = _rnd(stock_id, hash(dataset) % 1000)
    qend = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
    if dataset == "TaiwanStockFinancialStatements":
        return [{"date": f"{y}-{qend[q]}", "stock_id": stock_id, "type": "EPS", "value": v,
                 "origin_name": "基本每股盈餘（元）"} for y, q, v in eps]
    if dataset == "TaiwanStockMonthRevenue":
        rows, today = [], dt.date.today()
        epsq = {(y, q): v for y, q, v in eps}
        for y in range(today.year - 6, today.year + 1):
            for m in range(1, 13):
                if (y, m) >= (today.year, today.month):
                    break
                q = (m - 1) // 3 + 1
                e = epsq.get((y, q), eps[-1][2])
                base = {"cyclical": 30 + 6 * e, "growth": 20 * e, "stable": 50 + 3 * (y - today.year + 6)}[kind]
                rows.append({"date": f"{y + (m == 12)}-{m % 12 + 1:02d}-01", "stock_id": stock_id,
                             "country": "Taiwan", "revenue": int(max(5, base) * 1e8 * (1 + rnd.gauss(0, .04))),
                             "revenue_month": m, "revenue_year": y, "create_time": ""})
        return rows
    if dataset == "TaiwanStockDividend":
        annual = {}
        for y, q, v in eps:
            annual.setdefault(y, []).append(v)
        payout = {"cyclical": .5, "growth": .45, "stable": .85}[kind]
        rows = []
        for y, vs in annual.items():
            if len(vs) < 4:
                continue
            cash = round(max(0.0, sum(vs) * payout), 2)
            rows.append({"date": f"{y + 1}-06-30", "stock_id": stock_id, "year": f"{y - 1911}年",
                         "CashEarningsDistribution": cash, "CashStatutorySurplus": 0,
                         "StockEarningsDistribution": 0, "CashExDividendTradingDate": f"{y + 1}-07-15"})
        return rows
    bars = get_prices(stock_id)["bars"]
    if dataset == "TaiwanStockPER":
        ttm = {}
        for i in range(3, len(eps)):
            ttm[(eps[i][0], eps[i][1])] = sum(e[2] for e in eps[i - 3:i + 1])
        bv0 = bars[0]["close"] / rnd.uniform(1.2, 3.5)
        rows = []
        for i, b in enumerate(bars):
            d = dt.date.fromisoformat(b["date"])
            bv = bv0 * (1 + 0.08 * i / 250)
            key = max([k for k in ttm if dt.date(k[0], k[1] * 3, 1) < d] or [None], key=lambda k: k or (0, 0))
            t = ttm.get(key, 0) if key else 0
            rows.append({"date": b["date"], "stock_id": stock_id,
                         "dividend_yield": round(max(t, 0) * .5 / b["close"] * 100, 2),
                         "PER": round(b["close"] / t, 2) if t > 0 else 0,
                         "PBR": round(b["close"] / bv, 2)})
        return rows
    if dataset == "TaiwanStockInstitutionalInvestorsBuySell":
        rows = []
        for i, b in enumerate(bars[-500:]):
            for name, scale in (("Foreign_Investor", 3e6), ("Investment_Trust", 6e5), ("Dealer_self", 2e5)):
                net = rnd.gauss(0.1, 1) * scale
                rows.append({"date": b["date"], "stock_id": stock_id, "name": name,
                             "buy": int(scale * 2 + max(net, 0)), "sell": int(scale * 2 + max(-net, 0))})
        return rows
    if dataset == "TaiwanStockMarginPurchaseShortSale":
        bal, rows = rnd.uniform(5000, 40000), []
        limit = int(bal * 6)
        sh = bal * .05
        for b in bars[-500:]:
            bal = max(100, bal * (1 + rnd.gauss(-0.002, 0.015)))
            sh = max(10, sh * (1 + rnd.gauss(0, 0.04)))
            rows.append({"date": b["date"], "stock_id": stock_id, "MarginPurchaseTodayBalance": int(bal),
                         "MarginPurchaseLimit": limit, "ShortSaleTodayBalance": int(sh)})
        return rows
    return []

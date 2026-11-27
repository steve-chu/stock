"""測試共用工具：把整個專案複製到暫存資料夾再跑，不會動到真的資料庫和 site/。
資料一律用 seed/market.db、不連網路（OFFLINE=1），所以每次結果都一樣。"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = shutil.ignore_patterns("site", "data", ".git", "node_modules", "__pycache__", ".wrangler", ".pytest_cache")


def copy_repo(dst):
    shutil.copytree(ROOT, dst, ignore=SKIP)
    os.makedirs(os.path.join(dst, "core", "data"), exist_ok=True)
    shutil.copy(os.path.join(ROOT, "seed", "market.db"), os.path.join(dst, "core", "data", "market.db"))
    return dst


def stock_ids(repo=ROOT):
    out = []
    for line in open(os.path.join(repo, "stocks.txt"), encoding="utf-8"):
        sid = line.split("#")[0].strip().upper()
        if sid and sid not in out:
            out.append(sid)
    return out


def run_env(**extra):
    env = dict(os.environ, OFFLINE="1", TZ="Asia/Taipei", PYTHONDONTWRITEBYTECODE="1")
    env.pop("RELAY_URL", None)
    env.update(extra)
    return env


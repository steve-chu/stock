"""測試共用的 fixture（工具函式在 helpers.py）。"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import copy_repo, run_env  # noqa: E402


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    """跑一次完整的每日建置（不連網路），回傳專案資料夾；site/ 在裡面。"""
    repo = copy_repo(str(tmp_path_factory.mktemp("build") / "repo"))
    r = subprocess.run([sys.executable, "build.py"], cwd=repo, env=run_env(), capture_output=True, text=True, timeout=900)
    print(r.stdout[-3000:], r.stderr[-3000:])
    assert r.returncode == 0, "每日建置失敗"
    return repo


@pytest.fixture(scope="session")
def app_repo(tmp_path_factory):
    """給「電腦版 API」測試用的另一份專案（會寫入交易等資料，和建置分開）。"""
    repo = copy_repo(str(tmp_path_factory.mktemp("app") / "repo"))
    os.environ.update(OFFLINE="1", TZ="Asia/Taipei")
    sys.path.insert(0, repo)
    import build  # noqa: F401  套用不連網路的設定，順便載入電腦版 app
    return repo

"""状态文件原子写：并发写互不截断，序列化/落盘失败必须记账而不是静默。"""
import json
import threading

from cchud_next import host as host_mod

from hostfakes import make_host


def _host(tmp_path):
    h = make_host(tmp_path)
    h.status = {"layout": "card"}
    return h


def test_concurrent_writes_use_distinct_tmp_files(tmp_path, monkeypatch):
    h = _host(tmp_path)
    h.status.update({"count": 0, "blob": "x" * 4096})
    used: list[str] = []
    lock = threading.Lock()
    real_replace = host_mod.os.replace

    def spy(src, dst):
        with lock:
            used.append(str(src))
        return real_replace(src, dst)

    monkeypatch.setattr(host_mod.os, "replace", spy)

    def worker(i: int) -> None:
        h.status["count"] = i
        for _ in range(20):
            h._write_status()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(used) == 6 * 20
    assert len(set(used)) == len(used), "旧实现用固定 runtime.tmp，并发写会互相截断"
    assert "status_write_error" not in h.status
    data = json.loads(h.status_path.read_text(encoding="utf-8"))
    assert isinstance(data["count"], int)
    assert not list(h.status_path.parent.glob("*.tmp"))


def test_write_uses_instance_status_path(tmp_path):
    h = _host(tmp_path)
    h.status["marker"] = "mine"
    h._write_status()
    assert json.loads(h.status_path.read_text(encoding="utf-8"))["marker"] == "mine"


def test_unserializable_status_is_recorded_not_raised(tmp_path):
    h = _host(tmp_path)
    h.status["bad"] = object()
    h._write_status()                      # 旧实现只捕 OSError，TypeError 会冲出去
    assert "TypeError" in h.status["status_write_error"]


def test_circular_status_is_recorded(tmp_path):
    h = _host(tmp_path)
    loop: dict = {}
    loop["self"] = loop
    h.status["loop"] = loop
    h._write_status()
    assert "ValueError" in h.status["status_write_error"]


def test_replace_failure_is_recorded_and_leaves_no_tmp(tmp_path, monkeypatch):
    h = _host(tmp_path)

    def boom(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(host_mod.os, "replace", boom)
    h._write_status()
    assert "No space left" in h.status["status_write_error"]
    assert not list(h.status_path.parent.glob("*.tmp"))


def test_permission_error_is_retried_then_succeeds(tmp_path, monkeypatch):
    """另一个 HUD 进程短暂占住 runtime.json：重试一次就能写成功。"""
    h = _host(tmp_path)
    h.status["marker"] = "after-retry"
    monkeypatch.setattr(host_mod, "_STATUS_REPLACE_DELAY", 0.0)
    real_replace = host_mod.os.replace
    calls: list[int] = []

    def flaky(src, dst):
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError(13, "拒绝访问")
        return real_replace(src, dst)

    monkeypatch.setattr(host_mod.os, "replace", flaky)
    h._write_status()

    assert len(calls) == 2, "PermissionError 必须重试"
    assert "status_write_error" not in h.status
    assert json.loads(h.status_path.read_text(encoding="utf-8"))["marker"] == "after-retry"
    assert not list(h.status_path.parent.glob("*.tmp"))


def test_permission_error_exhausts_retries_and_is_recorded(tmp_path, monkeypatch):
    h = _host(tmp_path)
    monkeypatch.setattr(host_mod, "_STATUS_REPLACE_DELAY", 0.0)
    calls: list[int] = []

    def always_busy(src, dst):
        calls.append(1)
        raise PermissionError(13, "拒绝访问")

    monkeypatch.setattr(host_mod.os, "replace", always_busy)
    h._write_status()

    assert len(calls) == host_mod._STATUS_REPLACE_ATTEMPTS
    assert "PermissionError" in h.status["status_write_error"]
    assert not list(h.status_path.parent.glob("*.tmp"))


def test_generic_oserror_is_not_retried(tmp_path, monkeypatch):
    """只有「目标被占用」值得重试；磁盘满/路径非法重试也没用。"""
    h = _host(tmp_path)
    calls: list[int] = []

    def boom(src, dst):
        calls.append(1)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(host_mod.os, "replace", boom)
    h._write_status()
    assert len(calls) == 1


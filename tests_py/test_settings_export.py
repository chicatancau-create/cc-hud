"""Task 12 验收：设置损坏回退、夹取、脱敏。"""
import json

from cchud_next.export import redact, redact_url
from cchud_next.settings import ALPHAS, DEFAULTS, SettingsStore


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not json", encoding="utf-8")
    assert SettingsStore(p).load() == DEFAULTS


def test_non_dict_json_falls_back_to_defaults(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps([1, 2]), encoding="utf-8")
    assert SettingsStore(p).load() == DEFAULTS


def test_clamp_and_unknown_keys_dropped(tmp_path):
    store = SettingsStore(tmp_path / "s.json")
    store.save({"alpha": 0.1, "range": "9d", "layout": "bogus", "bogus": 1})
    got = store.load()
    assert got["alpha"] == min(ALPHAS, key=lambda x: abs(x - 0.1))   # 夹到最近档
    assert got["range"] == DEFAULTS["range"]
    assert got["layout"] == DEFAULTS["layout"]
    assert "bogus" not in got


def test_redact_url_strips_userinfo_and_query():
    out = redact_url("https://user:pass@example.com/x?token=abc&q=1")
    assert out == "https://example.com/x"
    assert "user:pass" not in out and "token" not in out


def test_redact_secret_keys():
    out = redact({"api_key": "sk-live", "token": "t-1",
                  "authorization": "Bearer z", "password": "p",
                  "session": "keep"})
    for k in ("api_key", "token", "authorization", "password"):
        assert out[k] == "<REDACTED>"
    assert out["session"] == "keep"


def test_redact_strings_and_nested_values():
    out = redact({"h": "Authorization: Bearer sk-123",
                  "u": "https://a:b@h/p?api_key=k",
                  "n": [{"token=zzz": 1}]})
    assert "<REDACTED>" in out["h"]
    assert "sk-123" not in json.dumps(out)
    assert out["u"] == "https://h/p"
    assert "token=zzz" in out["n"][0]          # 键名不是 secret 模式，值保留

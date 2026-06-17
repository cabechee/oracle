"""collector_config — 수집기 설정(텀·항목 토글·enabled) 정규화. DB는 페이크."""

import collector_config as cc


class _FakeSettings:
    def __init__(self, docs=None):
        self.docs = {d["_id"]: dict(d) for d in (docs or [])}

    def find_one(self, flt):
        d = self.docs.get(flt.get("_id"))
        return dict(d) if d else None

    def update_one(self, flt, update, upsert=False):
        _id = flt.get("_id")
        doc = self.docs.setdefault(_id, {"_id": _id})
        doc.update(update.get("$set", {}))


def _use(monkeypatch, docs=None):
    fake = _FakeSettings(docs)
    monkeypatch.setattr(cc.db, "settings", lambda: fake)
    return fake


def test_defaults(monkeypatch):
    _use(monkeypatch)
    cfg = cc.get_config()
    assert cfg["sync_interval_min"] == 1       # 기본 1분
    assert cfg["enabled"] is True
    assert cfg["collect_notifications"] is True


def test_set_normalizes_and_clamps(monkeypatch):
    _use(monkeypatch)
    out = cc.set_config({"sync_interval_min": "0", "collect_sms": 0,
                         "enabled": 1, "bogus": 9})
    assert out["sync_interval_min"] == 1        # 하한 1분
    assert out["collect_sms"] is False
    assert out["enabled"] is True
    assert "bogus" not in out
    out = cc.set_config({"sync_interval_min": 99999})
    assert out["sync_interval_min"] == 1440      # 상한 24시간

"""location_config — 위치 센싱 설정(확인 주기·WiFi 스킵) 정규화. DB는 페이크."""

import location_config as lc


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
    monkeypatch.setattr(lc.db, "settings", lambda: fake)
    return fake


def test_defaults(monkeypatch):
    _use(monkeypatch)
    cfg = lc.get_config()
    assert cfg["poll_interval_sec"] == 30
    assert cfg["skip_on_known_wifi"] is True


def test_set_normalizes_and_clamps(monkeypatch):
    _use(monkeypatch)
    out = lc.set_config({"poll_interval_sec": "5", "skip_on_known_wifi": 0,
                         "bogus": 1})
    assert out["poll_interval_sec"] == 15       # 하한 15초로 클램프
    assert out["skip_on_known_wifi"] is False
    assert "bogus" not in out
    out = lc.set_config({"poll_interval_sec": 99999})
    assert out["poll_interval_sec"] == 3600      # 상한 1시간

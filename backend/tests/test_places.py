"""places — 장소 레지스트리 upsert(멱등·필드 보존)·describe·정렬. DB는 페이크."""

import places as places_mod


class _FakeCol:
    def __init__(self):
        self.docs = {}

    def find_one(self, flt):
        for d in self.docs.values():
            if all(d.get(k) == v for k, v in flt.items()):
                return dict(d)
        return None

    def replace_one(self, flt, doc, upsert=False):
        self.docs[flt["_id"]] = dict(doc)

    def find(self):
        return [dict(d) for d in self.docs.values()]

    def delete_one(self, flt):
        existed = flt["_id"] in self.docs
        self.docs.pop(flt["_id"], None)

        class _R:
            deleted_count = 1 if existed else 0
        return _R()


def _use(monkeypatch):
    col = _FakeCol()
    monkeypatch.setattr(places_mod.db, "places", lambda: col)
    return col


def test_home_is_singleton(monkeypatch):
    _use(monkeypatch)
    a = places_mod.upsert("집", kind="home", lat=1.0, lng=2.0, wifi="HomeWifi")
    b = places_mod.upsert("우리집", kind="home", lat=1.1, lng=2.1)  # 재저장 → 같은 문서
    assert a["id"] == b["id"] == "place-home"
    assert b["name"] == "우리집"


def test_description_only_preserves_fields(monkeypatch):
    _use(monkeypatch)
    p = places_mod.upsert("카페", kind="place", lat=3.0, lng=4.0, wifi="CafeWifi")
    # 어드민이 설명만 편집 — 이름·kind·좌표·wifi는 그대로 보존돼야
    p2 = places_mod.upsert(name="카페", description="주말 작업", place_id=p["id"])
    assert p2["description"] == "주말 작업"
    assert p2["wifi"] == "CafeWifi"
    assert p2["lat"] == 3.0
    assert p2["kind"] == "place"


def test_describe(monkeypatch):
    _use(monkeypatch)
    places_mod.upsert("작업실", kind="office", description="조용한 스튜디오")
    assert places_mod.describe("office") == "조용한 스튜디오"   # kind로
    places_mod.upsert("단골카페", kind="place", wifi="X", description="라떼 맛집")
    assert places_mod.describe("단골카페") == "라떼 맛집"        # 이름으로
    assert places_mod.describe("없는곳") == ""
    assert places_mod.describe(None) == ""


def test_list_sorted_home_office_first(monkeypatch):
    _use(monkeypatch)
    places_mod.upsert("Z카페", kind="place", wifi="z")
    places_mod.upsert("작업실", kind="office")
    places_mod.upsert("집", kind="home")
    kinds = [p["kind"] for p in places_mod.list_places()]
    assert kinds == ["home", "office", "place"]


def test_bt_keyed_place(monkeypatch):
    _use(monkeypatch)
    a = places_mod.upsert("차", kind="place", bt="차량오디오")
    b = places_mod.upsert("차", kind="place", bt="차량오디오")   # 멱등(같은 BT)
    assert a["id"] == b["id"]
    assert a["bt"] == "차량오디오"
    # 설명만 편집 — bt 보존
    c = places_mod.upsert(name="차", description="운전 중", place_id=a["id"])
    assert c["bt"] == "차량오디오" and c["description"] == "운전 중"


def test_delete(monkeypatch):
    _use(monkeypatch)
    p = places_mod.upsert("카페", kind="place", wifi="w")
    assert places_mod.delete(p["id"]) is True
    assert places_mod.get(p["id"]) is None
    assert places_mod.delete("nope") is False

"""geocode — Kakao 역지오코딩 파싱·캐시·graceful + visits area 폴백 배선(DB·HTTP는 fake)."""

import geocode
import visits


# ── Kakao 응답 샘플 ───────────────────────────────────────────────
_DOC_BUILDING = {
    "road_address": {"building_name": "성산일출봉", "region_2depth_name": "서귀포시",
                     "region_3depth_name": "성산읍"},
    "address": {"region_2depth_name": "서귀포시", "region_3depth_name": "성산읍 고성리"},
}
_DOC_REGION = {
    "road_address": None,
    "address": {"region_2depth_name": "강남구", "region_3depth_name": "역삼동"},
}


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload

    def json(self):
        return self._p


class _FakeHttp:
    """geocode.httpx 대체 — get 호출 기록 + 정해둔 응답 반환(또는 예외)."""
    def __init__(self, resp=None, raise_exc=None):
        self.resp = resp
        self.raise_exc = raise_exc
        self.calls = 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls += 1
        if self.raise_exc:
            raise self.raise_exc
        return self.resp


class _FakeCache:
    def __init__(self):
        self.docs = {}

    def find_one(self, flt):
        return self.docs.get(flt["_id"])

    def update_one(self, flt, upd, upsert=False):
        self.docs.setdefault(flt["_id"], {"_id": flt["_id"]}).update(upd.get("$set", {}))


# ── _display: 건물명 우선, 없으면 시군구+읍면동 ──────────────────
def test_display_building_pref():
    assert geocode._display(_DOC_BUILDING) == "성산일출봉 (서귀포시)"


def test_display_region_fallback():
    assert geocode._display(_DOC_REGION) == "강남구 역삼동"


def test_display_empty_none():
    assert geocode._display({}) is None
    assert geocode._display({"address": {}, "road_address": {}}) is None


# ── reverse: 캐시/키없음/성공/오류 ───────────────────────────────
def test_reverse_no_key_no_call(monkeypatch):
    cache = _FakeCache()
    http = _FakeHttp(_Resp(200, {"documents": [_DOC_REGION]}))
    monkeypatch.setattr(geocode.db, "geocache", lambda: cache)
    monkeypatch.setattr(geocode, "httpx", http)
    monkeypatch.setattr(geocode, "KAKAO_REST_KEY", "")
    assert geocode.reverse(37.5, 127.0) is None
    assert http.calls == 0                  # 키 없으면 호출 안 함
    assert cache.docs == {}                 # 캐시도 안 남김(키 생기면 재시도 되게)


def test_reverse_success_caches(monkeypatch):
    cache = _FakeCache()
    http = _FakeHttp(_Resp(200, {"documents": [_DOC_REGION]}))
    monkeypatch.setattr(geocode.db, "geocache", lambda: cache)
    monkeypatch.setattr(geocode, "httpx", http)
    monkeypatch.setattr(geocode, "KAKAO_REST_KEY", "KEY")
    assert geocode.reverse(37.5, 127.0) == "강남구 역삼동"
    assert http.calls == 1
    # 같은 좌표 재호출 — 캐시 히트, http 추가 호출 없음
    assert geocode.reverse(37.5, 127.0) == "강남구 역삼동"
    assert http.calls == 1


def test_reverse_cache_hit_skips_http(monkeypatch):
    cache = _FakeCache()
    cache.docs["37.5,127.0"] = {"_id": "37.5,127.0", "name": "집앞"}
    http = _FakeHttp(_Resp(200, {"documents": [_DOC_REGION]}))
    monkeypatch.setattr(geocode.db, "geocache", lambda: cache)
    monkeypatch.setattr(geocode, "httpx", http)
    monkeypatch.setattr(geocode, "KAKAO_REST_KEY", "KEY")
    assert geocode.reverse(37.5, 127.0) == "집앞"
    assert http.calls == 0


def test_reverse_cached_none_not_recalled(monkeypatch):
    cache = _FakeCache()
    cache.docs["37.5,127.0"] = {"_id": "37.5,127.0", "name": None}   # 주소 없음으로 판명된 것
    http = _FakeHttp(_Resp(200, {"documents": [_DOC_REGION]}))
    monkeypatch.setattr(geocode.db, "geocache", lambda: cache)
    monkeypatch.setattr(geocode, "httpx", http)
    monkeypatch.setattr(geocode, "KAKAO_REST_KEY", "KEY")
    assert geocode.reverse(37.5, 127.0) is None
    assert http.calls == 0                  # None도 캐시 히트로 재호출 안 함


def test_reverse_http_error_no_cache(monkeypatch):
    cache = _FakeCache()
    http = _FakeHttp(_Resp(401, {}))
    monkeypatch.setattr(geocode.db, "geocache", lambda: cache)
    monkeypatch.setattr(geocode, "httpx", http)
    monkeypatch.setattr(geocode, "KAKAO_REST_KEY", "KEY")
    assert geocode.reverse(37.5, 127.0) is None
    assert cache.docs == {}                 # 오류는 캐시 안 함(재시도 여지)


def test_reverse_exception_graceful(monkeypatch):
    cache = _FakeCache()
    http = _FakeHttp(raise_exc=RuntimeError("net down"))
    monkeypatch.setattr(geocode.db, "geocache", lambda: cache)
    monkeypatch.setattr(geocode, "httpx", http)
    monkeypatch.setattr(geocode, "KAKAO_REST_KEY", "KEY")
    assert geocode.reverse(37.5, 127.0) is None


def test_reverse_none_coords():
    assert geocode.reverse(None, None) is None


# ── backfill: area 채움 + 카운트 ─────────────────────────────────
class _FakeVisits:
    def __init__(self, docs):
        self.docs = docs

    def find(self, q=None):
        return _Cursor(list(self.docs))

    def update_one(self, flt, upd, upsert=False):
        for d in self.docs:
            if d.get("_id") == flt.get("_id"):
                d.update(upd.get("$set", {}))


class _Cursor(list):
    def limit(self, n):
        return _Cursor(self[:n])


def test_backfill_sets_area_only_when_named(monkeypatch):
    docs = [
        {"_id": "v1", "lat": 33.0, "lng": 126.0, "place": None},
        {"_id": "v2", "lat": 33.1, "lng": 126.1, "place": None},
    ]
    fv = _FakeVisits(docs)
    monkeypatch.setattr(geocode.db, "visits", lambda: fv)
    monkeypatch.setattr(geocode, "KAKAO_REST_KEY", "KEY")
    # v1은 지명, v2는 없음(None) — 이름 얻은 것만 area 저장(v2는 재시도 여지로 안 박음)
    monkeypatch.setattr(geocode, "reverse",
                        lambda lat, lng: "제주시 한림읍" if lat == 33.0 else None)
    res = geocode.backfill_visits()
    assert res == {"processed": 2, "named": 1}
    assert docs[0]["area"] == "제주시 한림읍"
    assert "area" not in docs[1]            # None은 안 박음(키 생겨도 캐시 독 안 되게)


def test_backfill_no_key_skips(monkeypatch):
    docs = [{"_id": "v1", "lat": 33.0, "lng": 126.0, "place": None}]
    fv = _FakeVisits(docs)
    monkeypatch.setattr(geocode.db, "visits", lambda: fv)
    monkeypatch.setattr(geocode, "KAKAO_REST_KEY", "")
    res = geocode.backfill_visits()
    assert res["skipped"] == "no_key"
    assert "area" not in docs[0]            # 키 없으면 손 안 댐


# ── visits 배선: area 폴백 ───────────────────────────────────────
def test_place_name_area_fallback():
    assert visits._place_name({"area": "성산읍"}) == "성산읍"
    assert visits._place_name({"place": "집"}) == "집"            # place가 우선
    assert visits._place_name({"label": "할머니댁", "area": "성산읍"}) == "할머니댁"
    assert visits._place_name({}) == "어떤 곳"


def test_live_name_area_fallback(monkeypatch):
    import sys
    import types
    fake_places = types.ModuleType("places")
    fake_places.nearest = lambda lat, lng, r: None    # 등록 장소 없음
    monkeypatch.setitem(sys.modules, "places", fake_places)
    assert visits._live_name({"lat": 33.0, "lng": 126.0, "area": "성산읍"}) == "성산읍"
    assert visits._live_name({"lat": 33.0, "lng": 126.0}) is None   # area도 없으면 미지정

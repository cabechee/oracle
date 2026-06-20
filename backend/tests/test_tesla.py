"""Tesla Fleet API 클라이언트 — graceful(미인증/실패) + 토큰 갱신·파싱·스펙 준수."""

import time

import tesla


class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeHttpx:
    def __init__(self, post_resp=None, get_resp=None):
        self.posts = []
        self.gets = []
        self.post_resp = post_resp or _Resp()
        self.get_resp = get_resp or _Resp()

    def post(self, url, **kw):
        self.posts.append((url, kw))
        return self.post_resp

    def get(self, url, **kw):
        self.gets.append((url, kw))
        return self.get_resp


# ── graceful: 미인증이면 절대 안 죽고 빈 결과 ──
def test_unauthed_graceful(monkeypatch):
    monkeypatch.setattr(tesla, "_load_token", lambda: None)
    monkeypatch.setattr(tesla.config, "TESLA_CLIENT_ID", "")
    assert tesla.is_authed() is False
    assert tesla.vehicles() == []
    assert tesla.location() is None
    assert tesla.status()["authed"] is False


def test_partner_token_needs_creds(monkeypatch):
    monkeypatch.setattr(tesla.config, "TESLA_CLIENT_ID", "")
    monkeypatch.setattr(tesla.config, "TESLA_CLIENT_SECRET", "")
    tesla._partner.update({"token": None, "exp": 0})
    assert tesla.partner_token() is None


# ── access token: 유효하면 그대로, 만료면 refresh ──
def test_access_token_valid(monkeypatch):
    monkeypatch.setattr(tesla, "_load_token",
                        lambda: {"access_token": "AT", "expires_at": time.time() + 9999})
    assert tesla._access_token() == "AT"


def test_access_token_refresh(monkeypatch):
    monkeypatch.setattr(tesla, "_load_token",
                        lambda: {"access_token": "old", "expires_at": 0,
                                 "refresh_token": "RT"})
    saved = {}
    monkeypatch.setattr(tesla, "_save_token", lambda t: saved.update(t))
    monkeypatch.setattr(tesla.config, "TESLA_CLIENT_ID", "cid")
    fake = _FakeHttpx(post_resp=_Resp(200, {"access_token": "new", "expires_in": 100}))
    monkeypatch.setattr(tesla, "httpx", fake)
    assert tesla._access_token() == "new"
    assert saved["access_token"] == "new"
    assert saved["refresh_token"] == "RT"          # 응답에 없으면 기존 보존
    body = fake.posts[0][1]["data"]
    assert body["grant_type"] == "refresh_token"
    assert "client_secret" not in body             # 테슬라 스펙: refresh엔 secret 없음


# ── partner token: client_credentials 바디 스펙(audience·scope·secret) ──
def test_partner_token_spec(monkeypatch):
    monkeypatch.setattr(tesla.config, "TESLA_CLIENT_ID", "cid")
    monkeypatch.setattr(tesla.config, "TESLA_CLIENT_SECRET", "sec")
    monkeypatch.setattr(tesla.config, "TESLA_API_BASE", "https://base")
    tesla._partner.update({"token": None, "exp": 0})
    fake = _FakeHttpx(post_resp=_Resp(200, {"access_token": "PT", "expires_in": 100}))
    monkeypatch.setattr(tesla, "httpx", fake)
    assert tesla.partner_token() == "PT"
    body = fake.posts[0][1]["data"]
    assert body["grant_type"] == "client_credentials"
    assert body["audience"] == "https://base"
    assert body["client_secret"] == "sec"


# ── location 파싱: 운행/정차 판정 + 목적지 + 자는차 회피 ──
def test_location_driving_with_dest(monkeypatch):
    monkeypatch.setattr(tesla, "vehicles", lambda: [{"vin": "VIN1", "state": "online"}])
    monkeypatch.setattr(tesla, "vehicle_data", lambda vin: {
        "drive_state": {"latitude": 37.5, "longitude": 127.0,
                        "shift_state": "D", "speed": 40, "timestamp": 1,
                        "active_route_destination": "회사",
                        "active_route_latitude": 37.49, "active_route_longitude": 127.03,
                        "active_route_minutes_to_arrival": 12}})
    loc = tesla.location()
    assert loc["lat"] == 37.5 and loc["shift"] == "D" and loc["driving"] is True
    assert loc["dest"] == "회사" and loc["dest_lat"] == 37.49 and loc["eta_min"] == 12


def test_location_parked(monkeypatch):
    monkeypatch.setattr(tesla, "vehicles", lambda: [{"vin": "V", "state": "online"}])
    monkeypatch.setattr(tesla, "vehicle_data", lambda vin: {"drive_state": {"shift_state": "P"}})
    assert tesla.location()["driving"] is False


def test_location_asleep_no_wake(monkeypatch):
    # 자는 차(online 아님)는 vehicle_data를 부르지 않고 None — wake 회피(비용).
    monkeypatch.setattr(tesla, "vehicles", lambda: [{"vin": "V", "state": "asleep"}])
    monkeypatch.setattr(tesla, "vehicle_data",
                        lambda vin: (_ for _ in ()).throw(AssertionError("자는차 깨우면 안 됨")))
    assert tesla.location() is None


def test_location_no_vehicle(monkeypatch):
    monkeypatch.setattr(tesla, "vehicles", lambda: [])
    assert tesla.location() is None

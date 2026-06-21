package studio.camembertcheese.oracle.collector

import android.content.Context
import android.location.Location
import org.json.JSONObject

/// 위치 체류·이동 감지 → **여정 기록**(집→차→사무실→차→집) + 베르·쿠키 수다(banter)
/// + **차량 출차/주차 상태머신**.
///
/// 기록(여정)과 수다를 분리: 떠날 때마다 그 구간을 silent로 /visits에 남기고(데이터),
/// 수다는 이동(나섬)·도착(인사)에 흐름으로 건다. 시간 체크인(정시)과도 완전 별개.
///
/// 차량(좌표 없는 BT 장소=차)은 별도 상태머신:
///   주차중 ──[차 BT 연결 + 세운 데서 50m+ 이동]──▶ 운전중    (목적지 있으면 '회사 가는구나',
///                                                           없으면 3분 뒤 재확인 후 '어디 가?')
///   운전중 ──[차 BT 해제(디바운스)]──▶ 주차중                ('어디?'/'잘 도착했어?')
///   운전중 ──[10분 정지]──▶ 충전 확인(충전이면 '충전 중', 상태 유지)
///   운전중 ──[2시간 정지(안전망)]──▶ 주차중                  (조용히, 질문 X)
/// 비대칭 근거: BT 해제 = 이미 차서 멀어짐(=주차). BT 연결 = 차 근처일 뿐(물건 꺼내기?) →
/// 50m 게이트로 운전 확정. 물건 꺼내기는 BT 연결돼도 50m 안 → 출차 아님.
object LocationCollector {

    private const val ARRIVE_RADIUS = 120.0
    private const val STAY_RADIUS = 150.0
    private const val STAY_MINUTES = 15

    // 재시작 직후 첫 틱은 현재 BT로 상태만 맞추고 이벤트 X(가짜 출차/주차 방지). 프로세스 생존 동안만.
    @Volatile private var carBaselined = false

    fun tick(ctx: Context, skipOnWifi: Boolean, locCfg: JSONObject?) {
        try {
            val now = System.currentTimeMillis()
            Prefs.bumpTick(ctx)
            val places = PlacesCache.get(ctx)

            val btDev = Prefs.btConnected(ctx)
            val btPlace = if (btDev.isNotBlank()) PlacesCache.byBt(places, btDev) else null
            val isFixedBt = btPlace != null && PlacesCache.coordsOf(places, btPlace) != null
            // 좌표 없는 BT 장소 = 차(이동체). 좌표 있으면 고정 장소(스피커 등).
            val carName = if (btPlace != null && !isFixedBt) btPlace else null
            val onCar = carName != null

            // 차량 상태머신 — 처리하면(운전중·전이 발생) true → 체류머신 스킵.
            if (carTick(ctx, now, onCar, carName, locCfg)) return

            // 고정 BT 장소(좌표 있는 스피커 등) — 거기 있는 것, 체류머신 스킵(기존 동작).
            if (isFixedBt) {
                val loc = Geo.currentLocation(ctx)
                if (loc != null) Prefs.setAnchor(ctx, loc.latitude, loc.longitude, now)
                return
            }

            // 평범한 체류/이동(WiFi·GPS) — 도보로 장소 오감, banter arrive/leave, askPlace.
            stayTick(ctx, skipOnWifi, now, places)
        } catch (_: Exception) {
        }
    }

    // ── 차량 상태머신 ────────────────────────────────────────────────
    /// 운전 중엔 Tesla 차 GPS를 메인(폰보다 정확 — 폰은 운전 중 틀리게 찍히기도), 폰은 보조(로그).
    /// 그 외(주차·도보)엔 폰. 둘 다 받아 로그엔 남기고 메인만 상태머신에 쓴다.
    private fun bestLoc(ctx: Context, driving: Boolean): Location? {
        val phone = Geo.currentLocation(ctx)
        if (driving) {
            val t = Backend.carLocation(ctx)
            if (t != null) {
                val p = if (phone != null) " · 폰(%.5f,%.5f)".format(phone.latitude, phone.longitude) else " · 폰없음"
                L.i("운전중 위치 Tesla 메인(%.5f,%.5f)".format(t.first, t.second) + p)
                return Location("tesla").apply {
                    latitude = t.first; longitude = t.second; accuracy = 5f
                    time = System.currentTimeMillis()
                    elapsedRealtimeNanos = android.os.SystemClock.elapsedRealtimeNanos()
                }
            }
            L.i("운전중 위치 Tesla 없음 → 폰 폴백")
        }
        return phone
    }

    /// 차 상태를 한 틱 진행. 처리했으면(운전중이거나 전이 발생) true — 호출부가 체류머신 스킵.
    private fun carTick(ctx: Context, now: Long, onCar: Boolean,
                        carName: String?, locCfg: JSONObject?): Boolean {
        val departR = (locCfg?.optInt("car_depart_radius_m", 50) ?: 50).toDouble()
        val statR = (locCfg?.optInt("car_stationary_radius_m", 75) ?: 75).toDouble()
        val resetMs = (locCfg?.optInt("car_stationary_reset_min", 120) ?: 120) * 60_000L
        val debounce = (locCfg?.optInt("car_park_debounce_ticks", 2) ?: 2).coerceAtLeast(1)
        val chargeMs = (locCfg?.optInt("car_charge_check_min", 10) ?: 10) * 60_000L
        val recheckMs = (locCfg?.optInt("car_dest_recheck_min", 3) ?: 3) * 60_000L

        // 0) 재시작 직후 — 현재 BT(+지속 상태)로만 맞추고 이벤트 X.
        if (!carBaselined) {
            carBaselined = true
            Prefs.setParkPendingTicks(ctx, 0)
            if (onCar && Prefs.carState(ctx) == "driving") {
                val loc = bestLoc(ctx, driving = true)   // 운전중 — Tesla GPS 메인
                if (loc != null) Prefs.setDriveAnchor(ctx, loc.latitude, loc.longitude, now)
                L.i("차 상태 기준선: 운전중 유지(재시작)")
                return true
            }
            Prefs.setCarState(ctx, "parked")
            val loc = Geo.currentLocation(ctx)
            if (loc != null) Prefs.setDepartAnchor(ctx, loc.latitude, loc.longitude)
            L.i("차 상태 기준선: 주차중")
            return false
        }

        if (Prefs.carState(ctx) == "driving") {
            val loc = bestLoc(ctx, driving = true)   // 운전중 — Tesla GPS 메인(폰보다 정확), 폰 보조
            // 1) 주차 — 차 BT 해제(연속 debounce 틱). 시동 잠깐 껐다 켜기는 흡수.
            if (!onCar) {
                val pend = Prefs.parkPendingTicks(ctx) + 1
                Prefs.setParkPendingTicks(ctx, pend)
                if (pend >= debounce) {
                    L.i("주차(BT 해제 ${pend}틱 확정) — 운전중→주차중")
                    doPark(ctx, loc, now, silent = false)
                } else {
                    L.i("BT 해제 후보 ${pend}/${debounce}틱(시동 깜빡임?) — 대기")
                }
                return true
            }
            Prefs.setParkPendingTicks(ctx, 0)   // BT 유지/도로 잡힘 — 디바운스 리셋

            // 2) 목적지 재확인 — 출차 때 목적지 없었으면 recheck분 뒤 1회 더(운전 시작 후 내비 찍기).
            val recheckAt = Prefs.destRecheckAt(ctx)
            if (recheckAt > 0L && now >= recheckAt) {
                Prefs.setDestRecheckAt(ctx, 0L)   // 1회만
                val rlat = loc?.latitude ?: Prefs.driveAnchor(ctx)?.first ?: 0.0
                val rlng = loc?.longitude ?: Prefs.driveAnchor(ctx)?.second ?: 0.0
                L.i("출차 목적지 재확인(${recheckMs / 60000}분 경과) — 재조회")
                val r = Backend.carDeparture(ctx, rlat, rlng, recheck = true)
                val text = r?.optString("text")?.trim() ?: ""
                if (text.isNotEmpty()) {
                    Notify.companion(ctx, r!!.optString("speaker"), text)
                    L.i("목적지 재확인 멘트: $text")
                } else L.i("목적지 재확인 — 여전히 목적지 없음/멘트 게이팅")
            }

            // 3) 안전망 — 운전중 정지: chargeMs 정지면 충전확인(1회), resetMs 정지면 조용히 주차중.
            if (loc != null) {
                val da = Prefs.driveAnchor(ctx)
                if (da == null) {
                    Prefs.setDriveAnchor(ctx, loc.latitude, loc.longitude, now)
                } else {
                    val moved = Geo.distance(loc.latitude, loc.longitude, da.first, da.second)
                        .toDouble()
                    if (moved > statR) {
                        Prefs.setDriveAnchor(ctx, loc.latitude, loc.longitude, now) // 움직임 — 타이머 리셋
                    } else {
                        val still = now - Prefs.driveLastMove(ctx)
                        // 10분+ 한자리 정지 & 이번 정지 아직 확인 안 함 → 충전중인지(자는차면 무응답).
                        if (still >= chargeMs && Prefs.chargeCheckedAt(ctx) < Prefs.driveLastMove(ctx)) {
                            Prefs.setChargeCheckedAt(ctx, now)
                            L.i("운전중 ${still / 60000}분 정지 — 충전 확인 호출")
                            val r = Backend.carCharging(ctx, loc.latitude, loc.longitude)
                            val text = r?.optString("text")?.trim() ?: ""
                            if (text.isNotEmpty()) {
                                Notify.companion(ctx, r!!.optString("speaker"), text)
                                L.i("충전 중 확인 — $text")
                            } else L.i("충전 확인 — 충전 아님/무응답(운전중 유지)")
                        }
                        // 안전망 리셋(2시간) — 충전이든 멈춤이든 너무 오래면 조용히 주차중.
                        if (still >= resetMs) {
                            L.i("안전망: 정지 ${resetMs / 60000}분 지속 — 조용히 주차중 리셋")
                            doPark(ctx, loc, now, silent = true)
                        }
                    }
                }
            }
            return true   // 운전중 — 체류머신 스킵
        }

        // 주차중
        if (onCar) {
            // 3) 출차 — 차 BT 연결 채로 세운 데서 departR 이상 벗어남.
            val loc = Geo.currentLocation(ctx)
            val da = Prefs.departAnchor(ctx)
            if (da == null) {
                if (loc != null) Prefs.setDepartAnchor(ctx, loc.latitude, loc.longitude) // 연결 순간 신선한 기준
            } else if (loc != null) {
                val moved = Geo.distance(loc.latitude, loc.longitude, da.first, da.second)
                    .toDouble()
                if (moved >= departR) {
                    L.i("출차(BT 연결 + ${moved.toInt()}m ≥ ${departR.toInt()}m) — 주차중→운전중: '$carName'")
                    doDepart(ctx, loc.latitude, loc.longitude, now, carName, recheckMs)
                }
            }
            return true   // BT 연결 채 주차중 — 출차 감시 중, 체류머신 스킵(조기 leave 방지)
        }
        // 차 BT 없는 주차중 — departAnchor가 없으면(첫 실행) 채워둠. 도보론 안 흔듦(차 위치 고정).
        if (Prefs.departAnchor(ctx) == null) {
            val loc = Geo.currentLocation(ctx)
            if (loc != null) Prefs.setDepartAnchor(ctx, loc.latitude, loc.longitude)
        }
        return false   // 주차중 — 체류머신 돌게
    }

    /// 출차 — 머물던 곳(여정 silent) 마무리 + 운전중 진입 + 목적지 멘트(없으면 재확인 예약).
    private fun doDepart(ctx: Context, lat: Double, lng: Double, now: Long,
                         carName: String?, recheckMs: Long) {
        if (Prefs.visitOn(ctx)) {           // 머물던 곳(집 등)을 먼저 여정에 기록
            endStay(ctx, now)
            Prefs.setVisitOn(ctx, false)
        }
        Prefs.setCarState(ctx, "driving")
        Prefs.setBtBoardTime(ctx, now)      // 드라이브 구간 시작(주차 때 구간 길이)
        Prefs.setCarName(ctx, carName ?: "차")
        Prefs.setDriveAnchor(ctx, lat, lng, now)
        Prefs.setParkPendingTicks(ctx, 0)
        Prefs.setChargeCheckedAt(ctx, 0L)   // 새 운행 — 충전확인 리셋
        Prefs.setDestRecheckAt(ctx, 0L)
        val r = Backend.carDeparture(ctx, lat, lng)
        val text = r?.optString("text")?.trim() ?: ""
        if (text.isNotEmpty()) {
            Notify.companion(ctx, r!!.optString("speaker"), text)
            L.i("출차 멘트(즉답): $text")
        } else if (r?.optBoolean("recheck") == true) {
            Prefs.setDestRecheckAt(ctx, now + recheckMs)   // 목적지 없음 → recheck분 뒤 1회 재확인
            L.i("출차 — 목적지 미설정, ${recheckMs / 60000}분 뒤 재확인 예약")
        } else {
            L.i("출차 — 멘트 없음(게이팅/미연결)")
        }
    }

    /// 주차 — 드라이브 구간(여정 silent) + 주차 위치 기록 + 질문(silent면 위치만). 주차중 진입.
    private fun doPark(ctx: Context, loc: android.location.Location?, now: Long, silent: Boolean) {
        val board = Prefs.btBoardTime(ctx)
        recordSegment(ctx, Prefs.carName(ctx).ifBlank { "차" }, 0.0, 0.0,
            if (board > 0L) board else now, now)
        Prefs.setCarState(ctx, "parked")
        Prefs.setBtBoardTime(ctx, 0L)
        Prefs.setCarName(ctx, "")
        Prefs.setParkPendingTicks(ctx, 0)
        Prefs.clearDriveAnchor(ctx)
        Prefs.setDestRecheckAt(ctx, 0L)     // 주차 — 남은 목적지 재확인 취소
        // 새 주차 위치를 다음 출차의 거리 기준점으로.
        if (loc != null) Prefs.setDepartAnchor(ctx, loc.latitude, loc.longitude)
        val anchor = Prefs.departAnchor(ctx)
        val plat = loc?.latitude ?: anchor?.first ?: 0.0
        val plng = loc?.longitude ?: anchor?.second ?: 0.0
        val r = Backend.carParking(ctx, plat, plng, silent)
        if (!silent) {
            val text = r?.optString("text")?.trim() ?: ""
            if (text.isNotEmpty()) Notify.companion(ctx, r!!.optString("speaker"), text)
        }
    }

    // ── 평범한 체류/이동(WiFi·GPS) 머신 ───────────────────────────────
    private fun stayTick(ctx: Context, skipOnWifi: Boolean, now: Long, places: org.json.JSONArray) {
        // 1) WiFi — 등록 장소 WiFi면 GPS 없이 즉시 그 장소.
        if (skipOnWifi) {
            val ssid = Geo.wifiSsid(ctx)
            val wifiPlace = if (ssid != null) PlacesCache.byWifi(places, ssid) else null
            if (wifiPlace != null) {
                onPlaceImmediate(ctx, wifiPlace, now)
                return
            }
        }

        // 2) GPS — WiFi·BT로 확정 안 된 경우 **1분마다 항상** 확인(배터리는 WiFi/BT 매칭이 절약).
        val visitOn = Prefs.visitOn(ctx)
        val loc = Geo.currentLocation(ctx) ?: return
        val lat = loc.latitude
        val lng = loc.longitude
        val gpsPlace = PlacesCache.byGps(places, lat, lng, ARRIVE_RADIUS)

        val aLat = Prefs.anchorLat(ctx)
        val aLng = Prefs.anchorLng(ctx)
        if (aLat == null || aLng == null) {
            setAnchor(ctx, lat, lng, now); return
        }
        val fromAnchor = Geo.distance(lat, lng, aLat, aLng).toDouble()

        if (fromAnchor <= STAY_RADIUS) {
            if (visitOn) return
            val start = Prefs.anchorStart(ctx).let { if (it == 0L) now else it }
            val stayedMin = ((now - start) / 60000).toInt()
            if (gpsPlace != null || stayedMin >= STAY_MINUTES) {
                Prefs.setVisitOn(ctx, true)
                Prefs.setVisitPlace(ctx, gpsPlace ?: "")
                if (gpsPlace != null) {
                    L.i("GPS 도착(등록): '$gpsPlace' — banter arrive")
                    banterFlow(ctx, "arrive", gpsPlace)   // 저장된 곳 — 거주자 인사
                } else {
                    // 저장 안 된 새 곳 15분+ — '아빠 왔다 반겨야지'(엉뚱) 대신 어딘지 물어봄.
                    L.i("GPS 체류 ${stayedMin}분(미등록) — 여기 어디? 물어봄")
                    askPlace(ctx, lat, lng)
                }
            }
        } else {
            if (visitOn) {                    // 떠남 — 머물던 곳을 여정에 기록(silent) + 수다(궁금)
                val left = Prefs.visitPlace(ctx)
                endStay(ctx, now)
                L.i("GPS 나섬: '$left' — banter leave")
                banterFlow(ctx, "leave", left.ifBlank { null })
            }
            setAnchor(ctx, lat, lng, now)
        }
    }

    /// WiFi로 확정된 장소 — 다른 곳서 왔으면 이전 체류를 여정에 기록 후 도착 말 걸기.
    private fun onPlaceImmediate(ctx: Context, place: String, now: Long) {
        val visitOn = Prefs.visitOn(ctx)
        val lastPlace = Prefs.visitPlace(ctx)
        if (visitOn && lastPlace == place) return
        if (visitOn) endStay(ctx, now)
        Prefs.setAnchor(ctx, 0.0, 0.0, now)
        Prefs.setVisitOn(ctx, true)
        Prefs.setVisitPlace(ctx, place)
        L.i("WiFi 도착: '$place' — banter arrive")
        banterFlow(ctx, "arrive", place)
    }

    /// 머물던 곳(현재 anchor/visitPlace)을 이동 직전에 여정으로 기록(silent).
    private fun endStay(ctx: Context, now: Long) {
        val start = Prefs.anchorStart(ctx).let { if (it == 0L) now else it }
        recordSegment(ctx, Prefs.visitPlace(ctx),
            Prefs.anchorLat(ctx) ?: 0.0, Prefs.anchorLng(ctx) ?: 0.0, start, now)
    }

    private fun setAnchor(ctx: Context, lat: Double, lng: Double, now: Long) {
        Prefs.setAnchor(ctx, lat, lng, now)
        Prefs.setVisitOn(ctx, false)
        Prefs.setVisitPlace(ctx, "")
    }

    /// 베르·쿠키 수다 — 서버가 흐름에 각 턴 기록. notify(도착 인사)가 있으면 알림 표시.
    /// 이동·추측(leave)은 notify 비어 흐름에만 조용히(자기들끼리). 게이팅·실패면 조용.
    private fun banterFlow(ctx: Context, event: String, place: String?) {
        val r = Backend.banter(ctx, event, place) ?: return
        val notify = r.optJSONObject("notify")
        val text = notify?.optString("text")?.trim() ?: ""
        if (text.isNotEmpty()) Notify.companion(ctx, notify!!.optString("speaker"), text)
    }

    /// 저장 안 된 새 곳 15분+ 체류 — '여기 어디예요?' 물어봄(좌표 동봉 → 답하면 임시 장소 저장).
    private fun askPlace(ctx: Context, lat: Double, lng: Double) {
        val r = Backend.askPlace(ctx, lat, lng) ?: return
        val text = r.optString("text").trim()
        if (text.isNotEmpty()) Notify.companion(ctx, r.optString("speaker"), text)
    }

    /// 여정 한 구간(체류 또는 이동)을 /visits에 silent 기록.
    private fun recordSegment(ctx: Context, place: String, lat: Double, lng: Double,
                              start: Long, end: Long) {
        val minutes = ((end - start) / 60000).toInt()
        Backend.recordVisit(ctx, place.ifBlank { null }, lat, lng, start, end,
            minutes, silent = true)
    }
}

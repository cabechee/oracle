package studio.camembertcheese.oracle.collector

import android.content.Context
import org.json.JSONArray

/// 위치 체류·이동 감지 → **여정 기록**(집→차→사무실→차→집) + 도착 시 말 걸기.
///
/// 기록(여정)과 말 걸기를 분리: 떠날 때마다 그 구간을 silent로 /visits에 남기고(데이터),
/// 말 걸기는 '도착'에만 한다(차 탑승 포함). 시간 체크인(정시)과도 완전 별개.
/// BT(차)→WiFi→GPS 순. Flutter location_task_handler 이식 + /places 일반화.
object LocationCollector {

    private const val ARRIVE_RADIUS = 120.0
    private const val STAY_RADIUS = 150.0
    private const val STAY_MINUTES = 15

    fun tick(ctx: Context, skipOnWifi: Boolean) {
        try {
            val now = System.currentTimeMillis()
            val tickN = Prefs.bumpTick(ctx)
            val places = PlacesCache.get(ctx)

            // 0) BT — 연결된 기기가 등록 장소(bt)면 그 장소(차 등). 이동 구간 = 여정 기록.
            val btDev = Prefs.btConnected(ctx)
            val btPlace = if (btDev.isNotBlank()) PlacesCache.byBt(places, btDev) else null
            val lastBt = Prefs.btPlace(ctx)
            if ((btPlace ?: "") != lastBt) {
                if (lastBt.isNotBlank()) {
                    // 하차 — 탑승~하차를 이동 구간으로 기록(예: "차" 25분). 말 걸기는 도착 때.
                    val board = Prefs.btBoardTime(ctx)
                    recordSegment(ctx, lastBt, 0.0, 0.0,
                        if (board > 0L) board else now, now)
                    Prefs.setBtBoardTime(ctx, 0L)
                }
                if (btPlace != null) {
                    // 탑승 — 머물던 곳(집 등)을 먼저 기록(여정), 그다음 '차 탔어요?' 말 걸기.
                    if (Prefs.visitOn(ctx)) {
                        endStay(ctx, now)
                        Prefs.setVisitOn(ctx, false)
                    }
                    Prefs.setBtBoardTime(ctx, now)
                    say(ctx, btPlace)
                }
                Prefs.setBtPlace(ctx, btPlace ?: "")
            }
            if (btPlace != null) return   // 차 등에 있으면 GPS 스킵(이동 중)

            // 1) WiFi — 등록 장소 WiFi면 GPS 없이 즉시 그 장소.
            if (skipOnWifi) {
                val ssid = Geo.wifiSsid(ctx)
                val wifiPlace = if (ssid != null) PlacesCache.byWifi(places, ssid) else null
                if (wifiPlace != null) {
                    onPlaceImmediate(ctx, wifiPlace, now)
                    return
                }
            }

            // 2) GPS — 체류 확정 중엔 2틱마다만(배터리)
            val visitOn = Prefs.visitOn(ctx)
            if (visitOn && tickN % 2 != 0) return
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
                    say(ctx, gpsPlace)            // 도착 말 걸기 (이름 있으면 그곳, 없으면 새 곳)
                }
            } else {
                if (visitOn) {                    // 떠남 — 머물던 곳을 여정에 기록(silent)
                    endStay(ctx, now)
                }
                setAnchor(ctx, lat, lng, now)
            }
        } catch (_: Exception) {
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
        say(ctx, place)
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

    /// 도착 말 걸기 — 서버 게이팅 후 비어있지 않으면 알림. (떠남/이동엔 말 안 검 — 기록만)
    private fun say(ctx: Context, place: String?) {
        val r = Backend.companionSay(ctx, "arrive_place", place) ?: return
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

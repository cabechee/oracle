package studio.camembertcheese.oracle.collector

import android.content.Context
import org.json.JSONArray

/// 위치 체류(stay) 감지 — BT → WiFi → GPS 순으로 현재 '저장된 장소'를 판정하고,
/// 도착(arrive_place)·이탈(leave_place) 시 동반자 말 걸기 + 방문 기록.
/// Flutter location_task_handler를 네이티브로 이식 + /places 기반으로 일반화.
object LocationCollector {

    private const val ARRIVE_RADIUS = 120.0   // 장소 도착 반경(m)
    private const val STAY_RADIUS = 150.0     // 같은 곳 '머무름' 판정 반경(m)
    private const val STAY_MINUTES = 15       // 미등록 새 장소 체류 확정(분)

    fun tick(ctx: Context, skipOnWifi: Boolean) {
        try {
            val now = System.currentTimeMillis()
            val tickN = Prefs.bumpTick(ctx)
            val places = PlacesCache.get(ctx)

            // 0) BT — 연결된 기기가 등록 장소(bt)면 그 장소(차 등). 변화 시 도착/이탈.
            val btDev = Prefs.btConnected(ctx)
            val btPlace = if (btDev.isNotBlank()) PlacesCache.byBt(places, btDev) else null
            val lastBt = Prefs.btPlace(ctx)
            if ((btPlace ?: "") != lastBt) {
                if (lastBt.isNotBlank()) say(ctx, "leave_place", lastBt)
                if (btPlace != null) say(ctx, "arrive_place", btPlace)
                Prefs.setBtPlace(ctx, btPlace ?: "")
            }
            if (btPlace != null) return   // BT 장소(차)면 GPS 스킵(이동 중)

            // 1) WiFi — 등록 장소 WiFi면 GPS 없이 즉시 그 장소.
            if (skipOnWifi) {
                val ssid = Geo.wifiSsid(ctx)
                val wifiPlace = if (ssid != null) PlacesCache.byWifi(places, ssid) else null
                if (wifiPlace != null) {
                    onPlaceImmediate(ctx, places, wifiPlace, now)
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
                setAnchor(ctx, lat, lng, now); return     // 첫 위치
            }
            val fromAnchor = Geo.distance(lat, lng, aLat, aLng).toDouble()

            if (fromAnchor <= STAY_RADIUS) {
                if (visitOn) return                       // 이미 체류 확정 — 조용
                val start = Prefs.anchorStart(ctx).let { if (it == 0L) now else it }
                val stayedMin = ((now - start) / 60000).toInt()
                if (gpsPlace != null || stayedMin >= STAY_MINUTES) {
                    Prefs.setVisitOn(ctx, true)
                    Prefs.setVisitPlace(ctx, gpsPlace ?: "")
                    say(ctx, "arrive_place", gpsPlace)    // 이름 있으면 그 장소, 없으면 새 곳(null)
                }
            } else {
                if (visitOn) {
                    val start = Prefs.anchorStart(ctx).let { if (it == 0L) now else it }
                    val minutes = ((now - start) / 60000).toInt()
                    val vplace = Prefs.visitPlace(ctx).ifBlank { null }
                    endVisit(ctx, aLat, aLng, vplace, start, now, minutes)
                }
                setAnchor(ctx, lat, lng, now)             // 새 anchor에서 다시
            }
        } catch (_: Exception) {
        }
    }

    /// WiFi/BT로 확정된 장소 — GPS·anchor 무관 즉시 도착/유지. 다른 곳서 왔으면 이전 방문 종료.
    private fun onPlaceImmediate(ctx: Context, places: JSONArray, place: String, now: Long) {
        val visitOn = Prefs.visitOn(ctx)
        val lastPlace = Prefs.visitPlace(ctx)
        if (visitOn && lastPlace == place) return         // 이미 그곳 체류 중
        if (visitOn) {
            val start = Prefs.anchorStart(ctx).let { if (it == 0L) now else it }
            val minutes = ((now - start) / 60000).toInt()
            val aLat = Prefs.anchorLat(ctx) ?: 0.0
            val aLng = Prefs.anchorLng(ctx) ?: 0.0
            endVisit(ctx, aLat, aLng, lastPlace.ifBlank { null }, start, now, minutes)
        }
        val coords = PlacesCache.coordsOf(places, place)
        Prefs.setAnchor(ctx, coords?.first ?: 0.0, coords?.second ?: 0.0, now)
        Prefs.setVisitOn(ctx, true)
        Prefs.setVisitPlace(ctx, place)
        say(ctx, "arrive_place", place)
    }

    private fun setAnchor(ctx: Context, lat: Double, lng: Double, now: Long) {
        Prefs.setAnchor(ctx, lat, lng, now)
        Prefs.setVisitOn(ctx, false)
        Prefs.setVisitPlace(ctx, "")
    }

    private fun say(ctx: Context, event: String, place: String?) {
        val r = Backend.companionSay(ctx, event, place) ?: return
        val text = r.optString("text").trim()
        if (text.isNotEmpty()) Notify.companion(ctx, r.optString("speaker"), text)
    }

    private fun endVisit(ctx: Context, lat: Double, lng: Double, place: String?,
                         start: Long, end: Long, minutes: Int) {
        val r = Backend.recordVisit(ctx, place, lat, lng, start, end, minutes) ?: return
        val text = r.optString("text").trim()
        if (text.isNotEmpty()) Notify.companion(ctx, r.optString("speaker"), text)
    }
}

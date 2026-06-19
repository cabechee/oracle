package studio.camembertcheese.oracle.collector

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/// 장소 레지스트리 캐시 + 매칭(BT/WiFi/GPS → 장소 이름). 30분마다 백엔드서 갱신.
object PlacesCache {

    private const val REFRESH_MS = 30 * 60_000L

    /// 캐시된 장소들. 오래됐으면(또는 비었으면) 백엔드서 갱신. 실패해도 캐시 반환(graceful).
    fun get(ctx: Context): JSONArray {
        val now = System.currentTimeMillis()
        if (now - Prefs.placesFetchedAt(ctx) > REFRESH_MS || Prefs.places(ctx) == "[]") {
            val items = Backend.listPlaces(ctx)
            if (items != null) Prefs.setPlaces(ctx, items.toString(), now)
        }
        return try { JSONArray(Prefs.places(ctx)) } catch (e: Exception) { JSONArray() }
    }

    /// 한 장소의 다중 필드(bts/wifis) 또는 구 단일(bt/wifi) 중 target과 일치하는 게 있나(OR).
    private fun matchesAny(p: JSONObject, plural: String, single: String, target: String): Boolean {
        val arr = p.optJSONArray(plural)
        if (arr != null) {
            for (i in 0 until arr.length()) {
                if (arr.optString(i).trim() == target) return true
            }
            return false
        }
        return p.optString(single).trim() == target   // 구 단일 필드 폴백
    }

    /// 연결된 BT 기기명이 어떤 장소의 bts(여러 개) 중 하나라도 같으면 그 장소 이름.
    fun byBt(places: JSONArray, btDevice: String): String? {
        if (btDevice.isBlank()) return null
        val t = btDevice.trim()
        for (i in 0 until places.length()) {
            val p = places.optJSONObject(i) ?: continue
            if (p.optString("name").isNotBlank() && matchesAny(p, "bts", "bt", t))
                return p.optString("name")
        }
        return null
    }

    /// 현재 SSID가 어떤 장소의 wifis(여러 개) 중 하나라도 같으면 그 장소 이름.
    fun byWifi(places: JSONArray, ssid: String): String? {
        if (ssid.isBlank()) return null
        val t = ssid.trim()
        for (i in 0 until places.length()) {
            val p = places.optJSONObject(i) ?: continue
            if (p.optString("name").isNotBlank() && matchesAny(p, "wifis", "wifi", t))
                return p.optString("name")
        }
        return null
    }

    /// 좌표가 어떤 장소 반경 안이면 그 장소 이름(가장 가까운). 좌표 없는 장소는 무시.
    fun byGps(places: JSONArray, lat: Double, lng: Double, radiusM: Double): String? {
        var best: String? = null
        var bestDist = radiusM
        for (i in 0 until places.length()) {
            val p = places.optJSONObject(i) ?: continue
            if (p.isNull("lat") || p.isNull("lng")) continue
            val d = Geo.distance(lat, lng, p.optDouble("lat"), p.optDouble("lng")).toDouble()
            if (d <= bestDist && p.optString("name").isNotBlank()) {
                best = p.optString("name"); bestDist = d
            }
        }
        return best
    }

    /// 장소 이름 → 좌표(있으면). 방문 기록·anchor용.
    fun coordsOf(places: JSONArray, name: String): Pair<Double, Double>? {
        for (i in 0 until places.length()) {
            val p = places.optJSONObject(i) ?: continue
            if (p.optString("name") == name && !p.isNull("lat") && !p.isNull("lng"))
                return Pair(p.optDouble("lat"), p.optDouble("lng"))
        }
        return null
    }
}

package studio.camembertcheese.oracle.collector

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/// 백엔드 push — 기존 /signals/sync 재사용(폰 Flutter와 같은 페이로드 + source 태깅).
/// 외부 의존성 없이 HttpURLConnection + org.json.
object Backend {

    fun syncSignals(ctx: Context, sms: JSONArray, calls: JSONArray,
                    notifications: JSONArray): JSONObject? {
        val body = JSONObject()
            .put("sms", sms)
            .put("calls", calls)
            .put("notifications", notifications)
            .put("source", Prefs.deviceId(ctx))   // 어느 기기/클라이언트가 보냈는지 (provenance)
        return post(Prefs.baseUrl(ctx) + "/signals/sync", body)
    }

    /// 어드민에서 조정한 수집기 설정 — 매 사이클 받아 적용(텀·수집 항목·enabled). 실패면 null.
    fun fetchConfig(ctx: Context): JSONObject? =
        get(Prefs.baseUrl(ctx) + "/collector-config")?.optJSONObject("config")

    /// 위치 센싱 설정(주기·WiFi 스킵) — 어드민 📍 장소. 실패면 null.
    fun fetchLocationConfig(ctx: Context): JSONObject? =
        get(Prefs.baseUrl(ctx) + "/location-config")?.optJSONObject("config")

    /// 장소 레지스트리(집·작업실·자주 가는 곳, WiFi/BT/좌표/설명). 실패면 null.
    fun listPlaces(ctx: Context): JSONArray? =
        get(Prefs.baseUrl(ctx) + "/places")?.optJSONArray("items")

    /// 도착/이탈 말 걸기 — 서버가 게이팅 후 {speaker,text} 반환(억제면 text=""). 실패면 null.
    fun companionSay(ctx: Context, event: String, place: String?): JSONObject? {
        val body = JSONObject().put("event", event)
        if (place != null) body.put("place", place)
        return post(Prefs.baseUrl(ctx) + "/companion/say", body)
    }

    /// 방문 기록(체류 종료) — + '떠남' 멘트 반환.
    fun recordVisit(ctx: Context, place: String?, lat: Double, lng: Double,
                    startMs: Long, endMs: Long, minutes: Int): JSONObject? {
        val body = JSONObject()
            .put("place", place ?: JSONObject.NULL)
            .put("lat", lat).put("lng", lng)
            .put("start_ts", startMs).put("end_ts", endMs).put("minutes", minutes)
        return post(Prefs.baseUrl(ctx) + "/visits", body)
    }

    private fun get(urlStr: String): JSONObject? {
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(urlStr).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 15000
                readTimeout = 30000
            }
            if (conn.responseCode in 200..299) {
                val txt = conn.inputStream.bufferedReader().use { it.readText() }
                if (txt.isNotBlank()) JSONObject(txt) else null
            } else {
                null
            }
        } catch (e: Exception) {
            null
        } finally {
            conn?.disconnect()
        }
    }

    private fun post(urlStr: String, body: JSONObject): JSONObject? {
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(urlStr).openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 15000
                readTimeout = 60000
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
            }
            conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            val code = conn.responseCode
            if (code in 200..299) {
                val txt = conn.inputStream.bufferedReader().use { it.readText() }
                if (txt.isNotBlank()) JSONObject(txt) else JSONObject()
            } else {
                null
            }
        } catch (e: Exception) {
            null
        } finally {
            conn?.disconnect()
        }
    }
}

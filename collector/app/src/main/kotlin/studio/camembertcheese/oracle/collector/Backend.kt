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

    /// 차 현재 GPS(Tesla) + 네비 목적지 변경 알림 — 운전 중 메인 위치용. 자는 차/미연동이면 null.
    /// 반환 JSON: {lat,lng,driving,dest, notify?:{speaker,text}}. 목적지 바뀌면 notify(쿠키 멘트).
    fun carLocation(ctx: Context): JSONObject? =
        get(Prefs.baseUrl(ctx) + "/car/location")

    /// 장소 레지스트리(집·작업실·자주 가는 곳, WiFi/BT/좌표/설명). 실패면 null.
    fun listPlaces(ctx: Context): JSONArray? =
        get(Prefs.baseUrl(ctx) + "/places")?.optJSONArray("items")

    /// 도착/이탈 말 걸기 — 서버가 게이팅 후 {speaker,text} 반환(억제면 text=""). 실패면 null.
    fun companionSay(ctx: Context, event: String, place: String?): JSONObject? {
        val body = JSONObject().put("event", event)
        if (place != null) body.put("place", place)
        return post(Prefs.baseUrl(ctx) + "/companion/say", body)
    }

    /// 주차 위치 지정(차에서 내림) — GPS 기록 + '어디 세웠는지 기록할까요?' 말 걸기 반환.
    fun recordParking(ctx: Context, lat: Double, lng: Double): JSONObject? {
        val body = JSONObject()
            .put("lat", lat).put("lng", lng)
            .put("ts", System.currentTimeMillis())
        return post(Prefs.baseUrl(ctx) + "/parking", body)
    }

    /// 출차(주차중→운전중) — '어디 가?' 한마디 + 운행 스레드 시작. {speaker,text} 반환(억제면 빈 text).
    fun carDeparture(ctx: Context, lat: Double, lng: Double,
                     recheck: Boolean = false): JSONObject? {
        val body = JSONObject()
            .put("lat", lat).put("lng", lng)
            .put("ts", System.currentTimeMillis())
            .put("recheck", recheck)
        return post(Prefs.baseUrl(ctx) + "/car/departure", body)
    }

    /// 운전중 오래 정지 — 테슬라로 충전중인지 확인. 충전이면 멘트(text) 채워짐, 아니면 빈 text.
    fun carCharging(ctx: Context, lat: Double, lng: Double): JSONObject? {
        val body = JSONObject().put("lat", lat).put("lng", lng)
        return post(Prefs.baseUrl(ctx) + "/car/charging", body)
    }

    /// 주차(운전중→주차중) — 주차 위치 기록 + 질문('어디?'/답했으면 '잘 도착했어?').
    /// silent=true(안전망: 오래 정지 조용히 리셋)면 위치만 남기고 질문 안 함.
    fun carParking(ctx: Context, lat: Double, lng: Double, silent: Boolean): JSONObject? {
        val body = JSONObject()
            .put("lat", lat).put("lng", lng)
            .put("ts", System.currentTimeMillis())
            .put("silent", silent)
        return post(Prefs.baseUrl(ctx) + "/car/parking", body)
    }

    /// 동반자끼리 수다 — 아빠 이동/도착에 베르·쿠키가 흐름에 주고받음(서버가 흐름에 기록).
    /// event: arrive | leave | board. 반환 notify={speaker,text}는 도착(인사) 때만 채워짐.
    fun banter(ctx: Context, event: String, place: String?): JSONObject? {
        val body = JSONObject().put("event", event)
        if (place != null) body.put("place", place)
        return post(Prefs.baseUrl(ctx) + "/companion/banter", body)
    }

    /// 라이브 상태 보고 — 현재 WiFi·위치·BT·최근 로그(어드민 표시·adb 대체).
    fun reportStatus(ctx: Context, status: JSONObject): JSONObject? =
        post(Prefs.baseUrl(ctx) + "/collector-status", status)

    /// 저장 안 된 새 곳 15분+ 체류 — '여기 어디예요?' 질문 + 좌표 동봉(답하면 임시 장소 저장).
    fun askPlace(ctx: Context, lat: Double, lng: Double): JSONObject? {
        val body = JSONObject().put("lat", lat).put("lng", lng)
        return post(Prefs.baseUrl(ctx) + "/companion/askplace", body)
    }

    /// 방문 기록(체류·이동 구간). silent=true면 여정 기록만(말 걸기 생략).
    fun recordVisit(ctx: Context, place: String?, lat: Double, lng: Double,
                    startMs: Long, endMs: Long, minutes: Int,
                    silent: Boolean = false): JSONObject? {
        val body = JSONObject()
            .put("place", place ?: JSONObject.NULL)
            .put("lat", lat).put("lng", lng)
            .put("start_ts", startMs).put("end_ts", endMs).put("minutes", minutes)
            .put("silent", silent)
        return post(Prefs.baseUrl(ctx) + "/visits", body)
    }

    /// 공유받은 이미지/PDF → 분류기(/share/image) multipart 업로드.
    /// 백엔드가 영수증/일정/기록으로 분류·라우팅하고 {kind, ok, ...}를 반환한다.
    fun uploadShare(ctx: Context, bytes: ByteArray, filename: String): JSONObject? {
        val boundary = "----oracle" + System.currentTimeMillis()
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(Prefs.baseUrl(ctx) + "/share/image").openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 15000
                readTimeout = 280000          // PDF·여러 영수증 비전 처리 — 길게
                doOutput = true
                setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
            }
            conn.outputStream.use { out ->
                out.write(("--$boundary\r\nContent-Disposition: form-data; name=\"file\"; " +
                    "filename=\"$filename\"\r\nContent-Type: application/octet-stream\r\n\r\n").toByteArray(Charsets.UTF_8))
                out.write(bytes)
                out.write("\r\n--$boundary--\r\n".toByteArray(Charsets.UTF_8))
            }
            if (conn.responseCode in 200..299) {
                val txt = conn.inputStream.bufferedReader().use { it.readText() }
                if (txt.isNotBlank()) JSONObject(txt) else JSONObject()
            } else null
        } catch (e: Exception) {
            null
        } finally {
            conn?.disconnect()
        }
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

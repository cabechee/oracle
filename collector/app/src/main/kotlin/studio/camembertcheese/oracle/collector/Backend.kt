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

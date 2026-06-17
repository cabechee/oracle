package studio.camembertcheese.oracle.collector

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/// 수집기 설정(백엔드 주소·주기·기기ID·마지막 전송) + 알림 버퍼.
/// 알림 리스너 스레드와 동기화 스레드가 버퍼를 공유하므로 @Synchronized로 보호.
object Prefs {
    private const val NAME = "oracle_collector"
    private const val K_BASE = "base_url"
    private const val K_LAST_SYNC = "last_sync_ms"
    private const val K_DEVICE = "device_id"
    private const val K_NOTIF_BUF = "notif_buffer"
    private const val K_INTERVAL = "interval_min"

    private fun sp(ctx: Context) =
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    fun baseUrl(ctx: Context): String =
        sp(ctx).getString(K_BASE, "http://chocolat.tail575fea.ts.net:8001") ?: ""

    fun setBaseUrl(ctx: Context, v: String) =
        sp(ctx).edit().putString(K_BASE, v.trim().trimEnd('/')).apply()

    fun intervalMin(ctx: Context): Int = sp(ctx).getInt(K_INTERVAL, 1)
    fun setIntervalMin(ctx: Context, v: Int) =
        sp(ctx).edit().putInt(K_INTERVAL, v.coerceIn(1, 1440)).apply()

    fun lastSync(ctx: Context): Long = sp(ctx).getLong(K_LAST_SYNC, 0L)
    fun setLastSync(ctx: Context, v: Long) =
        sp(ctx).edit().putLong(K_LAST_SYNC, v).apply()

    fun deviceId(ctx: Context): String {
        sp(ctx).getString(K_DEVICE, null)?.let { return it }
        val id = "android-collector-" + UUID.randomUUID().toString().take(8)
        sp(ctx).edit().putString(K_DEVICE, id).apply()
        return id
    }

    // ── 앨범 버퍼 (NotificationListener가 적재, 동기화가 비움) ──
    @Synchronized
    fun addNotif(ctx: Context, app: String, title: String, text: String, ts: Long) {
        val arr = JSONArray(sp(ctx).getString(K_NOTIF_BUF, "[]"))
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            if (o.optString("app") == app && o.optString("title") == title &&
                o.optString("text") == text) return   // 중복(posted+updated) 방지
        }
        arr.put(JSONObject().put("app", app).put("title", title)
            .put("text", text).put("ts", ts))
        val out = if (arr.length() > 200) {
            val t = JSONArray()
            for (i in (arr.length() - 200) until arr.length()) t.put(arr.get(i))
            t
        } else arr
        sp(ctx).edit().putString(K_NOTIF_BUF, out.toString()).apply()
    }

    @Synchronized
    fun drainNotifs(ctx: Context): JSONArray {
        val arr = JSONArray(sp(ctx).getString(K_NOTIF_BUF, "[]"))
        sp(ctx).edit().putString(K_NOTIF_BUF, "[]").apply()
        return arr
    }

    @Synchronized
    fun restoreNotifs(ctx: Context, drained: JSONArray) {
        // 전송 실패 — 비웠던 알림을 되돌린다(그 사이 들어온 것 뒤에 붙임).
        val cur = JSONArray(sp(ctx).getString(K_NOTIF_BUF, "[]"))
        for (i in 0 until cur.length()) drained.put(cur.get(i))
        sp(ctx).edit().putString(K_NOTIF_BUF, drained.toString()).apply()
    }

    // ── 위치 상태(체류 머신) — 좌표는 정밀도 위해 String ──
    private const val K_ALAT = "anchor_lat"
    private const val K_ALNG = "anchor_lng"
    private const val K_ASTART = "anchor_start"
    private const val K_VISITON = "visit_on"
    private const val K_VPLACE = "visit_place"
    private const val K_TICK = "loc_tick"
    private const val K_BTPLACE = "bt_place"
    private const val K_BTCONN = "bt_connected"
    private const val K_PLACES = "places_cache"
    private const val K_PLACES_AT = "places_at"

    private fun getD(ctx: Context, k: String): Double? =
        sp(ctx).getString(k, null)?.toDoubleOrNull()

    fun anchorLat(ctx: Context) = getD(ctx, K_ALAT)
    fun anchorLng(ctx: Context) = getD(ctx, K_ALNG)
    fun anchorStart(ctx: Context): Long = sp(ctx).getLong(K_ASTART, 0L)
    fun setAnchor(ctx: Context, lat: Double, lng: Double, start: Long) =
        sp(ctx).edit().putString(K_ALAT, lat.toString()).putString(K_ALNG, lng.toString())
            .putLong(K_ASTART, start).apply()

    fun visitOn(ctx: Context): Boolean = sp(ctx).getBoolean(K_VISITON, false)
    fun setVisitOn(ctx: Context, v: Boolean) = sp(ctx).edit().putBoolean(K_VISITON, v).apply()
    fun visitPlace(ctx: Context): String = sp(ctx).getString(K_VPLACE, "") ?: ""
    fun setVisitPlace(ctx: Context, v: String) = sp(ctx).edit().putString(K_VPLACE, v).apply()

    fun bumpTick(ctx: Context): Int {
        val n = sp(ctx).getInt(K_TICK, 0) + 1
        sp(ctx).edit().putInt(K_TICK, n).apply()
        return n
    }

    fun btPlace(ctx: Context): String = sp(ctx).getString(K_BTPLACE, "") ?: ""
    fun setBtPlace(ctx: Context, v: String) = sp(ctx).edit().putString(K_BTPLACE, v).apply()
    /// BT 리시버가 적는 현재 연결된 기기명(연결 시 기기명, 끊기면 "").
    fun btConnected(ctx: Context): String = sp(ctx).getString(K_BTCONN, "") ?: ""
    fun setBtConnected(ctx: Context, v: String) = sp(ctx).edit().putString(K_BTCONN, v).apply()

    fun places(ctx: Context): String = sp(ctx).getString(K_PLACES, "[]") ?: "[]"
    fun placesFetchedAt(ctx: Context): Long = sp(ctx).getLong(K_PLACES_AT, 0L)
    fun setPlaces(ctx: Context, json: String, at: Long) =
        sp(ctx).edit().putString(K_PLACES, json).putLong(K_PLACES_AT, at).apply()
}

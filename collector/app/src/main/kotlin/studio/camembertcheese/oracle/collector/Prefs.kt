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

    /// 아직 안 보낸 알림 버퍼 개수 — 대시보드 '대기 신호'.
    fun notifBufferCount(ctx: Context): Int =
        try { JSONArray(sp(ctx).getString(K_NOTIF_BUF, "[]")).length() } catch (_: Exception) { 0 }

    /// 사용자가 수집을 켰는지(시작/중지 토글 표시용). 서비스 시작 시 true, 명시적 중지 시 false.
    fun collecting(ctx: Context): Boolean = sp(ctx).getBoolean("ui_collecting", false)
    fun setCollecting(ctx: Context, v: Boolean) =
        sp(ctx).edit().putBoolean("ui_collecting", v).apply()

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

    /// 체류 거점 = 머무는 동안 받은 fix들의 **누적 평균 좌표**(anchor=centroid). 드리프트가
    /// 평균에 녹아 한 점이 안 흔들린다. start=체류 시작 시각, anchor_n=평균 표본 수.
    fun anchorLat(ctx: Context) = getD(ctx, K_ALAT)
    fun anchorLng(ctx: Context) = getD(ctx, K_ALNG)
    fun anchorStart(ctx: Context): Long = sp(ctx).getLong(K_ASTART, 0L)
    fun setAnchor(ctx: Context, lat: Double, lng: Double, start: Long) =
        sp(ctx).edit().putString(K_ALAT, lat.toString()).putString(K_ALNG, lng.toString())
            .putLong(K_ASTART, start).apply()
    /// 평균 좌표만 갱신(체류 시작 시각은 보존) — 거점 안에서 평균을 굴릴 때.
    fun setAnchorCoords(ctx: Context, lat: Double, lng: Double) =
        sp(ctx).edit().putString(K_ALAT, lat.toString())
            .putString(K_ALNG, lng.toString()).apply()
    fun sampleCount(ctx: Context): Int = sp(ctx).getInt("anchor_n", 0)
    fun setSampleCount(ctx: Context, v: Int) = sp(ctx).edit().putInt("anchor_n", v).apply()

    /// 거점 이탈 디바운스 — 평균에서 확신 있게 벗어난 연속 틱 수(한 틱 튐 흡수).
    fun leavePending(ctx: Context): Int = sp(ctx).getInt("leave_pending", 0)
    fun setLeavePending(ctx: Context, v: Int) = sp(ctx).edit().putInt("leave_pending", v).apply()

    /// 도보/이동(차·대중교통) 판정용 직전 fix(속도 없을 때 변위로 추정).
    fun lastFixLat(ctx: Context) = getD(ctx, "lastfix_lat")
    fun lastFixLng(ctx: Context) = getD(ctx, "lastfix_lng")
    fun lastFixTime(ctx: Context): Long = sp(ctx).getLong("lastfix_t", 0L)
    fun setLastFix(ctx: Context, lat: Double, lng: Double, t: Long) =
        sp(ctx).edit().putString("lastfix_lat", lat.toString())
            .putString("lastfix_lng", lng.toString()).putLong("lastfix_t", t).apply()

    /// checkin 헛호출 방지 — 마지막으로 checkin 보낸 시(時) 버킷(epoch hour). 같은 시면 스킵.
    fun lastCheckinHour(ctx: Context): Long = sp(ctx).getLong("last_checkin_hour", -1L)
    fun setLastCheckinHour(ctx: Context, v: Long) =
        sp(ctx).edit().putLong("last_checkin_hour", v).apply()

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
    /// 차 등 BT 장소 탑승 시각(ms) — 하차 시 이동 구간 방문으로 기록(여정).
    fun btBoardTime(ctx: Context): Long = sp(ctx).getLong("bt_board_time", 0L)
    fun setBtBoardTime(ctx: Context, v: Long) =
        sp(ctx).edit().putLong("bt_board_time", v).apply()
    /// BT 리시버가 적는 현재 연결된 기기명(연결 시 기기명, 끊기면 "").
    fun btConnected(ctx: Context): String = sp(ctx).getString(K_BTCONN, "") ?: ""
    fun setBtConnected(ctx: Context, v: String) = sp(ctx).edit().putString(K_BTCONN, v).apply()
    /// WifiWatcher(NetworkCallback)가 적는 현재 WiFi SSID — 안드12+ getConnectionInfo 우회.
    fun wifiSsid(ctx: Context): String = sp(ctx).getString("wifi_ssid", "") ?: ""
    fun setWifiSsid(ctx: Context, v: String) = sp(ctx).edit().putString("wifi_ssid", v).apply()

    fun places(ctx: Context): String = sp(ctx).getString(K_PLACES, "[]") ?: "[]"
    fun placesFetchedAt(ctx: Context): Long = sp(ctx).getLong(K_PLACES_AT, 0L)
    fun setPlaces(ctx: Context, json: String, at: Long) =
        sp(ctx).edit().putString(K_PLACES, json).putLong(K_PLACES_AT, at).apply()

    // ── 차량 상태머신(주차중 ⇄ 운전중) ──
    // 출차 = 차 BT 연결 채로 주차지점서 200m+ 이동. 주차 = 차 BT 해제(디바운스).
    // 안전망 = 운전중 한참 정지 시 조용히 주차중 리셋. (재시작 시 carBaselined로 가짜이벤트 방지)
    fun carState(ctx: Context): String = sp(ctx).getString("car_state", "parked") ?: "parked"
    fun setCarState(ctx: Context, v: String) = sp(ctx).edit().putString("car_state", v).apply()

    /// 주차 위치 = 출차 200m 기준점. 차 BT 연결 순간/주차 시 갱신, 도보론 안 흔듦(차 위치 고정).
    fun departAnchor(ctx: Context): Pair<Double, Double>? {
        val la = getD(ctx, "depart_lat"); val lo = getD(ctx, "depart_lng")
        return if (la != null && lo != null) Pair(la, lo) else null
    }
    fun setDepartAnchor(ctx: Context, lat: Double, lng: Double) =
        sp(ctx).edit().putString("depart_lat", lat.toString())
            .putString("depart_lng", lng.toString()).apply()

    /// 안전망 정지 감지용 — 기준점 + 마지막으로 (정지반경 밖으로) 움직인 시각.
    fun driveAnchor(ctx: Context): Pair<Double, Double>? {
        val la = getD(ctx, "drive_lat"); val lo = getD(ctx, "drive_lng")
        return if (la != null && lo != null) Pair(la, lo) else null
    }
    fun driveLastMove(ctx: Context): Long = sp(ctx).getLong("drive_last_move", 0L)
    fun setDriveAnchor(ctx: Context, lat: Double, lng: Double, lastMove: Long) =
        sp(ctx).edit().putString("drive_lat", lat.toString())
            .putString("drive_lng", lng.toString())
            .putLong("drive_last_move", lastMove).apply()
    fun clearDriveAnchor(ctx: Context) =
        sp(ctx).edit().remove("drive_lat").remove("drive_lng")
            .remove("drive_last_move").apply()

    /// 운전 중 차 이름(드라이브 구간 라벨). 출차 시 set, 주차 시 "".
    fun carName(ctx: Context): String = sp(ctx).getString("car_name", "") ?: ""
    fun setCarName(ctx: Context, v: String) = sp(ctx).edit().putString("car_name", v).apply()

    /// 주차 디바운스 — 연속 BT 해제 틱 수(시동 깜빡임 흡수).
    fun parkPendingTicks(ctx: Context): Int = sp(ctx).getInt("park_pending_ticks", 0)
    fun setParkPendingTicks(ctx: Context, v: Int) =
        sp(ctx).edit().putInt("park_pending_ticks", v).apply()

    /// 출차 때 목적지 없으면 이 시각(ms) 이후 1회 재확인. 재확인 실행/주차 시 0으로.
    fun destRecheckAt(ctx: Context): Long = sp(ctx).getLong("dest_recheck_at", 0L)
    fun setDestRecheckAt(ctx: Context, v: Long) =
        sp(ctx).edit().putLong("dest_recheck_at", v).apply()

    /// 이번 정지구간에 충전확인을 한 시각(ms). driveLastMove보다 작으면 새 정지 → 다시 확인.
    fun chargeCheckedAt(ctx: Context): Long = sp(ctx).getLong("charge_checked_at", 0L)
    fun setChargeCheckedAt(ctx: Context, v: Long) =
        sp(ctx).edit().putLong("charge_checked_at", v).apply()
}

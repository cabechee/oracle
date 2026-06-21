package studio.camembertcheese.oracle.collector

import android.content.Context
import android.location.Location
import android.location.LocationManager
import android.net.wifi.WifiManager
import android.os.Build
import android.os.CancellationSignal
import android.os.SystemClock
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/// 위치·WiFi 저수준 — 순수 플랫폼(LocationManager·WifiManager). Play Services 무의존.
object Geo {

    private const val MAX_AGE_MS = 120_000L     // 2분 — 이보다 오래된 캐시 위치는 버림(엉뚱한 곳 기록 방지)
    private const val MAX_ACC_M = 500f          // 정확도 500m 초과(셀타워 등)면 버림

    fun distance(lat1: Double, lng1: Double, lat2: Double, lng2: Double): Float {
        val r = FloatArray(1)
        Location.distanceBetween(lat1, lng1, lat2, lng2, r)
        return r[0]
    }

    private fun ageMs(loc: Location): Long =
        (SystemClock.elapsedRealtimeNanos() - loc.elapsedRealtimeNanos) / 1_000_000L

    private fun usable(loc: Location?): Boolean =
        loc != null && loc.hasAccuracy() && loc.accuracy <= MAX_ACC_M && ageMs(loc) in 0..MAX_AGE_MS

    private fun freshFix(lm: LocationManager, ctx: Context, provider: String, timeoutSec: Long): Location? =
        try {
            val latch = CountDownLatch(1)
            val holder = arrayOfNulls<Location>(1)
            lm.getCurrentLocation(provider, CancellationSignal(), ctx.mainExecutor) {
                holder[0] = it; latch.countDown()
            }
            latch.await(timeoutSec, TimeUnit.SECONDS)
            holder[0]
        } catch (e: Exception) { null }

    /// 현재 위치 — **신선(≤2분)하고 정확(≤500m)한 fix만**. 없으면 null(오래된/엉뚱한 위치 기록 방지).
    ///
    /// GPS 신선 fix 우선(정확). 충분히 정확하지 않으면 네트워크도 시도. 캐시 lastKnown은 신선할 때만.
    /// 예전엔 fix 실패 시 lastKnown(몇 시간 전 위치)을 그대로 써서 엉뚱한 곳(마곡·서초 등)에 찍혔다.
    fun currentLocation(ctx: Context): Location? {
        val lm = ctx.getSystemService(Context.LOCATION_SERVICE) as? LocationManager ?: return null
        val gpsOn = lm.isProviderEnabled(LocationManager.GPS_PROVIDER)
        val netOn = lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER)
        if (!gpsOn && !netOn) return null
        val cands = ArrayList<Location>()
        try {
            if (Build.VERSION.SDK_INT >= 30) {
                if (gpsOn) freshFix(lm, ctx, LocationManager.GPS_PROVIDER, 12)?.let { cands.add(it) }
                // GPS가 충분히 정확하지 않을 때만 네트워크 fix 추가(빠르지만 부정확할 수 있음)
                if (cands.none { it.hasAccuracy() && it.accuracy <= 80f } && netOn)
                    freshFix(lm, ctx, LocationManager.NETWORK_PROVIDER, 6)?.let { cands.add(it) }
            }
            if (gpsOn) lm.getLastKnownLocation(LocationManager.GPS_PROVIDER)?.let { cands.add(it) }
            if (netOn) lm.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)?.let { cands.add(it) }
        } catch (e: SecurityException) {
            return null
        } catch (e: Exception) {
            // 무시 — 아래 필터로
        }
        // 신선·정확 후보 중 가장 정확한 것. 하나도 없으면 null(이번 틱은 위치 미확정으로 스킵)
        return cands.filter { usable(it) }.minByOrNull { it.accuracy }
    }

    /// 현재 연결된 WiFi SSID (위치 권한 필요). 없으면 null.
    @Suppress("DEPRECATION")
    fun wifiSsid(ctx: Context): String? {
        // 안드12+(API31)에선 WifiManager.connectionInfo가 백그라운드서 SSID를 가린다(<unknown ssid>).
        // → WifiWatcher(FLAG_INCLUDE_LOCATION_INFO NetworkCallback)가 Prefs에 적어둔 값을 우선 사용.
        val cached = Prefs.wifiSsid(ctx).trim()
        if (cached.isNotEmpty()) return cached
        return try {   // 레거시 폴백(안드11 이하·콜백 미동작 시)
            val wm = ctx.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
                ?: return null
            val raw = wm.connectionInfo?.ssid ?: return null
            val ssid = raw.replace("\"", "").trim()
            if (ssid.isEmpty() || ssid == "<unknown ssid>") null else ssid
        } catch (e: Exception) {
            null
        }
    }
}

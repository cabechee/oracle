package studio.camembertcheese.oracle.collector

import android.content.Context
import android.location.Location
import android.location.LocationManager
import android.net.wifi.WifiManager
import android.os.Build
import android.os.CancellationSignal
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/// 위치·WiFi 저수준 — 순수 플랫폼(LocationManager·WifiManager). Play Services 무의존.
object Geo {

    fun distance(lat1: Double, lng1: Double, lat2: Double, lng2: Double): Float {
        val r = FloatArray(1)
        Location.distanceBetween(lat1, lng1, lat2, lng2, r)
        return r[0]
    }

    /// 현재 위치 — getCurrentLocation(API30+, 신선) 우선, 실패 시 마지막 위치. 권한·미가용이면 null.
    fun currentLocation(ctx: Context): Location? {
        val lm = ctx.getSystemService(Context.LOCATION_SERVICE) as? LocationManager ?: return null
        val provider = when {
            lm.isProviderEnabled(LocationManager.GPS_PROVIDER) -> LocationManager.GPS_PROVIDER
            lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER) -> LocationManager.NETWORK_PROVIDER
            else -> return null
        }
        return try {
            if (Build.VERSION.SDK_INT >= 30) {
                val latch = CountDownLatch(1)
                val holder = arrayOfNulls<Location>(1)
                lm.getCurrentLocation(provider, CancellationSignal(), ctx.mainExecutor) {
                    holder[0] = it; latch.countDown()
                }
                latch.await(15, TimeUnit.SECONDS)
                holder[0] ?: lm.getLastKnownLocation(provider)
            } else {
                @Suppress("DEPRECATION")
                lm.getLastKnownLocation(provider)
            }
        } catch (e: SecurityException) {
            null
        } catch (e: Exception) {
            null
        }
    }

    /// 현재 연결된 WiFi SSID (위치 권한 필요). 없으면 null.
    @Suppress("DEPRECATION")
    fun wifiSsid(ctx: Context): String? {
        return try {
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

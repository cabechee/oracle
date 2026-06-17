package studio.camembertcheese.oracle.collector

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder

/// 수집 포그라운드 서비스 — 주기적으로(기본 30분) 미읽음 SMS·부재중 통화·알림 버퍼를
/// 백엔드(/signals/sync)로 보낸다. 배터리 최적화 제외 시 안정적으로 상시 동작.
/// (⚠️ Android 15+ dataSync FGS는 일일 누적 실행 제한이 있음 — v2에서 GPS 추가 시 location 타입 병행 권장)
class CollectorService : Service() {

    @Volatile private var running = false
    private var worker: Thread? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForegroundNotif()
        if (!running) {
            running = true
            worker = Thread { loop() }.also { it.start() }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        worker?.interrupt()
        super.onDestroy()
    }

    private fun loop() {
        while (running) {
            try { syncOnce(applicationContext) } catch (_: Exception) {}
            val mins = Prefs.intervalMin(applicationContext).coerceAtLeast(5)
            try { Thread.sleep(mins * 60_000L) } catch (_: InterruptedException) { break }
        }
    }

    private fun startForegroundNotif() {
        val mgr = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val chId = "oracle_collector"
        val ch = NotificationChannel(chId, "Oracle 수집", NotificationManager.IMPORTANCE_MIN)
        mgr.createNotificationChannel(ch)
        val notif = Notification.Builder(this, chId)
            .setContentTitle("Oracle 수집 중")
            .setContentText("문자·통화·알림을 모아 보냅니다")
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(1, notif, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(1, notif)
        }
    }

    companion object {
        fun start(ctx: Context) {
            val i = Intent(ctx, CollectorService::class.java)
            if (Build.VERSION.SDK_INT >= 26) ctx.startForegroundService(i) else ctx.startService(i)
        }

        fun stop(ctx: Context) {
            ctx.stopService(Intent(ctx, CollectorService::class.java))
        }

        /// 한 번 동기화 — 성공 시 true. 알림 버퍼는 실패하면 되돌린다(유실 방지).
        fun syncOnce(ctx: Context): Boolean {
            val sms = Collectors.unreadSms(ctx)
            val calls = Collectors.missedCalls(ctx, Prefs.lastSync(ctx))
            val notifs = Prefs.drainNotifs(ctx)
            val res = Backend.syncSignals(ctx, sms, calls, notifs)
            if (res == null) {
                Prefs.restoreNotifs(ctx, notifs)
                return false
            }
            Prefs.setLastSync(ctx, System.currentTimeMillis())
            return true
        }
    }
}

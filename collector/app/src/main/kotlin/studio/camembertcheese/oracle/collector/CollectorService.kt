package studio.camembertcheese.oracle.collector

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.bluetooth.BluetoothDevice
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import org.json.JSONArray
import org.json.JSONObject

/// 수집 포그라운드 서비스 — 신호(문자·통화·알림)는 sync_interval_min마다, 위치 체류 감지는
/// location-config poll_interval_sec마다. 둘 다 어드민(collector-config·location-config) 설정대로.
/// 배터리 최적화 제외 시 상시 동작. location 타입으로 Android15 dataSync 제한도 회피.
class CollectorService : Service() {

    @Volatile private var running = false
    private var worker: Thread? = null
    private var btWatcher: BtWatcher? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        registerBt()
    }

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
        btWatcher?.let { try { unregisterReceiver(it) } catch (_: Exception) {} }
        super.onDestroy()
    }

    /// BT 연결 감지 런타임 등록 — ACL_CONNECTED는 정적 등록이 막혀(암시적 제한) 서비스가 단다.
    private fun registerBt() {
        try {
            val w = BtWatcher()
            val f = IntentFilter().apply {
                addAction(BluetoothDevice.ACTION_ACL_CONNECTED)
                addAction(BluetoothDevice.ACTION_ACL_DISCONNECTED)
            }
            if (Build.VERSION.SDK_INT >= 34) {
                registerReceiver(w, f, Context.RECEIVER_NOT_EXPORTED)
            } else {
                @Suppress("UnspecifiedRegisterReceiverFlag")
                registerReceiver(w, f)
            }
            btWatcher = w
        } catch (_: Exception) {
        }
    }

    private fun loop() {
        while (running) {
            var sleepMs = 60_000L
            try {
                val cfg = Backend.fetchConfig(applicationContext)
                val enabled = cfg == null || cfg.optBoolean("enabled", true)
                val syncMin = (cfg?.optInt("sync_interval_min", 1) ?: 1).coerceAtLeast(1)
                val collectLoc = cfg == null || cfg.optBoolean("collect_location", true)
                Prefs.setIntervalMin(applicationContext, syncMin)
                if (enabled) {
                    // 신호 — sync_interval_min마다(루프가 더 잦게 돌아도 due일 때만).
                    if (System.currentTimeMillis() - Prefs.lastSync(applicationContext)
                        >= syncMin * 60_000L
                    ) {
                        syncOnce(applicationContext, cfg)
                    }
                    // 위치 — poll_interval_sec마다(루프 주기). 끄면 신호 주기로.
                    if (collectLoc) {
                        val loc = Backend.fetchLocationConfig(applicationContext)
                        val skip = loc == null || loc.optBoolean("skip_on_known_wifi", true)
                        LocationCollector.tick(applicationContext, skip)
                        sleepMs = ((loc?.optInt("poll_interval_sec", 60) ?: 60)
                            .coerceAtLeast(15)) * 1000L
                    } else {
                        sleepMs = syncMin * 60_000L
                    }
                    // 정시 체크인 — 위치와 완전 별개. 서버가 '이 시에 안 보냈으면' 게이팅.
                    tryCheckin(applicationContext)
                } else {
                    sleepMs = syncMin * 60_000L
                }
            } catch (_: Exception) {
            }
            try { Thread.sleep(sleepMs) } catch (_: InterruptedException) { break }
        }
    }

    private fun startForegroundNotif() {
        val mgr = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val chId = "oracle_collector"
        mgr.createNotificationChannel(
            NotificationChannel(chId, "Oracle 수집", NotificationManager.IMPORTANCE_MIN))
        val notif = Notification.Builder(this, chId)
            .setContentTitle("Oracle 수집 중")
            .setContentText("문자·통화·알림·위치를 모아 보냅니다")
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 34) {
            // 위치 권한 있으면 location 타입 포함(없으면 dataSync만 — FGS 시작 거부 방지).
            var type = ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
            if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
                == PackageManager.PERMISSION_GRANTED
            ) {
                type = type or ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
            }
            startForeground(1, notif, type)
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

        /// 신호 한 번 동기화 — 성공 시 true. 알림 버퍼는 실패하면 되돌린다(유실 방지).
        /// cfg(어드민 설정)의 수집 항목 토글을 존중. cfg=null이면 전부 수집(테스트·폴백).
        fun syncOnce(ctx: Context, cfg: JSONObject? = null): Boolean {
            val sms = if (cfg?.optBoolean("collect_sms", true) != false)
                Collectors.unreadSms(ctx) else JSONArray()
            val calls = if (cfg?.optBoolean("collect_calls", true) != false)
                Collectors.missedCalls(ctx, Prefs.lastSync(ctx)) else JSONArray()
            val notifs = if (cfg?.optBoolean("collect_notifications", true) != false)
                Prefs.drainNotifs(ctx) else JSONArray()
            val res = Backend.syncSignals(ctx, sms, calls, notifs)
            if (res == null) {
                Prefs.restoreNotifs(ctx, notifs)
                return false
            }
            Prefs.setLastSync(ctx, System.currentTimeMillis())
            return true
        }

        /// 정시 체크인 시도 — 매 루프 호출, 서버가 '이 시(정시)에 안 보냈으면'만 발화(게이팅).
        /// 위치와 완전 별개 — GPS 안 봄.
        fun tryCheckin(ctx: Context) {
            val r = Backend.companionSay(ctx, "checkin", null) ?: return
            val text = r.optString("text").trim()
            if (text.isNotEmpty()) Notify.companion(ctx, r.optString("speaker"), text)
        }
    }
}


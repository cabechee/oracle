package studio.camembertcheese.oracle.collector

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import org.json.JSONArray
import org.json.JSONObject

/// 수집 포그라운드 서비스 — 신호(문자·통화·알림)는 sync_interval_min마다, 위치 체류 감지는
/// location-config poll_interval_sec마다. 둘 다 어드민(collector-config·location-config) 설정대로.
/// 배터리 최적화 제외 시 상시 동작. location 타입으로 Android15 dataSync 제한도 회피.
class CollectorService : Service() {

    @Volatile private var running = false
    private var worker: Thread? = null
    // 상시 CPU 깨움 — Doze에 Thread.sleep이 늘어나 틱이 밀리는 걸 막음(서비스 도는 내내 보유).
    private var wakeLock: PowerManager.WakeLock? = null
    private var btWatcher: BtWatcher? = null
    // BT 프로필 프록시(차 오디오 연결 감지) — ACL_CONNECTED 브로드캐스트가 기기따라 안 와서
    // (특히 삼성/안드14) 매 루프 폴링으로 보강. 연결되면 그 기기명을 Prefs에.
    @Volatile private var headsetProxy: BluetoothProfile? = null
    @Volatile private var a2dpProxy: BluetoothProfile? = null
    private var wifiCb: ConnectivityManager.NetworkCallback? = null
    // BT 폴링 디바운스 — 차 BT 연결 깜빡임(flapping)에 가짜 탑승/하차가 뜨지 않게.
    @Volatile private var btBaselined = false   // 재시작 직후 첫 폴은 기준선만(이벤트 X)
    private var btCandidate: String? = null      // 바뀐 값 후보(연속 확인용)
    private var btCandidateCount = 0

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        registerBt()
        setupBtProxies()
        registerWifi()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Prefs.setCollecting(applicationContext, true)   // 대시보드 토글 — 시작됨
        startForegroundNotif()
        acquireWake()
        if (!running) {
            running = true
            worker = Thread { loop() }.also { it.start() }
        }
        return START_STICKY
    }

    /// partial wake lock 획득 — CPU를 안 재워 Doze에도 1분 틱이 제때 돈다(상태/차감지 안 밀림).
    /// 배터리 더 씀(상시 깨움) 대신 신뢰성. 프로세스 죽으면 OS가 자동 해제(영구 누수 없음).
    private fun acquireWake() {
        if (wakeLock?.isHeld == true) return
        try {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "oracle:collector")
                .apply { setReferenceCounted(false); acquire() }
            L.i("wake lock 획득 — Doze에도 틱 유지")
        } catch (e: Exception) {
            L.i("wake lock 실패: ${e.message}")
        }
    }

    override fun onDestroy() {
        running = false
        worker?.interrupt()
        try { if (wakeLock?.isHeld == true) wakeLock?.release() } catch (_: Exception) {}
        wakeLock = null
        btWatcher?.let { try { unregisterReceiver(it) } catch (_: Exception) {} }
        closeBtProxies()
        wifiCb?.let {
            try {
                (getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager)
                    ?.unregisterNetworkCallback(it)
            } catch (_: Exception) {}
        }
        super.onDestroy()
    }

    /// 현재 WiFi SSID 감지 — 안드12+(API31)에선 NetworkCallback에 FLAG_INCLUDE_LOCATION_INFO를
    /// 줘야 SSID가 안 가려진다(위치 권한 필요, 보유). 콜백이 Prefs에 SSID를 적고 Geo.wifiSsid가 읽음.
    /// API<31은 레거시 getConnectionInfo가 동작하므로 콜백 불필요.
    private fun registerWifi() {
        if (Build.VERSION.SDK_INT < 31) { L.i("WiFi 콜백 스킵(SDK<31, 레거시)"); return }
        try {
            val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
                ?: run { L.i("WiFi: ConnectivityManager 없음"); return }
            val cb = object : ConnectivityManager.NetworkCallback(
                ConnectivityManager.NetworkCallback.FLAG_INCLUDE_LOCATION_INFO) {
                override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                    if (!caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) return
                    val info = caps.transportInfo as? WifiInfo
                    val ssid = (info?.ssid ?: "").replace("\"", "").trim()
                    // 신호세기 변동마다 불려서, 실제 SSID가 바뀔 때만 기록(로그·prefs 둘 다).
                    if (ssid.isNotEmpty() && ssid != "<unknown ssid>"
                        && Prefs.wifiSsid(applicationContext) != ssid) {
                        Prefs.setWifiSsid(applicationContext, ssid)
                        L.i("WiFi 연결: $ssid")
                    }
                }
                override fun onLost(network: Network) {
                    if (Prefs.wifiSsid(applicationContext).isNotEmpty()) {
                        Prefs.setWifiSsid(applicationContext, "")
                        L.i("WiFi 끊김")
                    }
                }
            }
            val req = NetworkRequest.Builder()
                .addTransportType(NetworkCapabilities.TRANSPORT_WIFI).build()
            cm.registerNetworkCallback(req, cb)
            wifiCb = cb
            L.i("WiFi 콜백 등록됨(FLAG_INCLUDE_LOCATION_INFO)")
        } catch (e: Exception) {
            L.i("WiFi 콜백 등록 실패: ${e.message}")
        }
    }

    /// BT 연결 감지 런타임 등록 — ACL_CONNECTED는 정적 등록이 막혀(암시적 제한) 서비스가 단다.
    /// (브로드캐스트는 빠른 길. 기기따라 안 오므로 프록시 폴링이 정설.)
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

    /// HFP/A2DP 프로필 프록시 확보 — 비동기로 붙고(보통 수백 ms), 이후 connectedDevices를 폴링.
    private fun setupBtProxies() {
        try {
            val mgr = getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager ?: return
            val adapter = mgr.adapter ?: return
            val listener = object : BluetoothProfile.ServiceListener {
                override fun onServiceConnected(profile: Int, proxy: BluetoothProfile) {
                    when (profile) {
                        BluetoothProfile.HEADSET -> headsetProxy = proxy
                        BluetoothProfile.A2DP -> a2dpProxy = proxy
                    }
                    L.i("BT 프록시 연결됨: profile=$profile")
                }
                override fun onServiceDisconnected(profile: Int) {
                    when (profile) {
                        BluetoothProfile.HEADSET -> headsetProxy = null
                        BluetoothProfile.A2DP -> a2dpProxy = null
                    }
                }
            }
            adapter.getProfileProxy(this, listener, BluetoothProfile.HEADSET)
            adapter.getProfileProxy(this, listener, BluetoothProfile.A2DP)
        } catch (_: Exception) {
        }
    }

    private fun closeBtProxies() {
        try {
            val mgr = getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
            val adapter = mgr?.adapter ?: return
            headsetProxy?.let { adapter.closeProfileProxy(BluetoothProfile.HEADSET, it) }
            a2dpProxy?.let { adapter.closeProfileProxy(BluetoothProfile.A2DP, it) }
        } catch (_: Exception) {
        }
    }

    /// 현재 연결된 등록 장소(bt) 기기명 폴링 → Prefs.btConnected 갱신(차 등). 프록시 미준비면 건너뜀.
    /// LocationCollector는 Prefs.btConnected만 보므로 브로드캐스트/폴링 어느 쪽이 채워도 동작.
    private fun pollBtConnected(ctx: Context) {
        if (headsetProxy == null && a2dpProxy == null) return   // 미준비 — 브로드캐스트 값 보존
        val names = ArrayList<String>()
        try {
            for (p in listOfNotNull(headsetProxy, a2dpProxy)) {
                for (d in p.connectedDevices) {
                    val n = try { d.name } catch (e: SecurityException) { null }
                    if (!n.isNullOrBlank() && !names.contains(n)) names.add(n)
                }
            }
        } catch (_: Exception) {
            return
        }
        val places = PlacesCache.get(ctx)
        var chosen = ""                                          // 등록 장소 BT만 추적(이어폰 등 무시)
        for (n in names) {
            if (PlacesCache.byBt(places, n) != null) { chosen = n; break }
        }
        // 재시작 직후 — 실제 현재 상태로 '기준선'만 맞춘다(탑승/하차 이벤트 없이).
        // 안 그러면 stale btConnected('차')에서 ''로 바뀌며 가짜 '하차·주차'가 뜬다(09:34 버그).
        if (!btBaselined) {
            btBaselined = true
            if (Prefs.btConnected(ctx) != chosen) {
                Prefs.setBtConnected(ctx, chosen)
                Prefs.setBtPlace(ctx, if (chosen.isBlank()) ""
                                      else (PlacesCache.byBt(places, chosen) ?: ""))
                L.i("BT 기준선 동기화: '$chosen' (재시작 — 이벤트 없이)")
            }
            return
        }
        if (chosen == Prefs.btConnected(ctx)) {                  // 변화 없음 — 후보 리셋
            btCandidate = null; btCandidateCount = 0
            return
        }
        // 변화 감지 — 차 BT 깜빡임(connect/disconnect/reconnect) 방지: 2회 연속 같아야 확정.
        if (chosen == btCandidate) {
            btCandidateCount++
        } else {
            btCandidate = chosen; btCandidateCount = 1
        }
        if (btCandidateCount >= 2) {
            L.i("BT 폴링 변화(확정): '${Prefs.btConnected(ctx)}' -> '$chosen'  [연결=$names]")
            Prefs.setBtConnected(ctx, chosen)
            btCandidate = null; btCandidateCount = 0
        } else {
            L.i("BT 변화 후보(대기 — 깜빡임 방지): '$chosen'  [연결=$names]")
        }
    }

    /// 라이브 상태 + 최근 로그를 백엔드에 보고 — 어드민 📍 장소서 현재 WiFi·위치·로그 확인(adb 대체).
    private fun reportStatus(ctx: Context) {
        try {
            val status = JSONObject()
                .put("device_id", Prefs.deviceId(ctx))
                .put("wifi", Geo.wifiSsid(ctx) ?: "")
                .put("place", Prefs.visitPlace(ctx))
                .put("visit_on", Prefs.visitOn(ctx))
                .put("bt", Prefs.btConnected(ctx))
                .put("car_state", Prefs.carState(ctx))   // 주차중 | 운전중 (어드민 표시)
                .put("logs", JSONArray(L.snapshot()))
            // 현재 GPS(앵커) — 차 등 이동 중에도 1분마다 갱신돼 어디 있는지 보임.
            val la = Prefs.anchorLat(ctx)
            val lo = Prefs.anchorLng(ctx)
            if (la != null && lo != null) status.put("lat", la).put("lng", lo)
            Backend.reportStatus(ctx, status)
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
                        pollBtConnected(applicationContext)   // 차 BT 연결 폴링(브로드캐스트 보강)
                        LocationCollector.tick(applicationContext, skip, loc)
                        sleepMs = ((loc?.optInt("poll_interval_sec", 60) ?: 60)
                            .coerceAtLeast(15)) * 1000L
                    } else {
                        sleepMs = syncMin * 60_000L
                    }
                    // 정시 체크인 — 위치와 완전 별개. 서버가 '이 시에 안 보냈으면' 게이팅.
                    tryCheckin(applicationContext)
                    // 라이브 상태 보고(현재 WiFi·위치·BT·최근 로그) — 어드민서 adb 없이 확인.
                    reportStatus(applicationContext)
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
        // ⚠️ 안드15(API35)에서 **dataSync FGS는 6시간/일 제한** — 만료되면 OS가 서비스를 멈추고,
        // START_STICKY 재시작이 startForeground(dataSync)에서 ForegroundServiceStartNotAllowedException로
        // 크래시 → ~6시간마다 재시작/가짜 주차의 근본 원인이었다.
        // **location 타입은 시간제한 없음** — 위치권한 있으면 location만 쓴다(신호 수집도 그 FGS 안에서 함).
        try {
            if (Build.VERSION.SDK_INT >= 34) {
                val type = if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
                    == PackageManager.PERMISSION_GRANTED)
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
                else
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
                startForeground(1, notif, type)
            } else {
                startForeground(1, notif)
            }
        } catch (e: Exception) {
            // FGS 시작 거부(시간제한·백그라운드 제약 등) — 크래시(무한 재시작) 대신 무타입 폴백, 그래도 안 되면 포기.
            L.i("startForeground 실패: ${e.message}")
            try { startForeground(1, notif) } catch (_: Exception) {}
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
            // lastSync 리셋(재설치 등으로 0)이면 통화기록 전체(최근 20건=수일~수주 전까지)를
            // 새 부재중으로 쏟아내지 않게 2시간 베이스라인만 — 직전에 놓친 건 잡되 묵은 건 무시.
            val callSince = Prefs.lastSync(ctx).let {
                if (it <= 0L) System.currentTimeMillis() - 2 * 3600_000L else it
            }
            val calls = if (cfg?.optBoolean("collect_calls", true) != false)
                Collectors.missedCalls(ctx, callSince) else JSONArray()
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


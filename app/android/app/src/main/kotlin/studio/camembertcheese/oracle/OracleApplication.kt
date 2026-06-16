package studio.camembertcheese.oracle

import android.app.Application
import android.bluetooth.BluetoothDevice
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build

/// 앱 프로세스 수명 동안 BT 연결을 감지 — 차 오디오 등 연결 시 "그 장소에 있다" 신호.
///
/// MainActivity(액티비티 수명)보다 오래 살아 백그라운드에서도 받는다 — 위치 포그라운드
/// 서비스가 프로세스를 유지하므로, Application에 건 런타임 리시버는 그동안 계속 산다.
/// 연결 기기명을 flutter SharedPreferences(`loc_bt_connected`)에 적고, 위치 isolate가
/// 1분 틱에서 읽어 등록 장소(places.bt)와 매칭한다. (home_widget과 같은 네이티브↔prefs 패턴)
/// Flutter v2 임베딩은 별도 Application이 필요 없으므로 android.app.Application 상속이면 충분.
class OracleApplication : Application() {
    private val prefsName = "FlutterSharedPreferences"
    private val btKey = "flutter.loc_bt_connected"

    private val btReceiver = object : BroadcastReceiver() {
        override fun onReceive(ctx: Context, intent: Intent) {
            try {
                @Suppress("DEPRECATION")
                val dev: BluetoothDevice? =
                    intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
                // 기기명 읽기는 BLUETOOTH_CONNECT 권한 필요(없으면 SecurityException → 빈값)
                val name = try { dev?.name ?: "" } catch (e: SecurityException) { "" }
                val sp = ctx.getSharedPreferences(prefsName, Context.MODE_PRIVATE)
                when (intent.action) {
                    BluetoothDevice.ACTION_ACL_CONNECTED ->
                        if (name.isNotEmpty()) sp.edit().putString(btKey, name).apply()
                    BluetoothDevice.ACTION_ACL_DISCONNECTED ->
                        if (sp.getString(btKey, "") == name)
                            sp.edit().putString(btKey, "").apply()
                }
            } catch (_: Exception) {
                // 리시버 예외 삼킴 — 앱 안정성 우선
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        try {
            val filter = IntentFilter().apply {
                addAction(BluetoothDevice.ACTION_ACL_CONNECTED)
                addAction(BluetoothDevice.ACTION_ACL_DISCONNECTED)
            }
            if (Build.VERSION.SDK_INT >= 34) {
                registerReceiver(btReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
            } else {
                @Suppress("UnspecifiedRegisterReceiverFlag")
                registerReceiver(btReceiver, filter)
            }
        } catch (_: Exception) {
            // 등록 실패해도 앱은 정상 — BT 기능만 비활성
        }
    }
}

package studio.camembertcheese.oracle.collector

import android.bluetooth.BluetoothDevice
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/// BT 연결 감지 — 차 오디오 등 연결 시 그 기기명을 prefs에 적는다(LocationCollector가 places.bt와 매칭).
/// ACL_CONNECTED는 매니페스트 정적 등록이 막혀 있어(암시적 브로드캐스트 제한), 서비스가 런타임 등록한다.
class BtWatcher : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        try {
            @Suppress("DEPRECATION")
            val dev: BluetoothDevice? = intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
            val name = try { dev?.name ?: "" } catch (e: SecurityException) { "" }
            when (intent.action) {
                BluetoothDevice.ACTION_ACL_CONNECTED ->
                    if (name.isNotEmpty()) Prefs.setBtConnected(ctx.applicationContext, name)
                BluetoothDevice.ACTION_ACL_DISCONNECTED ->
                    if (Prefs.btConnected(ctx.applicationContext) == name)
                        Prefs.setBtConnected(ctx.applicationContext, "")
            }
        } catch (_: Exception) {
        }
    }
}

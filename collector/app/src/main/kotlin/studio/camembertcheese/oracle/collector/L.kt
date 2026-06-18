package studio.camembertcheese.oracle.collector

import android.util.Log
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/// 수집기 로그 — Logcat + 인메모리 링버퍼.
/// 버퍼는 매 사이클 백엔드(/collector-status)로 보고돼 어드민서 보임 → 운전 중 adb logcat 대체.
/// (이벤트(BT 전환·도착·나섬·탑승·주차) 때만 쌓여 시끄럽지 않음. 프로세스 살아있는 동안 유지.)
object L {
    private const val TAG = "OracleCollector"
    private val buf = ArrayDeque<String>()
    private val fmt = SimpleDateFormat("MM-dd HH:mm:ss", Locale.US)

    fun i(msg: String) {
        Log.i(TAG, msg)
        synchronized(buf) {
            buf.addLast(fmt.format(Date()) + "  " + msg)
            while (buf.size > 100) buf.removeFirst()
        }
    }

    fun snapshot(): List<String> = synchronized(buf) { buf.toList() }
}

package studio.camembertcheese.oracle.collector

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.text.format.DateFormat
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

/// 최소 제어 UI — 백엔드 주소·권한·시작/중지·즉시 전송 테스트·상태. (AppCompat 무의존 프로그래매틱 UI)
class MainActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var urlField: EditText

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val d = resources.displayMetrics.density
        val pad = (16 * d).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad * 2, pad, pad)
        }

        root.addView(TextView(this).apply { text = "Oracle 수집기"; textSize = 22f })
        root.addView(TextView(this).apply {
            text = "문자·통화·앱 알림을 모아 백엔드로 보냅니다.\n(아이폰이 못 하는 수동 수집 전담)"
            setPadding(0, pad / 2, 0, pad)
        })

        root.addView(TextView(this).apply { text = "백엔드 주소" })
        urlField = EditText(this).apply {
            inputType = InputType.TYPE_TEXT_VARIATION_URI
            setText(Prefs.baseUrl(this@MainActivity))
        }
        root.addView(urlField)
        root.addView(button("주소 저장") {
            Prefs.setBaseUrl(this, urlField.text.toString()); toast("저장됨"); refresh()
        })

        root.addView(spacer(pad))
        root.addView(button("권한 요청 (문자·통화·알림)") { requestPerms() })
        root.addView(button("알림 접근 설정 열기") {
            safeStart(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        })
        root.addView(button("배터리 최적화 제외") {
            safeStart(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        })
        root.addView(button("위치 ‘항상 허용’ 설정 (백그라운드 위치)") {
            safeStart(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                android.net.Uri.parse("package:$packageName")))
        })

        root.addView(spacer(pad))
        root.addView(button("수집 시작") { CollectorService.start(this); toast("수집 시작"); refresh() })
        root.addView(button("수집 중지") { CollectorService.stop(this); toast("수집 중지"); refresh() })
        root.addView(button("지금 한 번 보내기 (테스트)") {
            Thread {
                val ok = CollectorService.syncOnce(applicationContext)
                runOnUiThread { toast(if (ok) "전송 성공" else "전송 실패 (주소·권한 확인)"); refresh() }
            }.start()
        })

        root.addView(spacer(pad))
        status = TextView(this)
        root.addView(status)

        setContentView(ScrollView(this).apply { addView(root) })
        refresh()
    }

    private fun refresh() {
        val last = Prefs.lastSync(this)
        val lastStr = if (last == 0L) "없음"
        else DateFormat.format("MM-dd HH:mm", last).toString()
        status.text = "기기 ID: ${Prefs.deviceId(this)}\n" +
            "백엔드: ${Prefs.baseUrl(this)}\n" +
            "마지막 전송: $lastStr · 주기: ${Prefs.intervalMin(this)}분"
    }

    private fun requestPerms() {
        val perms = mutableListOf(
            Manifest.permission.READ_SMS,
            Manifest.permission.READ_CALL_LOG,
            Manifest.permission.ACCESS_FINE_LOCATION)
        if (Build.VERSION.SDK_INT >= 33) perms.add(Manifest.permission.POST_NOTIFICATIONS)
        if (Build.VERSION.SDK_INT >= 31) perms.add(Manifest.permission.BLUETOOTH_CONNECT)
        requestPermissions(perms.toTypedArray(), 1)
    }

    // ── UI 헬퍼 ──
    private fun button(label: String, onClick: () -> Unit) =
        Button(this).apply { text = label; setOnClickListener { onClick() } }

    private fun spacer(h: Int) = View(this).apply {
        layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, h)
    }

    private fun safeStart(i: Intent) {
        try { startActivity(i) } catch (_: Exception) { toast("열 수 없음") }
    }

    private fun toast(m: String) = Toast.makeText(this, m, Toast.LENGTH_SHORT).show()
}

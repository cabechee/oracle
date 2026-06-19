package studio.camembertcheese.oracle.collector

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

/// 수집기 대시보드 — '지금 잘 돌고 있나·뭐가 막혔나'를 위에서부터 바로 읽히게.
/// 상태 요약 → 점검(권한 ✓/설정) → 지금 상태(차·WiFi·BT·장소) → 수집 항목 → 액션 → 설정.
/// AppCompat/Compose 무의존 프로그래매틱 UI. 라이브 값은 onResume마다 새로고침.
class MainActivity : Activity() {

    // 라이트 팔레트
    private val cPage = 0xFFF7F5EF.toInt()
    private val cCard = 0xFFFFFFFF.toInt()
    private val cText = 0xFF22221F.toInt()
    private val cMuted = 0xFF6E6C66.toInt()
    private val cHint = 0xFF9C9A91.toInt()
    private val cBorder = 0xFFE6E3DB.toInt()
    private val cGreen = 0xFF2E7D32.toInt(); private val cGreenBg = 0xFFE7F2DE.toInt()
    private val cAmber = 0xFFA9690A.toInt(); private val cAmberBg = 0xFFFBEEDA.toInt()
    private val cInfo = 0xFF185FA5.toInt(); private val cInfoBg = 0xFFE6F1FB.toInt()
    private val cChipBg = 0xFFEFEDE6.toInt()

    // 새로고침마다 갱신되는 뷰들
    private lateinit var statusPill: TextView
    private lateinit var heroDot: View
    private lateinit var heroStatus: TextView
    private lateinit var heroSub: TextView
    private lateinit var waitStat: TextView
    private lateinit var healthBadge: TextView
    private lateinit var healthBody: LinearLayout
    private lateinit var liveBody: LinearLayout
    private lateinit var toggleBtn: Button
    private lateinit var urlField: EditText
    private lateinit var deviceLabel: TextView

    private val density get() = resources.displayMetrics.density
    private fun dp(v: Int) = (v * density).toInt()
    private val wrap = LinearLayout.LayoutParams.WRAP_CONTENT
    private val match = LinearLayout.LayoutParams.MATCH_PARENT
    private fun rowParams() = LinearLayout.LayoutParams(match, wrap)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(cPage)
            setPadding(dp(16), dp(20), dp(16), dp(24))
        }

        // ── 상단 바: 타이틀 + 상태 칩 ──
        root.addView(LinearLayout(this).apply {
            layoutParams = rowParams()
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(2), 0, dp(2), dp(14))
            addView(tv("Oracle 수집기", 19f, cText, bold = true),
                LinearLayout.LayoutParams(0, wrap, 1f))
            statusPill = tv("", 12f, cMuted).apply { setPadding(dp(10), dp(5), dp(10), dp(5)) }
            addView(statusPill)
        })

        // ── 카드 1: 상태 요약 ──
        val hero = card()
        hero.addView(LinearLayout(this).apply {
            layoutParams = rowParams()
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            heroDot = View(this@MainActivity)
            addView(heroDot, LinearLayout.LayoutParams(dp(9), dp(9)).apply { rightMargin = dp(8) })
            heroStatus = tv("…", 19f, cText, bold = true)
            addView(heroStatus, LinearLayout.LayoutParams(0, wrap, 1f))
        })
        heroSub = tv("", 13f, cMuted).apply { setPadding(0, dp(4), 0, 0) }
        hero.addView(heroSub)
        val statBox = stat("대기 신호", "—")
        waitStat = statBox.findViewWithTag<TextView>("v")
        hero.addView(LinearLayout(this).apply {
            layoutParams = rowParams()
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(12), 0, 0)
            addView(statBox, LinearLayout.LayoutParams(0, wrap, 1f))
        })
        addCard(root, hero)

        // ── 카드 2: 점검(권한) ──
        val health = card()
        health.addView(LinearLayout(this).apply {
            layoutParams = rowParams()
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, 0, 0, dp(2))
            addView(tv("점검", 13f, cMuted, bold = true), LinearLayout.LayoutParams(0, wrap, 1f))
            healthBadge = tv("", 12f, cGreen).apply { setPadding(dp(8), dp(2), dp(8), dp(2)) }
            addView(healthBadge)
        })
        healthBody = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        health.addView(healthBody)
        addCard(root, health)

        // ── 카드 3: 지금 상태(라이브 센서) ──
        val live = card()
        live.addView(tv("지금 상태", 13f, cMuted, bold = true).apply { setPadding(0, 0, 0, dp(2)) })
        liveBody = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        live.addView(liveBody)
        addCard(root, live)

        // ── 카드 4: 수집 항목 ──
        val items = card()
        items.addView(tv("수집 항목", 13f, cMuted, bold = true).apply { setPadding(0, 0, 0, dp(10)) })
        items.addView(LinearLayout(this).apply {
            layoutParams = rowParams()
            orientation = LinearLayout.HORIZONTAL
            addView(chip("문자")); addView(chip("통화")); addView(chip("알림")); addView(chip("위치"))
        })
        addCard(root, items)

        // ── 액션 ──
        toggleBtn = primaryBtn("수집 시작") {
            if (Prefs.collecting(this)) {
                CollectorService.stop(this); Prefs.setCollecting(this, false); toast("수집 중지")
            } else {
                CollectorService.start(this); toast("수집 시작")
            }
            refresh()
        }
        root.addView(toggleBtn)
        root.addView(LinearLayout(this).apply {
            layoutParams = rowParams()
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(8), 0, dp(4))
            addView(smallBtn("지금 전송") {
                Thread {
                    val ok = CollectorService.syncOnce(applicationContext)
                    runOnUiThread { toast(if (ok) "전송 성공" else "전송 실패 (주소·권한 확인)"); refresh() }
                }.start()
            }.apply { (layoutParams as LinearLayout.LayoutParams).rightMargin = dp(8) })
            addView(smallBtn("로그") { showLogs() })
        })

        // ── 카드 5: 설정 ──
        val settings = card()
        settings.addView(tv("설정", 13f, cMuted, bold = true).apply { setPadding(0, 0, 0, dp(10)) })
        settings.addView(tv("백엔드 주소", 12f, cHint))
        urlField = EditText(this).apply {
            inputType = InputType.TYPE_TEXT_VARIATION_URI
            setText(Prefs.baseUrl(this@MainActivity))
            textSize = 14f; setTextColor(cText)
        }
        settings.addView(urlField, rowParams())
        settings.addView(Button(this).apply {
            text = "주소 저장"; textSize = 13f; setTextColor(cText); isAllCaps = false
            background = strokeBg()
            setPadding(dp(14), dp(9), dp(14), dp(9))
            setOnClickListener {
                Prefs.setBaseUrl(this@MainActivity, urlField.text.toString()); toast("저장됨"); refresh()
            }
            layoutParams = rowParams().apply { topMargin = dp(8) }
        })
        deviceLabel = tv("", 12f, cHint).apply { setPadding(0, dp(10), 0, 0) }
        settings.addView(deviceLabel)
        addCard(root, settings)

        setContentView(ScrollView(this).apply { setBackgroundColor(cPage); addView(root) })
        refresh()
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    // ── 새로고침: 라이브 값 다시 읽어 반영 ──
    private fun refresh() {
        val collecting = Prefs.collecting(this)
        val last = Prefs.lastSync(this)
        val interval = Prefs.intervalMin(this)
        val freshMs = maxOf(15L, interval * 3L) * 60_000L
        val now = System.currentTimeMillis()

        // 상태 요약 — 마지막 전송 신선도로 판단(실데이터)
        val (label, color, bg) = when {
            !collecting -> Triple("중지됨", cMuted, cChipBg)
            last == 0L -> Triple("시작됨 · 첫 전송 대기", cGreen, cGreenBg)
            now - last <= freshMs -> Triple("수집 중", cGreen, cGreenBg)
            else -> Triple("최근 전송 없음", cAmber, cAmberBg)
        }
        heroStatus.text = label
        heroDot.background = oval(color)
        statusPill.text = label
        statusPill.setTextColor(color)
        statusPill.background = pillBg(bg)
        heroSub.text = if (last == 0L) "아래에서 수집을 시작하세요"
        else "마지막 전송 ${agoStr(now - last)} 전 · ${interval}분 주기"
        waitStat.text = "${Prefs.notifBufferCount(this)}건"
        toggleBtn.text = if (collecting) "수집 중지" else "수집 시작"

        // 점검(권한) — 빠진 것만 [설정], 나머진 ✓
        healthBody.removeAllViews()
        val perms = listOf<Triple<String, Boolean, () -> Unit>>(
            Triple("문자·통화 읽기", smsCallsGranted()) { requestPerms() },
            Triple("알림 접근", notifAccessGranted()) {
                openSetting(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS) },
            Triple("위치 항상 허용", locationAlwaysGranted()) { openAppDetails() },
            Triple("배터리 최적화 제외", batteryExempt()) {
                openSetting(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS) },
        )
        var need = 0
        for ((i, p) in perms.withIndex()) {
            if (!p.second) need++
            if (i > 0) healthBody.addView(divider())
            healthBody.addView(permRow(p.first, p.second, p.third))
        }
        if (need == 0) {
            healthBadge.text = "모두 정상"; healthBadge.setTextColor(cGreen)
            healthBadge.background = pillBg(cGreenBg)
        } else {
            healthBadge.text = "${need}건 조치 필요"; healthBadge.setTextColor(cAmber)
            healthBadge.background = pillBg(cAmberBg)
        }

        // 지금 상태(라이브)
        liveBody.removeAllViews()
        val carPill = if (Prefs.carState(this) == "driving")
            pillView("운전중", cInfo, cInfoBg) else pillView("주차중", cMuted, cChipBg)
        liveBody.addView(infoRow("차", carPill))
        liveBody.addView(divider())
        liveBody.addView(infoRow("WiFi", valueText(Prefs.wifiSsid(this).ifBlank { "없음" })))
        liveBody.addView(divider())
        liveBody.addView(infoRow("블루투스", valueText(Prefs.btConnected(this).ifBlank { "없음" })))
        liveBody.addView(divider())
        liveBody.addView(infoRow("장소", valueText(Prefs.visitPlace(this).ifBlank { "이동 중" })))

        deviceLabel.text = "기기 ${Prefs.deviceId(this)}"
    }

    // ── 행 헬퍼 ──
    private fun infoRow(label: String, value: View): LinearLayout =
        LinearLayout(this).apply {
            layoutParams = rowParams()
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(9), 0, dp(9))
            addView(tv(label, 14f, cText), LinearLayout.LayoutParams(0, wrap, 1f))
            addView(value)
        }

    private fun permRow(label: String, granted: Boolean, onFix: () -> Unit): LinearLayout =
        LinearLayout(this).apply {
            layoutParams = rowParams()
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(9), 0, dp(9))
            addView(View(this@MainActivity).apply { background = oval(if (granted) cGreen else cAmber) },
                LinearLayout.LayoutParams(dp(8), dp(8)).apply { rightMargin = dp(10) })
            addView(tv(label, 14f, cText), LinearLayout.LayoutParams(0, wrap, 1f))
            if (granted) addView(tv("허용됨", 13f, cGreen)) else addView(chipBtn("설정", onFix))
        }

    // ── 빌딩블록 ──
    private fun tv(text: String, sizeSp: Float, color: Int, bold: Boolean = false): TextView =
        TextView(this).apply {
            this.text = text; textSize = sizeSp; setTextColor(color)
            if (bold) typeface = Typeface.create(typeface, Typeface.BOLD)
        }

    private fun valueText(v: String): TextView = tv(v, 13f, cMuted)

    private fun pillView(text: String, fg: Int, bg: Int): TextView =
        tv(text, 12f, fg).apply { setPadding(dp(10), dp(3), dp(10), dp(3)); background = pillBg(bg) }

    private fun chip(text: String): TextView =
        tv(text, 12f, cInfo).apply {
            setPadding(dp(11), dp(5), dp(11), dp(5)); background = pillBg(cInfoBg)
            layoutParams = LinearLayout.LayoutParams(wrap, wrap).apply { rightMargin = dp(6) }
        }

    private fun card(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        background = GradientDrawable().apply {
            setColor(cCard); cornerRadius = dp(14).toFloat(); setStroke(maxOf(1, dp(1)), cBorder)
        }
        setPadding(dp(16), dp(14), dp(16), dp(14))
    }

    private fun addCard(parent: LinearLayout, c: View) {
        parent.addView(c, LinearLayout.LayoutParams(match, wrap).apply { bottomMargin = dp(10) })
    }

    /// 미니 통계 박스(라벨+값). 값 TextView에 tag="v"로 찾아 갱신.
    private fun stat(label: String, value: String): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        background = GradientDrawable().apply { setColor(cChipBg); cornerRadius = dp(8).toFloat() }
        setPadding(dp(12), dp(8), dp(12), dp(8))
        addView(tv(label, 12f, cMuted))
        addView(tv(value, 18f, cText, bold = true).apply { tag = "v" })
    }

    private fun divider(): View = View(this).apply {
        layoutParams = LinearLayout.LayoutParams(match, maxOf(1, (0.5f * density).toInt()))
        setBackgroundColor(cBorder)
    }

    private fun primaryBtn(text: String, onClick: () -> Unit): Button = Button(this).apply {
        this.text = text; textSize = 15f; setTextColor(0xFFFFFFFF.toInt()); isAllCaps = false
        background = GradientDrawable().apply { setColor(cText); cornerRadius = dp(10).toFloat() }
        setPadding(0, dp(12), 0, dp(12))
        setOnClickListener { onClick() }
        layoutParams = LinearLayout.LayoutParams(match, wrap)
    }

    private fun smallBtn(text: String, onClick: () -> Unit): Button = Button(this).apply {
        this.text = text; textSize = 13f; setTextColor(cText); isAllCaps = false
        background = strokeBg()
        setPadding(dp(14), dp(9), dp(14), dp(9))
        setOnClickListener { onClick() }
        layoutParams = LinearLayout.LayoutParams(0, wrap, 1f)
    }

    private fun chipBtn(text: String, onClick: () -> Unit): Button = Button(this).apply {
        this.text = text; textSize = 12f; setTextColor(cAmber); isAllCaps = false
        background = GradientDrawable().apply { setColor(cAmberBg); cornerRadius = dp(8).toFloat() }
        minWidth = 0; minHeight = 0
        setPadding(dp(12), dp(5), dp(12), dp(5))
        setOnClickListener { onClick() }
    }

    private fun strokeBg() = GradientDrawable().apply {
        setColor(cCard); cornerRadius = dp(8).toFloat(); setStroke(maxOf(1, dp(1)), cBorder)
    }

    private fun pillBg(color: Int) = GradientDrawable().apply {
        setColor(color); cornerRadius = dp(999).toFloat()
    }

    private fun oval(color: Int) = GradientDrawable().apply {
        shape = GradientDrawable.OVAL; setColor(color)
    }

    // ── 권한 점검 ──
    private fun smsCallsGranted(): Boolean =
        checkSelfPermission(Manifest.permission.READ_SMS) == PackageManager.PERMISSION_GRANTED &&
            checkSelfPermission(Manifest.permission.READ_CALL_LOG) == PackageManager.PERMISSION_GRANTED

    private fun locationAlwaysGranted(): Boolean {
        val fine = checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
        return if (Build.VERSION.SDK_INT >= 29)
            fine && checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION) ==
                PackageManager.PERMISSION_GRANTED
        else fine
    }

    private fun notifAccessGranted(): Boolean {
        val flat = Settings.Secure.getString(contentResolver, "enabled_notification_listeners") ?: ""
        return flat.contains(packageName)
    }

    private fun batteryExempt(): Boolean {
        val pm = getSystemService(POWER_SERVICE) as? PowerManager ?: return true
        return pm.isIgnoringBatteryOptimizations(packageName)
    }

    private fun requestPerms() {
        val perms = mutableListOf(
            Manifest.permission.READ_SMS,
            Manifest.permission.READ_CALL_LOG,
            Manifest.permission.ACCESS_FINE_LOCATION)
        if (Build.VERSION.SDK_INT >= 33) perms.add(Manifest.permission.POST_NOTIFICATIONS)
        if (Build.VERSION.SDK_INT >= 31) perms.add(Manifest.permission.BLUETOOTH_CONNECT)
        if (Build.VERSION.SDK_INT >= 29) perms.add(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
        requestPermissions(perms.toTypedArray(), 1)
    }

    override fun onRequestPermissionsResult(
        requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        refresh()
    }

    // ── 보조 ──
    private fun showLogs() {
        val logs = try { L.snapshot().joinToString("\n") } catch (_: Exception) { "" }
        AlertDialog.Builder(this)
            .setTitle("최근 로그")
            .setMessage(if (logs.isBlank()) "아직 로그 없음" else logs)
            .setPositiveButton("닫기", null)
            .show()
    }

    private fun openSetting(action: String) = safeStart(Intent(action))
    private fun openAppDetails() = safeStart(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
        android.net.Uri.parse("package:$packageName")))

    private fun safeStart(i: Intent) {
        try { startActivity(i) } catch (_: Exception) { toast("열 수 없음") }
    }

    private fun toast(m: String) = Toast.makeText(this, m, Toast.LENGTH_SHORT).show()

    private fun agoStr(ms: Long): String {
        val m = ms / 60_000
        return when {
            m < 1 -> "방금"
            m < 60 -> "${m}분"
            m < 1440 -> "${m / 60}시간"
            else -> "${m / 1440}일"
        }
    }
}

package studio.camembertcheese.oracle.collector

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

/// 앱 푸시 알림 수집 — 시스템 바인드 서비스(알림 접근 권한). 의미 있는 것만 버퍼에 적재.
/// 포그라운드 서비스와 독립적으로 상시 동작(권한만 있으면). 동기화 때 버퍼를 비워 전송.
class NotificationCollector : NotificationListenerService() {

    private val blocklist = listOf(
        "studio.camembertcheese.oracle.collector",
        "studio.camembertcheese.oracle",
        "android", "com.android.systemui",
        "com.samsung.android.", "com.google.android.gms",
        "com.google.android.apps.nexuslauncher", "com.sec.android.app.launcher"
    )

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        sbn ?: return
        try {
            val pkg = sbn.packageName ?: ""
            if (blocklist.any { pkg.startsWith(it) }) return
            if (sbn.isOngoing) return   // 음악·진행중 알림 제외(노이즈)
            val ex = sbn.notification?.extras ?: return
            val title = ex.getCharSequence(Notification.EXTRA_TITLE)?.toString()?.trim() ?: ""
            val text = ex.getCharSequence(Notification.EXTRA_TEXT)?.toString()?.trim() ?: ""
            // 펼친 본문(BIG_TEXT)이 더 길면 그걸 쓴다 — 현대카드 등은 가맹점·누적이 접힌 한 줄
            // (EXTRA_TEXT)엔 없고 펼친 여러 줄(BIG_TEXT)에만 온다(가맹점 통째 누락 방지).
            val big = ex.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()?.trim() ?: ""
            val body = if (big.length > text.length) big else text
            if (title.isEmpty() && body.isEmpty()) return
            Prefs.addNotif(applicationContext, pkg, title, body, sbn.postTime)
        } catch (_: Exception) {
        }
    }
}

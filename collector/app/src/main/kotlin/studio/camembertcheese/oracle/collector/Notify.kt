package studio.camembertcheese.oracle.collector

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import org.json.JSONObject

/// 동반자(도착/이탈) 말 걸기 알림. 탭하면 **Flutter 앱(능동 인터페이스)의 기록 탭**으로 —
/// ask payload를 인텐트 extra로 넘겨 거기서 답하게(req1 흐름 보존). 수집기 자신은 열지 않는다.
object Notify {

    private const val FLUTTER_PKG = "studio.camembertcheese.oracle"
    private const val FLUTTER_ACT = "studio.camembertcheese.oracle.MainActivity"

    fun companion(ctx: Context, speaker: String, text: String) {
        if (text.isBlank()) return
        val mgr = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val chId = "companion"
        mgr.createNotificationChannel(
            NotificationChannel(chId, "동반자", NotificationManager.IMPORTANCE_DEFAULT))

        val ask = JSONObject().put("s", speaker).put("t", text).toString()
        val launch = Intent(Intent.ACTION_MAIN).apply {
            setClassName(FLUTTER_PKG, FLUTTER_ACT)
            putExtra("oracle_ask", ask)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        }
        val pi = PendingIntent.getActivity(
            ctx, 0, launch,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

        val icon = when (speaker) { "쿠키" -> "🐦"; "베르" -> "🐶"; else -> "🐾" }
        val n = Notification.Builder(ctx, chId)
            .setContentTitle("$icon ${if (speaker.isBlank()) "동반자" else speaker}")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_notify_chat)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setContentIntent(pi)
            .setAutoCancel(true)
            .build()
        mgr.notify(3200, n)
    }
}

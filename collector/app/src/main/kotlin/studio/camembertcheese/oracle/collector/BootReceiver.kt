package studio.camembertcheese.oracle.collector

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/// 부팅 완료 시 수집 서비스 자동 시작.
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            try { CollectorService.start(ctx) } catch (_: Exception) {}
        }
    }
}

package studio.camembertcheese.oracle.collector

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/// 부팅 완료 + 앱 업데이트(패키지 교체) 시 수집 서비스 자동 시작.
/// (MY_PACKAGE_REPLACED는 백그라운드 FGS 시작 제한에 걸릴 수 있어 best-effort — 막히면 앱 1회 실행 필요)
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        when (intent.action) {
            Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_MY_PACKAGE_REPLACED ->
                try { CollectorService.start(ctx) } catch (_: Exception) {}
        }
    }
}

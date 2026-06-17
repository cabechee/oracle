package studio.camembertcheese.oracle

import android.content.Intent
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

/// 수집기(별도 앱)가 띄운 동반자 알림을 탭하면 이 앱이 ask payload(extra "oracle_ask")와 함께
/// 열린다. Dart가 `oracle/launch` 채널의 consumeAsk로 가져가 기록 탭으로 라우팅(req1).
class MainActivity : FlutterActivity() {
    private val channel = "oracle/launch"
    private var pendingAsk: String? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channel)
            .setMethodCallHandler { call, result ->
                if (call.method == "consumeAsk") {
                    val ask = pendingAsk ?: intent?.getStringExtra("oracle_ask")
                    pendingAsk = null
                    intent?.removeExtra("oracle_ask")
                    result.success(ask)
                } else {
                    result.notImplemented()
                }
            }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        pendingAsk = intent.getStringExtra("oracle_ask")
    }
}

package studio.camembertcheese.oracle.collector

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import kotlin.concurrent.thread

/// 갤러리 등에서 '공유하기'로 영수증 이미지/PDF를 수집기에 넣으면 → 가계부 드롭존(/ledger/receipt)과 동일 처리.
/// (Oracle 본앱 공유는 '기록'으로, 수집기 공유는 '영수증 처리'로 — 역할 분리.)
class ShareActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val uris = ArrayList<Uri>()
        when (intent?.action) {
            Intent.ACTION_SEND ->
                (intent.getParcelableExtra(Intent.EXTRA_STREAM) as? Uri)?.let { uris.add(it) }
            Intent.ACTION_SEND_MULTIPLE ->
                intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)?.let { uris.addAll(it) }
        }
        if (uris.isEmpty()) {
            Toast.makeText(this, "공유된 이미지가 없어요", Toast.LENGTH_SHORT).show()
            finish(); return
        }
        Toast.makeText(this, "영수증 ${uris.size}건 처리 중…", Toast.LENGTH_SHORT).show()
        val app = applicationContext
        thread {
            var ok = 0
            for (u in uris) {
                try {
                    val bytes = contentResolver.openInputStream(u)?.use { it.readBytes() } ?: continue
                    val name = (u.lastPathSegment ?: "receipt").substringAfterLast('/')
                    val r = Backend.uploadReceipt(app, bytes, if (name.contains('.')) name else "$name.jpg")
                    if (r != null && r.optBoolean("ok")) ok++
                } catch (e: Exception) {
                    // 무시 — 다음 파일로
                }
            }
            runOnUiThread {
                Toast.makeText(app,
                    if (ok > 0) "영수증 ${ok}건 가계부에 처리됐어요" else "처리 실패 — 영수증을 못 읽었어요",
                    Toast.LENGTH_LONG).show()
                finish()
            }
        }
    }
}

package studio.camembertcheese.oracle.collector

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import kotlin.concurrent.thread

/// 갤러리 등에서 '공유하기'로 이미지/PDF를 수집기에 넣으면 → 분류기(/share/image)가
/// 영수증/일정/기록으로 판별해 각각 가계부·캘린더·흐름으로 라우팅한다.
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
        Toast.makeText(this, "${uris.size}건 분류 처리 중…", Toast.LENGTH_SHORT).show()
        val app = applicationContext
        thread {
            val counts = HashMap<String, Int>()   // kind(receipt|calendar|note) → 건수
            for (u in uris) {
                try {
                    val bytes = contentResolver.openInputStream(u)?.use { it.readBytes() } ?: continue
                    val name = (u.lastPathSegment ?: "img").substringAfterLast('/')
                    val r = Backend.uploadShare(app, bytes, if (name.contains('.')) name else "$name.jpg")
                    if (r != null && r.optBoolean("ok")) {
                        val k = r.optString("kind", "note")
                        counts[k] = (counts[k] ?: 0) + 1
                    }
                } catch (e: Exception) {
                    // 무시 — 다음 파일로
                }
            }
            val label = mapOf("receipt" to "영수증", "calendar" to "일정", "note" to "기록")
            runOnUiThread {
                val msg = if (counts.isEmpty()) "처리 실패 — 다시 시도해주세요"
                          else counts.entries.joinToString(" · ") {
                              "${label[it.key] ?: it.key} ${it.value}건"
                          } + " 처리됐어요"
                Toast.makeText(app, msg, Toast.LENGTH_LONG).show()
                finish()
            }
        }
    }
}

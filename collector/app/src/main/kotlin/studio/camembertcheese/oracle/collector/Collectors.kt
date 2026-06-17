package studio.camembertcheese.oracle.collector

import android.content.Context
import android.provider.CallLog
import android.provider.Telephony
import org.json.JSONArray
import org.json.JSONObject

/// 단말 데이터 수집 — 미읽음 SMS · 부재중 통화. 권한 없으면 빈 배열(graceful).
/// 백엔드 /signals/sync 페이로드 형태({from, body, ts} / {from, ts})로 맞춘다.
object Collectors {

    fun unreadSms(ctx: Context, limit: Int = 50): JSONArray {
        val out = JSONArray()
        try {
            ctx.contentResolver.query(
                Telephony.Sms.Inbox.CONTENT_URI,
                arrayOf(Telephony.Sms.ADDRESS, Telephony.Sms.BODY, Telephony.Sms.DATE),
                "${Telephony.Sms.READ} = 0", null,
                "${Telephony.Sms.DATE} DESC"
            )?.use { c ->
                val ai = c.getColumnIndex(Telephony.Sms.ADDRESS)
                val bi = c.getColumnIndex(Telephony.Sms.BODY)
                val di = c.getColumnIndex(Telephony.Sms.DATE)
                var n = 0
                while (c.moveToNext() && n < limit) {
                    out.put(JSONObject()
                        .put("from", if (ai >= 0) c.getString(ai) ?: "" else "")
                        .put("body", if (bi >= 0) c.getString(bi) ?: "" else "")
                        .put("ts", if (di >= 0) c.getLong(di) else System.currentTimeMillis()))
                    n++
                }
            }
        } catch (_: Exception) {
        }
        return out
    }

    fun missedCalls(ctx: Context, sinceMs: Long, limit: Int = 20): JSONArray {
        val out = JSONArray()
        try {
            ctx.contentResolver.query(
                CallLog.Calls.CONTENT_URI,
                arrayOf(CallLog.Calls.NUMBER, CallLog.Calls.CACHED_NAME, CallLog.Calls.DATE),
                "${CallLog.Calls.TYPE} = ? AND ${CallLog.Calls.DATE} > ?",
                arrayOf(CallLog.Calls.MISSED_TYPE.toString(), sinceMs.toString()),
                "${CallLog.Calls.DATE} DESC"
            )?.use { c ->
                val ni = c.getColumnIndex(CallLog.Calls.NUMBER)
                val ci = c.getColumnIndex(CallLog.Calls.CACHED_NAME)
                val di = c.getColumnIndex(CallLog.Calls.DATE)
                var n = 0
                while (c.moveToNext() && n < limit) {
                    val name = if (ci >= 0) c.getString(ci) else null
                    val num = if (ni >= 0) c.getString(ni) else null
                    out.put(JSONObject()
                        .put("from", if (!name.isNullOrEmpty()) name else (num ?: ""))
                        .put("ts", if (di >= 0) c.getLong(di) else System.currentTimeMillis()))
                    n++
                }
            }
        } catch (_: Exception) {
        }
        return out
    }
}

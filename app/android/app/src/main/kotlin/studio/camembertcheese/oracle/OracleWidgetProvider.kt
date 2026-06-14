package studio.camembertcheese.oracle

import android.appwidget.AppWidgetManager
import android.content.Context
import android.content.SharedPreferences
import android.widget.RemoteViews
import es.antonborri.home_widget.HomeWidgetLaunchIntent
import es.antonborri.home_widget.HomeWidgetProvider

/// Oracle 홈 위젯 — 위 절반 알림, 아래 절반 리마인더 (4x4).
/// Flutter가 HomeWidget.saveWidgetData로 넣은 'notif_text'·'reminder_text'를 그린다.
class OracleWidgetProvider : HomeWidgetProvider() {

    override fun onUpdate(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetIds: IntArray,
        widgetData: SharedPreferences,
    ) {
        appWidgetIds.forEach { widgetId ->
            val views = RemoteViews(context.packageName, R.layout.oracle_widget_layout).apply {
                // 위젯 전체 탭 → 앱 열기
                val launchIntent = HomeWidgetLaunchIntent.getActivity(
                    context,
                    MainActivity::class.java,
                )
                setOnClickPendingIntent(R.id.widget_root, launchIntent)

                setTextViewText(
                    R.id.notif_text,
                    widgetData.getString("notif_text", null) ?: "아직 받은 알림이 없어요",
                )
                setTextViewText(
                    R.id.reminder_text,
                    widgetData.getString("reminder_text", null) ?: "리마인더가 비어 있어요",
                )
            }
            appWidgetManager.updateAppWidget(widgetId, views)
        }
    }
}

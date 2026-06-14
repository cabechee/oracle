import 'package:home_widget/home_widget.dart';

import 'api.dart';

const _widgetName = 'studio.camembertcheese.oracle.OracleWidgetProvider';

/// 홈 위젯(4x4) 갱신 — 위=알림 요약, 아래=리마인더.
Future<void> updateOracleWidget(
    {required String notifText, required String reminderText}) async {
  try {
    await HomeWidget.saveWidgetData<String>('notif_text', notifText);
    await HomeWidget.saveWidgetData<String>('reminder_text', reminderText);
    await HomeWidget.updateWidget(qualifiedAndroidName: _widgetName);
  } catch (_) {
    // 위젯 미설치·플랫폼 미지원 등 — 조용히 무시
  }
}

/// dashboard feed 응답 → (알림 텍스트, 리마인더 텍스트).
(String, String) widgetTextsFromDashboard(Map<String, dynamic> d) {
  final digest = d['digest'] as Map<String, dynamic>?;
  final groups =
      (digest?['groups'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
  final totals = digest?['totals'] as Map<String, dynamic>? ?? const {};
  const labels = {
    'attention': '관심', 'acquaintance': '지인', 'low': '일반', 'spam': '스팸',
  };
  final lines = <String>[];
  final tparts = <String>[];
  labels.forEach((k, v) {
    final n = (totals[k] as num?)?.toInt() ?? 0;
    if (n > 0) tparts.add('$v $n');
  });
  if (tparts.isNotEmpty) lines.add(tparts.join(' · '));
  for (final g in groups.take(4)) {
    lines.add('${g['sender']} ${(g['count'] as num?)?.toInt() ?? 0}건');
  }
  final notifText = lines.isEmpty ? '아직 받은 알림이 없어요' : lines.join('\n');

  final rems =
      (d['reminders'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
  final active = rems.where((r) => r['done'] != true).toList();
  final remText = active.isEmpty
      ? '리마인더가 비어 있어요'
      : active.take(5).map((r) => '· ${r['text']}').join('\n');
  return (notifText, remText);
}

/// API에서 받아 위젯 갱신 (백그라운드 sync·앱 복귀 시).
Future<void> refreshWidget(OracleApi api) async {
  try {
    final d = await api.fetchDashboard();
    final (n, r) = widgetTextsFromDashboard(d);
    await updateOracleWidget(notifText: n, reminderText: r);
  } catch (_) {}
}

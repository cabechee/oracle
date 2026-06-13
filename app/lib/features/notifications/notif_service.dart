import 'package:flutter_local_notifications/flutter_local_notifications.dart';

/// 로컬 푸시 알림 — init + 새 다이제스트 알림. (FCM 아님, 앱 실행 중 한정)
class NotifService {
  final FlutterLocalNotificationsPlugin _plugin =
      FlutterLocalNotificationsPlugin();

  /// [onTap]: 알림 탭 시 payload(다이제스트 날짜)와 함께 호출 — "탭해서 보기" 동작.
  Future<void> init({void Function(String? payload)? onTap}) async {
    try {
      const init = InitializationSettings(
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
      );
      await _plugin.initialize(
        init,
        onDidReceiveNotificationResponse: (r) => onTap?.call(r.payload),
      );
      // Android 13+ 권한 요청 (없으면 silent)
      await _plugin
          .resolvePlatformSpecificImplementation<
              AndroidFlutterLocalNotificationsPlugin>()
          ?.requestNotificationsPermission();
    } catch (_) {}
  }

  Future<void> notifyNewDigest(String date) async {
    try {
      const details = NotificationDetails(
        android: AndroidNotificationDetails(
          'oracle_digest',
          '다이제스트',
          channelDescription: '자정 다이제스트 도착 알림',
          importance: Importance.high,
          priority: Priority.high,
        ),
      );
      await _plugin.show(0, '📓 새 다이제스트', '$date — 탭해서 보기', details,
          payload: date);
    } catch (_) {}
  }
}

import 'package:flutter_foreground_task/flutter_foreground_task.dart';

import 'location_task_handler.dart';

/// 위치 포그라운드 서비스 제어 — init/start/stop.
class LocationService {
  static void init() {
    FlutterForegroundTask.init(
      androidNotificationOptions: AndroidNotificationOptions(
        channelId: 'oracle_location',
        channelName: '위치 감지',
        channelDescription: 'Oracle이 집·작업실 도착/이탈을 감지합니다.',
        onlyAlertOnce: true,
      ),
      iosNotificationOptions: const IOSNotificationOptions(),
      foregroundTaskOptions: ForegroundTaskOptions(
        eventAction: ForegroundTaskEventAction.repeat(60000), // 1분
        autoRunOnBoot: true,
        autoRunOnMyPackageReplaced: true,
        allowWakeLock: true,
        allowWifiLock: false,
      ),
    );
  }

  static Future<bool> isRunning() => FlutterForegroundTask.isRunningService;

  static Future<ServiceRequestResult> start() async {
    if (await FlutterForegroundTask.isRunningService) {
      return FlutterForegroundTask.restartService();
    }
    return FlutterForegroundTask.startService(
      serviceId: 3100,
      notificationTitle: 'Oracle 위치 감지 중',
      notificationText: '집·작업실 도착/이탈을 살펴요',
      serviceTypes: [ForegroundServiceTypes.location],
      callback: startLocationCallback,
    );
  }

  static Future<ServiceRequestResult> stop() =>
      FlutterForegroundTask.stopService();
}

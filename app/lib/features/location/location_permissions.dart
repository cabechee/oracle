import 'package:permission_handler/permission_handler.dart';

/// 위치 권한 3단계 — whileInUse → always(별도 요청) → 알림.
/// Android 10+는 '항상 허용'을 whileInUse 이후 별도 단계로만 받을 수 있다.
Future<bool> requestLocationPermissions() async {
  final whenInUse = await Permission.locationWhenInUse.request();
  if (!whenInUse.isGranted) return false;
  final always = await Permission.locationAlways.request();
  await Permission.notification.request();
  // 차 BT 등 연결 감지 — 있으면 (없거나 거부해도 위치는 정상). Android 12+ 런타임 권한.
  try {
    await Permission.bluetoothConnect.request();
  } catch (_) {}
  return always.isGranted;
}

import 'package:permission_handler/permission_handler.dart';

/// 위치 권한 3단계 — whileInUse → always(별도 요청) → 알림.
/// Android 10+는 '항상 허용'을 whileInUse 이후 별도 단계로만 받을 수 있다.
Future<bool> requestLocationPermissions() async {
  final whenInUse = await Permission.locationWhenInUse.request();
  if (!whenInUse.isGranted) return false;
  final always = await Permission.locationAlways.request();
  await Permission.notification.request();
  return always.isGranted;
}

/// 위치 추적 백그라운드 — 1분 폴링 포그라운드 서비스의 TaskHandler.
///
/// 집/작업실 도착·이탈·평소위치 500m 이탈을 폰에서 판정 → 백엔드 /companion/say
/// (쿠키/베르 한마디) → 로컬 알림. 별도 isolate라 OracleApi 대신 http 직접 사용.
library;

import 'dart:convert';

import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

const kHomeLat = 'loc_home_lat';
const kHomeLng = 'loc_home_lng';
const kOfficeLat = 'loc_office_lat';
const kOfficeLng = 'loc_office_lng';
const _kLastPlace = 'loc_last_place';
const _kWasFar = 'loc_was_far';

const _baseUrl = String.fromEnvironment('ORACLE_API',
    defaultValue: 'http://chocolat.tail575fea.ts.net:8001');
const _arriveRadius = 120.0; // 도착 판정 반경(m)
const _deviateRadius = 500.0; // 평소 위치 이탈 판정(m)

@pragma('vm:entry-point')
void startLocationCallback() {
  FlutterForegroundTask.setTaskHandler(LocationTaskHandler());
}

class LocationTaskHandler extends TaskHandler {
  @override
  Future<void> onStart(DateTime timestamp, TaskStarter starter) async {
    await _tick();
  }

  @override
  void onRepeatEvent(DateTime timestamp) {
    _tick(); // void — async는 fire-and-forget
  }

  @override
  Future<void> onDestroy(DateTime timestamp, bool isTimeout) async {}

  Future<void> _tick() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final pos = await Geolocator.getCurrentPosition(
        locationSettings:
            const LocationSettings(accuracy: LocationAccuracy.high),
      );
      final lat = pos.latitude, lng = pos.longitude;

      final homeLat = prefs.getDouble(kHomeLat), homeLng = prefs.getDouble(kHomeLng);
      final officeLat = prefs.getDouble(kOfficeLat),
          officeLng = prefs.getDouble(kOfficeLng);
      final lastPlace = prefs.getString(_kLastPlace) ?? 'unknown';

      // 집/작업실까지 거리 (저장된 것만)
      double? dHome, dOffice;
      if (homeLat != null && homeLng != null) {
        dHome = Geolocator.distanceBetween(lat, lng, homeLat, homeLng);
      }
      if (officeLat != null && officeLng != null) {
        dOffice = Geolocator.distanceBetween(lat, lng, officeLat, officeLng);
      }

      // 현재 장소 — 집/작업실 반경 안이면 그곳, 아니면 away
      String place = 'away';
      if (dHome != null && dHome <= _arriveRadius) {
        place = 'home';
      } else if (dOffice != null && dOffice <= _arriveRadius) {
        place = 'office';
      }

      // 평소 위치(집·작업실)에서 멀리(500m+)인가 — 직전 위치가 아니라 '집/작업실' 기준.
      // 이동 중에도 직전 위치선 500m가 쉽게 넘어가 반복되던 버그를 이 기준으로 차단.
      final hasPlace = dHome != null || dOffice != null;
      double minDist = double.infinity;
      if (dHome != null && dHome < minDist) minDist = dHome;
      if (dOffice != null && dOffice < minDist) minDist = dOffice;
      final far = hasPlace && minDist > _deviateRadius;
      final wasFar = prefs.getBool(_kWasFar) ?? false;
      await prefs.setBool(_kWasFar, far);

      String? event;
      if (place != lastPlace) {
        if (place == 'home') {
          event = 'arrive_home';
        } else if (place == 'office') {
          event = 'arrive_office';
        } else if (lastPlace == 'home') {
          event = 'leave_home';
        } else if (lastPlace == 'office') {
          event = 'leave_office';
        }
        await prefs.setString(_kLastPlace, place);
      }
      // 집/작업실에서 '막' 500m 벗어나는 순간 한 번만 — 이미 멀면(far→far) 다시 안 물어봄.
      if (event == null && far && !wasFar) {
        event = 'deviate';
      }

      if (event != null) {
        await _sayAndNotify(event, place);
      }
    } catch (_) {
      // isolate 예외 삼킴 — 서비스 유지
    }
  }

  Future<void> _sayAndNotify(String event, String place) async {
    try {
      final resp = await http
          .post(Uri.parse('$_baseUrl/companion/say'),
              headers: {'Content-Type': 'application/json'},
              body: jsonEncode({'event': event, 'place': place}))
          .timeout(const Duration(seconds: 20));
      if (resp.statusCode != 200) return;
      final data = jsonDecode(resp.body) as Map<String, dynamic>;
      final text = (data['text'] as String? ?? '').trim();
      if (text.isEmpty) return;
      await _notify((data['speaker'] as String?) ?? '', text);
    } catch (_) {}
  }

  Future<void> _notify(String speaker, String text) async {
    final plugin = FlutterLocalNotificationsPlugin();
    await plugin.initialize(const InitializationSettings(
      android: AndroidInitializationSettings('@mipmap/ic_launcher'),
    ));
    final icon = speaker == '쿠키' ? '🐦' : (speaker == '베르' ? '🐶' : '🐾');
    final largeIcon = speaker == '베르'
        ? const DrawableResourceAndroidBitmap('bert')
        : null;
    await plugin.show(3100, '$icon ${speaker.isEmpty ? '동반자' : speaker}', text,
        NotificationDetails(
          android: AndroidNotificationDetails('companion', '동반자',
              channelDescription: '쿠키·베르의 말 걸기',
              importance: Importance.defaultImportance,
              largeIcon: largeIcon,
              styleInformation: const BigTextStyleInformation('')),
        ));
  }
}

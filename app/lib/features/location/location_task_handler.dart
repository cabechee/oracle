/// 위치 추적 백그라운드 — 체류(stay) 감지 포그라운드 서비스의 TaskHandler.
///
/// 1분 폴링하되 '한 곳에 머무름(체류)'을 감지한다:
/// - 집/작업실 반경 진입 → 즉시 방문 시작(도착 인사)
/// - 새 장소에 15분+ 머묾 → 방문 시작("여기 뭐 해?")
/// - 머물던 anchor를 벗어남 → 방문 종료(체류 시간 기록 + "한동안 있다 가네")
/// 배터리: 체류 확정 중엔 GPS를 2틱(2분)마다만(이탈 감지 약간 지연 허용).
/// 별도 isolate라 OracleApi 대신 http 직접. 의미 있는 '방문 이벤트'만 서버로.
library;

import 'dart:convert';

import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:network_info_plus/network_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';

const kHomeLat = 'loc_home_lat';
const kHomeLng = 'loc_home_lng';
const kOfficeLat = 'loc_office_lat';
const kOfficeLng = 'loc_office_lng';
const kHomeWifi = 'loc_home_wifi';     // 집 WiFi 이름(SSID) — 붙어 있으면 GPS 없이 집
const kOfficeWifi = 'loc_office_wifi';

// 체류 상태 (anchor = 지금 머무는 후보 중심)
const _kAnchorLat = 'visit_anchor_lat';
const _kAnchorLng = 'visit_anchor_lng';
const _kAnchorStart = 'visit_anchor_start'; // epoch ms
const _kVisitOn = 'visit_on';               // 체류 확정 여부
const _kVisitPlace = 'visit_place';         // 'home'|'office'|''(새 장소)
const _kTick = 'visit_tick';

const _baseUrl = String.fromEnvironment('ORACLE_API',
    defaultValue: 'http://chocolat.tail575fea.ts.net:8001');
const _arriveRadius = 120.0; // 집/작업실 도착 반경(m)
const _stayRadius = 150.0;   // 같은 곳 '머무름' 판정 반경(m)
const _stayMinutes = 15;     // 새 장소 체류 확정 시간(분)

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
      final tick = (prefs.getInt(_kTick) ?? 0) + 1;
      await prefs.setInt(_kTick, tick);
      final now = DateTime.now().millisecondsSinceEpoch;

      // 1) WiFi 우선 — 저장된 집/작업실 WiFi에 붙어 있으면 GPS 없이 즉시 그 장소.
      final wifiPlace = await _wifiPlace(prefs);
      if (wifiPlace != null) {
        await _onWifiPlace(prefs, wifiPlace, now);
        return; // GPS 안 켬 (배터리 절감)
      }

      // 2) WiFi 안 맞음 → GPS (체류 확정 중엔 2틱=2분마다만)
      final visitOn = prefs.getBool(_kVisitOn) ?? false;
      if (visitOn && tick % 2 != 0) return;

      final pos = await Geolocator.getCurrentPosition(
        locationSettings:
            const LocationSettings(accuracy: LocationAccuracy.high),
      );
      final lat = pos.latitude, lng = pos.longitude;

      final homeLat = prefs.getDouble(kHomeLat), homeLng = prefs.getDouble(kHomeLng);
      final officeLat = prefs.getDouble(kOfficeLat),
          officeLng = prefs.getDouble(kOfficeLng);
      String? place;
      if (homeLat != null &&
          homeLng != null &&
          Geolocator.distanceBetween(lat, lng, homeLat, homeLng) <=
              _arriveRadius) {
        place = 'home';
      } else if (officeLat != null &&
          officeLng != null &&
          Geolocator.distanceBetween(lat, lng, officeLat, officeLng) <=
              _arriveRadius) {
        place = 'office';
      }

      final anchorLat = prefs.getDouble(_kAnchorLat),
          anchorLng = prefs.getDouble(_kAnchorLng);
      if (anchorLat == null || anchorLng == null) {
        await _setAnchor(prefs, lat, lng, now); // 첫 위치
        return;
      }
      final fromAnchor =
          Geolocator.distanceBetween(lat, lng, anchorLat, anchorLng);

      if (fromAnchor <= _stayRadius) {
        if (visitOn) return; // 이미 체류 확정 — 조용
        final start = prefs.getInt(_kAnchorStart) ?? now;
        final stayedMin = (now - start) ~/ 60000;
        if (place != null || stayedMin >= _stayMinutes) {
          await prefs.setBool(_kVisitOn, true);
          await prefs.setString(_kVisitPlace, place ?? '');
          final event = place == 'home'
              ? 'arrive_home'
              : place == 'office'
                  ? 'arrive_office'
                  : 'arrive_place';
          await _say(event, place);
        }
      } else {
        if (visitOn) {
          final start = prefs.getInt(_kAnchorStart) ?? now;
          final minutes = (now - start) ~/ 60000;
          final vplace = prefs.getString(_kVisitPlace) ?? '';
          await _endVisit(anchorLat, anchorLng,
              vplace.isEmpty ? null : vplace, start, now, minutes);
        }
        await _setAnchor(prefs, lat, lng, now); // 새 anchor에서 다시 시작
      }
    } catch (_) {
      // isolate 예외 삼킴 — 서비스 유지
    }
  }

  /// 저장된 집/작업실 WiFi에 붙어 있으면 그 장소, 아니면 null.
  Future<String?> _wifiPlace(SharedPreferences prefs) async {
    try {
      final raw = await NetworkInfo().getWifiName();
      if (raw == null) return null;
      final ssid = raw.replaceAll('"', '').trim();
      if (ssid.isEmpty || ssid == '<unknown ssid>') return null;
      if (ssid == prefs.getString(kHomeWifi)) return 'home';
      if (ssid == prefs.getString(kOfficeWifi)) return 'office';
    } catch (_) {}
    return null;
  }

  /// WiFi로 확정된 집/작업실 — GPS·anchor 무관 즉시 도착/유지. (다른 곳서 왔으면 이전 방문 종료)
  Future<void> _onWifiPlace(
      SharedPreferences prefs, String place, int now) async {
    final visitOn = prefs.getBool(_kVisitOn) ?? false;
    final lastPlace = prefs.getString(_kVisitPlace) ?? '';
    if (visitOn && lastPlace == place) return; // 이미 그곳 체류 중

    if (visitOn) {
      final start = prefs.getInt(_kAnchorStart) ?? now;
      final minutes = (now - start) ~/ 60000;
      final aLat = prefs.getDouble(_kAnchorLat) ?? 0;
      final aLng = prefs.getDouble(_kAnchorLng) ?? 0;
      await _endVisit(aLat, aLng, lastPlace.isEmpty ? null : lastPlace,
          start, now, minutes);
    }
    final pLat = prefs.getDouble(place == 'home' ? kHomeLat : kOfficeLat) ?? 0;
    final pLng = prefs.getDouble(place == 'home' ? kHomeLng : kOfficeLng) ?? 0;
    await prefs.setDouble(_kAnchorLat, pLat);
    await prefs.setDouble(_kAnchorLng, pLng);
    await prefs.setInt(_kAnchorStart, now);
    await prefs.setBool(_kVisitOn, true);
    await prefs.setString(_kVisitPlace, place);
    await _say(place == 'home' ? 'arrive_home' : 'arrive_office', place);
  }

  Future<void> _setAnchor(
      SharedPreferences prefs, double lat, double lng, int now) async {
    await prefs.setDouble(_kAnchorLat, lat);
    await prefs.setDouble(_kAnchorLng, lng);
    await prefs.setInt(_kAnchorStart, now);
    await prefs.setBool(_kVisitOn, false);
    await prefs.setString(_kVisitPlace, '');
  }

  // 방문 시작 — companion 멘트만 (도착 인사 / "여기 뭐 해?")
  Future<void> _say(String event, String? place) async {
    try {
      final resp = await http
          .post(Uri.parse('$_baseUrl/companion/say'),
              headers: {'Content-Type': 'application/json'},
              body: jsonEncode({'event': event, 'place': place}))
          .timeout(const Duration(seconds: 20));
      if (resp.statusCode != 200) return;
      final d = jsonDecode(resp.body) as Map<String, dynamic>;
      final text = (d['text'] as String? ?? '').trim();
      if (text.isNotEmpty) await _notify((d['speaker'] as String?) ?? '', text);
    } catch (_) {}
  }

  // 방문 종료 — 기록 + '떠남' 멘트
  Future<void> _endVisit(double lat, double lng, String? place, int start,
      int end, int minutes) async {
    try {
      final resp = await http
          .post(Uri.parse('$_baseUrl/visits'),
              headers: {'Content-Type': 'application/json'},
              body: jsonEncode({
                'place': place,
                'lat': lat,
                'lng': lng,
                'start_ts': start,
                'end_ts': end,
                'minutes': minutes,
              }))
          .timeout(const Duration(seconds: 20));
      if (resp.statusCode != 200) return;
      final d = jsonDecode(resp.body) as Map<String, dynamic>;
      final text = (d['text'] as String? ?? '').trim();
      if (text.isNotEmpty) await _notify((d['speaker'] as String?) ?? '', text);
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
        ),
        payload: 'ask:$text'); // 탭하면 기록 탭에서 이 질문에 답
  }
}

import 'package:android_intent_plus/android_intent.dart';
import 'package:flutter/material.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:geolocator/geolocator.dart';
import 'package:network_info_plus/network_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/design.dart';
import 'location_permissions.dart';
import 'location_service.dart';
import 'location_task_handler.dart';

/// 위치 동반자 설정 — 집/작업실 저장 + 추적 켜기/끄기.
class LocationScreen extends StatefulWidget {
  const LocationScreen({super.key});

  @override
  State<LocationScreen> createState() => _LocationScreenState();
}

class _LocationScreenState extends State<LocationScreen> {
  bool _running = false;
  bool _hasHome = false, _hasOffice = false;
  String? _msg;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    final prefs = await SharedPreferences.getInstance();
    final running = await LocationService.isRunning();
    if (!mounted) return;
    setState(() {
      _running = running;
      _hasHome = prefs.getDouble(kHomeLat) != null;
      _hasOffice = prefs.getDouble(kOfficeLat) != null;
    });
  }

  Future<void> _saveHere(String latKey, String lngKey, String label) async {
    setState(() {
      _busy = true;
      _msg = '$label 위치 잡는 중…';
    });
    try {
      if (!await requestLocationPermissions()) {
        setState(() => _msg = '위치 권한이 필요해요 (‘항상 허용’까지)');
        return;
      }
      final pos = await Geolocator.getCurrentPosition(
        locationSettings:
            const LocationSettings(accuracy: LocationAccuracy.high),
      );
      final prefs = await SharedPreferences.getInstance();
      await prefs.setDouble(latKey, pos.latitude);
      await prefs.setDouble(lngKey, pos.longitude);
      // 지금 붙어 있는 WiFi도 기억 — 다음부터 이 WiFi면 GPS 없이 즉시 이곳으로.
      String wifiNote = '';
      try {
        final raw = await NetworkInfo().getWifiName();
        final ssid = (raw ?? '').replaceAll('"', '').trim();
        if (ssid.isNotEmpty && ssid != '<unknown ssid>') {
          await prefs.setString(label == '집' ? kHomeWifi : kOfficeWifi, ssid);
          wifiNote = ' · WiFi “$ssid” 기억함';
        }
      } catch (_) {}
      setState(() => _msg = '$label 위치를 저장했어요$wifiNote');
      await _refresh();
    } catch (e) {
      setState(() => _msg = '실패: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _toggle() async {
    setState(() => _busy = true);
    try {
      if (_running) {
        await LocationService.stop();
      } else {
        if (!await requestLocationPermissions()) {
          setState(() => _msg = '‘항상 허용’ 위치 권한이 필요해요');
          return;
        }
        LocationService.init();
        await FlutterForegroundTask.requestIgnoreBatteryOptimization();
        await LocationService.start();
      }
      await _refresh();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('위치 동반자')),
      body: ListView(
        padding: const EdgeInsets.all(OracleSpace.screenH),
        children: [
          Text(
            '집·작업실을 저장하면, 도착하거나 나설 때 쿠키·베르가 말을 걸어요. '
            '켜면 1분마다 위치를 확인하는 지속 알림이 떠요(배터리를 좀 씁니다).',
            style: OracleType.marginalia,
          ),
          const SizedBox(height: 28),
          _placeRow('집', _hasHome, kHomeLat, kHomeLng,
              () => _saveHere(kHomeLat, kHomeLng, '집')),
          _placeRow('작업실', _hasOffice, kOfficeLat, kOfficeLng,
              () => _saveHere(kOfficeLat, kOfficeLng, '작업실')),
          const Divider(height: 40),
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(_running ? '감지 중' : '꺼짐',
                        style: OracleType.userBody),
                    Text('포그라운드 위치 추적',
                        style: OracleType.marginalia
                            .copyWith(color: OracleColors.gray)),
                  ],
                ),
              ),
              Switch(
                value: _running,
                activeThumbColor: OracleColors.vermilion,
                onChanged: _busy ? null : (_) => _toggle(),
              ),
            ],
          ),
          if (_msg != null)
            Padding(
              padding: const EdgeInsets.only(top: 20),
              child: Text(_msg!,
                  style: OracleType.label.copyWith(color: OracleColors.vermilion)),
            ),
        ],
      ),
    );
  }

  Widget _placeRow(String label, bool saved, String latKey, String lngKey,
          VoidCallback onSave) =>
      Padding(
        padding: const EdgeInsets.only(bottom: 16),
        child: Row(
          children: [
            Expanded(
              child: Text('$label${saved ? '  ·  저장됨' : ''}',
                  style: OracleType.userBody),
            ),
            if (saved)
              TextButton(
                onPressed: () => _openInMap(latKey, lngKey, label),
                child: Text('지도',
                    style:
                        OracleType.label.copyWith(color: OracleColors.gray)),
              ),
            TextButton(
              onPressed: _busy ? null : onSave,
              child: Text(saved ? '여기로 갱신' : '여기를 $label으로',
                  style:
                      OracleType.label.copyWith(color: OracleColors.vermilion)),
            ),
          ],
        ),
      );

  /// 저장한 좌표를 지도앱으로 — geo: 인텐트(설치된 지도앱 선택).
  Future<void> _openInMap(String latKey, String lngKey, String label) async {
    final prefs = await SharedPreferences.getInstance();
    final lat = prefs.getDouble(latKey), lng = prefs.getDouble(lngKey);
    if (lat == null || lng == null) return;
    final intent = AndroidIntent(
      action: 'action_view',
      data: 'geo:$lat,$lng?q=$lat,$lng(${Uri.encodeComponent(label)})',
    );
    try {
      await intent.launch();
    } catch (_) {
      if (mounted) setState(() => _msg = '지도앱을 열 수 없어요');
    }
  }
}

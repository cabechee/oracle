import 'dart:convert';

import 'package:android_intent_plus/android_intent.dart';
import 'package:flutter/material.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:geolocator/geolocator.dart';
import 'package:network_info_plus/network_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../api.dart';
import '../../core/design.dart';
import 'location_permissions.dart';
import 'location_service.dart';
import 'location_task_handler.dart';

/// 위치 동반자 설정 — 집/작업실 저장 + 추적 켜기/끄기 + 자주 가는 곳(레지스트리).
///
/// 집·작업실·장소는 백엔드 레지스트리(SoT)에 올리고(동반자 맥락·웹 어드민),
/// 지오펜스 판정용으로 폰 prefs에도 좌표/WiFi 사본을 남긴다.
class LocationScreen extends StatefulWidget {
  final OracleApi api;
  const LocationScreen({super.key, required this.api});

  @override
  State<LocationScreen> createState() => _LocationScreenState();
}

class _LocationScreenState extends State<LocationScreen> {
  bool _running = false;
  bool _hasHome = false, _hasOffice = false;
  String? _msg;
  bool _busy = false;

  List<Map<String, dynamic>> _places = const [];
  bool _loadingPlaces = true;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    final prefs = await SharedPreferences.getInstance();
    final running = await LocationService.isRunning();
    List<Map<String, dynamic>> places = const [];
    try {
      places = await widget.api.listPlaces();
      places = await _migrateAnchors(prefs, places);
    } catch (_) {
      // 오프라인이면 빈 목록 — 집/작업실(prefs)은 그대로 동작
    }
    // 리졸브된 WiFi 집합을 prefs에 — 앱 복귀 시 '새 WiFi 저장 제안'이 이걸로 판단(오프라인).
    final knownWifi = <String>{
      for (final k in [kHomeWifi, kOfficeWifi])
        if ((prefs.getString(k) ?? '').isNotEmpty) prefs.getString(k)!,
      for (final p in places)
        if (((p['wifi'] as String?) ?? '').isNotEmpty) p['wifi'] as String,
    };
    await prefs.setStringList(kKnownWifi, knownWifi.toList());
    // BT로 식별되는 장소(차 등) → {BT기기명: 장소이름} 동기화 — isolate가 연결 감지에 씀.
    final btMap = <String, String>{
      for (final p in places)
        if (((p['bt'] as String?) ?? '').trim().isNotEmpty)
          (p['bt'] as String).trim(): ((p['name'] as String?) ?? '').trim(),
    };
    await prefs.setString(kBtMap, jsonEncode(btMap));
    // 위치 확인(센싱) 설정 동기화 — 어드민(📍 장소)의 주기·WiFi 스킵을 prefs로(주기는 다음 start 때 반영).
    try {
      final lc = await widget.api.getLocationConfig();
      final sec = (lc['poll_interval_sec'] as num?)?.toInt() ?? 60;
      await prefs.setInt(kPollIntervalMs, sec * 1000);
      await prefs.setBool(kSkipOnWifi, lc['skip_on_known_wifi'] != false);
    } catch (_) {}
    if (!mounted) return;
    setState(() {
      _running = running;
      _hasHome = prefs.getDouble(kHomeLat) != null;
      _hasOffice = prefs.getDouble(kOfficeLat) != null;
      _places = places;
      _loadingPlaces = false;
    });
  }

  /// 구앱이 폰(prefs)에만 저장해둔 집/작업실을 레지스트리에 1회 올린다(authoritative
  /// 좌표·WiFi). 레지스트리에 이미 있으면 건너뜀 → 새 앱 첫 진입 시 자동 동기화.
  Future<List<Map<String, dynamic>>> _migrateAnchors(
      SharedPreferences prefs, List<Map<String, dynamic>> places) async {
    final have = {for (final p in places) p['kind']};
    var changed = false;
    Future<void> push(String kind, String name, String latK, String lngK,
        String wifiK) async {
      if (have.contains(kind)) return; // 이미 레지스트리에 있음
      final lat = prefs.getDouble(latK), lng = prefs.getDouble(lngK);
      if (lat == null || lng == null) return; // 폰에도 저장 안 됨
      try {
        await widget.api.upsertPlace(
            name: name, kind: kind, lat: lat, lng: lng,
            wifi: prefs.getString(wifiK));
        changed = true;
      } catch (_) {}
    }

    await push('home', '집', kHomeLat, kHomeLng, kHomeWifi);
    await push('office', '작업실', kOfficeLat, kOfficeLng, kOfficeWifi);
    if (!changed) return places;
    try {
      return await widget.api.listPlaces();
    } catch (_) {
      return places;
    }
  }

  /// 집/작업실 = GPS로 좌표 잡고 + 지금 WiFi 기억 → prefs(지오펜스) + 백엔드 레지스트리.
  Future<void> _saveHere(
      String latKey, String lngKey, String label, String kind) async {
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
      String? ssid;
      String wifiNote = '';
      try {
        final raw = await NetworkInfo().getWifiName();
        final s = (raw ?? '').replaceAll('"', '').trim();
        if (s.isNotEmpty && s != '<unknown ssid>') {
          ssid = s;
          await prefs.setString(label == '집' ? kHomeWifi : kOfficeWifi, s);
          wifiNote = ' · WiFi “$s” 기억함';
        }
      } catch (_) {}
      // 백엔드 레지스트리에도 (동반자 맥락·웹 어드민). 실패해도 prefs는 저장됨.
      try {
        await widget.api.upsertPlace(
            name: label,
            kind: kind,
            lat: pos.latitude,
            lng: pos.longitude,
            wifi: ssid);
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
        final prefs = await SharedPreferences.getInstance();
        LocationService.init(
            intervalMs: prefs.getInt(kPollIntervalMs) ?? 60000);
        await FlutterForegroundTask.requestIgnoreBatteryOptimization();
        await LocationService.start();
      }
      await _refresh();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // ── 자주 가는 곳 추가/편집/삭제 ────────────────────────────
  /// 새 장소 추가 — fromWifi면 지금 WiFi·GPS를 잡아 함께 등록(맥락 설명도 입력).
  Future<void> _addPlace({required bool fromWifi}) async {
    String? wifi;
    double? lat, lng;
    if (fromWifi) {
      setState(() => _busy = true);
      try {
        try {
          final raw = await NetworkInfo().getWifiName();
          final s = (raw ?? '').replaceAll('"', '').trim();
          if (s.isNotEmpty && s != '<unknown ssid>') wifi = s;
        } catch (_) {}
        if (await requestLocationPermissions()) {
          try {
            final pos = await Geolocator.getCurrentPosition(
              locationSettings:
                  const LocationSettings(accuracy: LocationAccuracy.high),
            );
            lat = pos.latitude;
            lng = pos.longitude;
          } catch (_) {}
        }
      } finally {
        if (mounted) setState(() => _busy = false);
      }
      if (wifi == null && lat == null) {
        setState(() => _msg = '지금 WiFi·위치를 못 잡았어요 — 직접 추가를 써주세요');
        return;
      }
    }
    final prefs = await SharedPreferences.getInstance();
    final btNow = (prefs.getString(kBtConnected) ?? '').trim();
    if (!mounted) return;
    final r = await _placeDialog(
        detectedWifi: wifi, detectedBt: btNow.isEmpty ? null : btNow);
    if (r == null) return;
    try {
      await widget.api.upsertPlace(
          name: r.$1, kind: 'place', lat: lat, lng: lng, wifi: wifi,
          bt: r.$3.isEmpty ? null : r.$3, description: r.$2);
      setState(() => _msg = '‘${r.$1}’ 저장했어요');
      await _refresh();
    } catch (e) {
      setState(() => _msg = '저장 실패: $e');
    }
  }

  Future<void> _editPlace(Map<String, dynamic> p) async {
    final r = await _placeDialog(
        initialName: p['name'] as String?,
        initialDesc: p['description'] as String?,
        initialBt: p['bt'] as String?,
        detectedWifi: p['wifi'] as String?);
    if (r == null) return;
    try {
      await widget.api.upsertPlace(
          id: p['id'] as String?, name: r.$1, description: r.$2,
          bt: r.$3.isEmpty ? null : r.$3);
      await _refresh();
    } catch (e) {
      setState(() => _msg = '수정 실패: $e');
    }
  }

  Future<void> _deletePlace(Map<String, dynamic> p) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: OracleColors.paper,
        title: Text('‘${p['name']}’ 삭제할까요?',
            style: OracleType.journal.copyWith(fontSize: 15)),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: Text('아니요',
                  style: OracleType.userBody.copyWith(color: OracleColors.gray))),
          TextButton(
              onPressed: () => Navigator.pop(context, true),
              child: Text('삭제',
                  style:
                      OracleType.userBody.copyWith(color: OracleColors.vermilion))),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await widget.api.deletePlace(p['id'] as String);
      await _refresh();
    } catch (e) {
      setState(() => _msg = '삭제 실패: $e');
    }
  }

  /// 이름·설명·BT 입력 다이얼로그 — (name, description, bt) 또는 취소면 null.
  Future<(String, String, String)?> _placeDialog(
      {String? initialName, String? initialDesc, String? initialBt,
      String? detectedWifi, String? detectedBt}) async {
    final nameCtrl = TextEditingController(text: initialName ?? '');
    final descCtrl = TextEditingController(text: initialDesc ?? '');
    final btCtrl = TextEditingController(
        text: (initialBt ?? '').isNotEmpty ? initialBt : (detectedBt ?? ''));
    return showDialog<(String, String, String)>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: OracleColors.paper,
        title: Text(initialName == null ? '장소 추가' : '장소 수정',
            style: OracleType.dateHeader),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (detectedWifi != null && detectedWifi.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Text('WiFi “$detectedWifi”',
                      style:
                          OracleType.label.copyWith(color: OracleColors.gray)),
                ),
              if (detectedBt != null && detectedBt.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Text('지금 연결된 블루투스 “$detectedBt”',
                      style:
                          OracleType.label.copyWith(color: OracleColors.gray)),
                ),
              TextField(
                controller: nameCtrl,
                autofocus: true,
                style: OracleType.userBody,
                decoration: const InputDecoration(hintText: '이름 (예: 단골 카페, 차)'),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: descCtrl,
                style: OracleType.userBody,
                minLines: 2,
                maxLines: 4,
                decoration: const InputDecoration(
                    hintText: '설명 — 동반자가 맥락으로 써요 (예: 주말마다 작업하는 곳)'),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: btCtrl,
                style: OracleType.userBody,
                decoration: const InputDecoration(
                    hintText: '블루투스 기기명 — 연결되면 그 장소로 (예: 차량오디오) · 선택'),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: Text('취소',
                  style: OracleType.label.copyWith(color: OracleColors.gray))),
          TextButton(
              onPressed: () {
                final n = nameCtrl.text.trim();
                if (n.isEmpty) return;
                Navigator.pop(ctx,
                    (n, descCtrl.text.trim(), btCtrl.text.trim()));
              },
              child: Text('저장',
                  style:
                      OracleType.label.copyWith(color: OracleColors.vermilion))),
        ],
      ),
    );
  }

  Future<void> _addMenu() async {
    final choice = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: OracleColors.paper,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.wifi, color: OracleColors.ink),
              title: Text('지금 WiFi·위치로 추가', style: OracleType.userBody),
              subtitle: Text('여기 붙은 WiFi와 좌표를 함께 기억',
                  style: OracleType.marginalia),
              onTap: () => Navigator.pop(context, 'wifi'),
            ),
            ListTile(
              leading: const Icon(Icons.edit_outlined, color: OracleColors.ink),
              title: Text('직접 추가', style: OracleType.userBody),
              subtitle:
                  Text('이름·설명만 (맥락용)', style: OracleType.marginalia),
              onTap: () => Navigator.pop(context, 'manual'),
            ),
          ],
        ),
      ),
    );
    if (choice == 'wifi') await _addPlace(fromWifi: true);
    if (choice == 'manual') await _addPlace(fromWifi: false);
  }

  @override
  Widget build(BuildContext context) {
    final extraPlaces =
        _places.where((p) => p['kind'] != 'home' && p['kind'] != 'office').toList();
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
              () => _saveHere(kHomeLat, kHomeLng, '집', 'home')),
          _placeRow('작업실', _hasOffice, kOfficeLat, kOfficeLng,
              () => _saveHere(kOfficeLat, kOfficeLng, '작업실', 'office')),
          const Divider(height: 40),
          // ── 자주 가는 곳 ──
          Row(
            children: [
              Expanded(
                child: Text('자주 가는 곳', style: OracleType.userBody),
              ),
              TextButton.icon(
                onPressed: _busy ? null : _addMenu,
                icon: const Icon(Icons.add,
                    size: 16, color: OracleColors.vermilion),
                label: Text('추가',
                    style: OracleType.label
                        .copyWith(color: OracleColors.vermilion)),
              ),
            ],
          ),
          if (_loadingPlaces)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 16),
              child: Center(
                child: SizedBox(
                    width: 14,
                    height: 14,
                    child: CircularProgressIndicator(
                        strokeWidth: 1, color: OracleColors.faint)),
              ),
            )
          else if (extraPlaces.isEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4, bottom: 8),
              child: Text(
                  '새 WiFi에 붙으면 저장을 제안하고, ‘추가’로 직접 등록할 수도 있어요. '
                  '설명은 동반자가 맥락으로 씁니다.',
                  style: OracleType.marginalia.copyWith(color: OracleColors.gray)),
            )
          else
            for (final p in extraPlaces) _placeCard(p),
          const SizedBox(height: 28),
          // ── 추적 토글 ──
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(_running ? '감지 중' : '꺼짐', style: OracleType.userBody),
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
                  style:
                      OracleType.label.copyWith(color: OracleColors.vermilion)),
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

  /// 자주 가는 곳 카드 — 이름·설명·WiFi. 탭=수정, 휴지통=삭제.
  Widget _placeCard(Map<String, dynamic> p) {
    final desc = (p['description'] as String?)?.trim() ?? '';
    final wifi = (p['wifi'] as String?)?.trim() ?? '';
    final bt = (p['bt'] as String?)?.trim() ?? '';
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: InkWell(
        onTap: () => _editPlace(p),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text((p['name'] as String?) ?? '이름 없는 곳',
                      style: OracleType.userBody),
                  if (desc.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Text(desc,
                          style: OracleType.marginalia
                              .copyWith(color: OracleColors.gray)),
                    ),
                  if (wifi.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Text('WiFi “$wifi”', style: OracleType.label),
                    ),
                  if (bt.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Text('BT “$bt”', style: OracleType.label),
                    ),
                ],
              ),
            ),
            IconButton(
              icon: const Icon(Icons.delete_outline,
                  size: 19, color: OracleColors.faint),
              onPressed: () => _deletePlace(p),
            ),
          ],
        ),
      ),
    );
  }

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

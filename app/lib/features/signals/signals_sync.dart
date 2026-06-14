/// 신호 평면 콜렉터 — 30분 주기 WorkManager 백그라운드 작업.
///
/// 미읽음 SMS + 마지막 동기화 이후 부재중 통화를 백엔드 /signals/sync로 보내고,
/// 새 요약이 돌아오면 로컬 알림으로 표시한다. FCM 없이 폰 주도 사이클.
/// SMS 본문은 백엔드에서 로컬 LLM으로만 처리(클라우드 미전송 — 백엔드 원칙).
library;

import 'dart:async';
import 'dart:convert';

import 'package:another_telephony/telephony.dart' hide NetworkType;
import 'package:call_log/call_log.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:notification_listener_service/notification_event.dart';
import 'package:notification_listener_service/notification_listener_service.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:workmanager/workmanager.dart';

import '../../api.dart';
import '../../applog.dart';
import '../../home_widget_service.dart';

const kSignalsTask = 'signals-sync';
const _kLastSyncKey = 'signals_last_sync_ms';
const _kNotifBufKey = 'signals_notif_buffer';
const _kNotifPermAsked = 'notif_perm_asked';

// 수집 제외 — 자기 자신·시스템·런처·구글서비스(노이즈). 나머지는 백엔드가 분류로 거름.
const _notifBlocklist = [
  'studio.camembertcheese.oracle', 'android', 'com.android.systemui',
  'com.samsung.android.', 'com.google.android.gms',
  'com.google.android.apps.nexuslauncher', 'com.sec.android.app.launcher',
];

StreamSubscription<ServiceNotificationEvent>? _notifSub;

/// 알림 리스너 시작 — 권한 있으면 스트림 구독(앱 실행 중 누적), 없으면 1회 권한 화면.
Future<void> initNotificationListener() async {
  try {
    if (!await NotificationListenerService.isPermissionGranted()) {
      final prefs = await SharedPreferences.getInstance();
      if (!(prefs.getBool(_kNotifPermAsked) ?? false)) {
        await prefs.setBool(_kNotifPermAsked, true);
        await NotificationListenerService.requestPermission();
      }
      return;
    }
    _notifSub ??=
        NotificationListenerService.notificationsStream.listen(_onNotif);
  } catch (e) {
    AppLog.info('알림 리스너 init 실패: $e');
  }
}

/// 알림 1건 — 의미있는 것만 prefs 버퍼에 누적 (sync 때 flush).
///
/// "놓치는 알림" 진단을 위해 필터 분기마다 로그를 남긴다(타이틀 long-press 로그뷰).
/// 제거·지속(onGoing) 이벤트는 음악 위젯 등으로 매우 잦아 로깅 생략(노이즈).
Future<void> _onNotif(ServiceNotificationEvent e) async {
  if (e.hasRemoved == true || e.onGoing == true) return; // 제거·지속(음악 등) 제외
  final pkg = e.packageName ?? '';
  if (_notifBlocklist.any((b) => pkg.startsWith(b))) {
    AppLog.info('알림 거름: 블랙리스트 $pkg');
    return;
  }
  final title = (e.title ?? '').trim();
  final content = (e.content ?? '').trim();
  if (title.isEmpty && content.isEmpty) {
    AppLog.info('알림 거름: 빈 제목·본문 ($pkg)');
    return;
  }
  final prefs = await SharedPreferences.getInstance();
  final buf = prefs.getStringList(_kNotifBufKey) ?? [];
  // 같은 알림이 posted+updated 두 이벤트로 중복 적재되는 것 방지 — 버퍼에 동일한
  // (app·title·text)가 이미 있으면 스킵. (ts=수신시각이라 백엔드 dedup id가 갈리던 원인)
  final dupe = buf.any((s) {
    try {
      final m = jsonDecode(s) as Map<String, dynamic>;
      return m['app'] == pkg && m['title'] == title && m['text'] == content;
    } catch (_) {
      return false;
    }
  });
  if (dupe) {
    AppLog.info('알림 거름: 중복 $pkg / $title');
    return;
  }
  buf.add(jsonEncode({
    'app': pkg,
    'title': title,
    'text': content,
    'ts': DateTime.now().millisecondsSinceEpoch,
  }));
  if (buf.length > 200) buf.removeRange(0, buf.length - 200); // 상한
  await prefs.setStringList(_kNotifBufKey, buf);
  AppLog.info('알림 수집: $pkg / ${title.isEmpty ? content : title} (버퍼 ${buf.length})');
}

/// main()에서 1회 — 디스패처 등록 + 30분 주기 작업 예약 (idempotent).
Future<void> initSignalsSync() async {
  await Workmanager().initialize(signalsDispatcher);
  await Workmanager().registerPeriodicTask(
    kSignalsTask,
    kSignalsTask,
    frequency: const Duration(minutes: 30),
    existingWorkPolicy: ExistingPeriodicWorkPolicy.keep,
    constraints: Constraints(networkType: NetworkType.connected),
    backoffPolicy: BackoffPolicy.linear,
  );
}

@pragma('vm:entry-point')
void signalsDispatcher() {
  Workmanager().executeTask((task, inputData) async {
    try {
      await runSignalsSync();
      return true;
    } catch (e) {
      AppLog.info('signals sync 실패: $e');
      return true; // 재시도 폭주 방지 — 다음 주기에 자연 재시도
    }
  });
}

// 포그라운드 동시 실행 가드 — 앱 시작(initState)과 resume이 거의 동시에 발사돼
// 같은 미읽음 신호를 두 번 보내 brief가 중복 생성되던 race 방지 (main isolate 한정).
bool _syncInFlight = false;

/// 포그라운드 보조 동기화 — 앱 열림/복귀 시. 삼성 배터리 최적화로 백그라운드
/// 주기가 미뤄져도 앱을 여는 순간엔 최신을 보장 (minGap 스로틀 + 동시 가드).
Future<void> maybeForegroundSync(
    {Duration minGap = const Duration(minutes: 5)}) async {
  if (_syncInFlight) return;
  final prefs = await SharedPreferences.getInstance();
  final last = prefs.getInt(_kLastSyncKey) ?? 0;
  if (DateTime.now().millisecondsSinceEpoch - last < minGap.inMilliseconds) {
    return;
  }
  _syncInFlight = true;
  try {
    await runSignalsSync();
  } catch (e) {
    AppLog.info('포그라운드 signals sync 실패: $e');
  } finally {
    _syncInFlight = false;
  }
}

/// 동기화 1회 — 권한 없으면 해당 소스만 조용히 건너뜀.
Future<void> runSignalsSync() async {
  final prefs = await SharedPreferences.getInstance();
  final nowMs = DateTime.now().millisecondsSinceEpoch;
  final sinceMs = prefs.getInt(_kLastSyncKey) ??
      (nowMs - const Duration(hours: 24).inMilliseconds);

  // 1) 미읽음 SMS (READ_SMS 권한 필요 — 없으면 빈 리스트)
  final sms = <Map<String, dynamic>>[];
  try {
    final inbox = await Telephony.instance.getInboxSms(
      columns: [SmsColumn.ADDRESS, SmsColumn.BODY, SmsColumn.DATE, SmsColumn.READ],
      filter: SmsFilter.where(SmsColumn.READ).equals('0'),
      sortOrder: [OrderBy(SmsColumn.DATE, sort: Sort.DESC)],
    );
    for (final m in inbox.take(50)) {
      sms.add({'from': m.address ?? '', 'body': m.body ?? '', 'ts': m.date ?? nowMs});
    }
  } catch (e) {
    AppLog.info('SMS 조회 불가(권한?): $e');
  }

  // 2) 부재중 통화 — 마지막 동기화 이후
  final calls = <Map<String, dynamic>>[];
  try {
    final entries = await CallLog.query(
        dateFrom: sinceMs, type: CallType.missed);
    for (final c in entries.take(20)) {
      calls.add({
        'from': (c.name?.isNotEmpty == true ? c.name : c.number) ?? '',
        'ts': c.timestamp ?? nowMs,
      });
    }
  } catch (e) {
    AppLog.info('통화기록 조회 불가(권한?): $e');
  }

  // 3) 앱 알림 버퍼 flush (리스너가 누적해둔 것)
  final notifBuf = prefs.getStringList(_kNotifBufKey) ?? [];
  final notifications = <Map<String, dynamic>>[];
  for (final s in notifBuf) {
    try {
      notifications.add(jsonDecode(s) as Map<String, dynamic>);
    } catch (_) {}
  }

  // 빈 동기화도 보낸다 — 서버측 미요약분 재시도 트리거 + 30분 하트비트(동작 확인 가능)
  final result =
      await OracleApi().syncSignals(sms, calls, notifications: notifications);
  await prefs.setInt(_kLastSyncKey, nowMs);
  if (notifications.isNotEmpty) {
    await prefs.remove(_kNotifBufKey); // 전송 성공 후 버퍼 비움
  }

  final summary = (result['summary'] as String?)?.trim() ?? '';
  if (summary.isNotEmpty && !summary.startsWith('(요약 실패')) {
    await _notify(summary,
        smsCount: (result['sms_count'] as num?)?.toInt() ?? 0,
        callCount: (result['call_count'] as num?)?.toInt() ?? 0);
  }

  await _maybeBriefingNotify(prefs); // 새 조간/석간이면 알림 (같은 주기 편승)
  await _maybeCheckin(prefs);        // 활동 시간대면 동반자 '뭐해' (정시 1회)
  try {
    await refreshWidget(OracleApi()); // 홈 위젯 갱신 (오늘 알림·리마인더)
  } catch (e) {
    AppLog.info('위젯 갱신 실패: $e');
  }
}

const _kBriefingSeen = 'briefing_last_seen';
const _kLastCheckinHour = 'companion_last_checkin_hour';

// 동반자 말걸기 — 활동 시간대(09~22시) 매 정시 1회. 좀 잦아도 OK(사용자 선택).
const _checkinStartHour = 9;
const _checkinEndHour = 22;

/// 동반자 정시 체크인 — 위치 없이 쿠키/베르가 '뭐해' 한마디. 매 시간 1회.
///
/// 30분 주기에 편승해, 같은 '시'엔 한 번만 보낸다(정각 직후 첫 틱에 발사 → 거의 정시).
Future<void> _maybeCheckin(SharedPreferences prefs) async {
  final now = DateTime.now();
  if (now.hour < _checkinStartHour || now.hour >= _checkinEndHour) return;
  // 정시 1회 — 이 시간대(연-월-일-시)에 이미 보냈으면 건너뜀.
  final hourKey = '${now.year}-${now.month}-${now.day}-${now.hour}';
  if (prefs.getString(_kLastCheckinHour) == hourKey) return;
  try {
    final r = await OracleApi().companionSay('checkin');
    final text = (r['text'] as String?)?.trim() ?? '';
    if (text.isEmpty) return;        // alias 미설정·실패 — 다음 기회에
    await prefs.setString(_kLastCheckinHour, hourKey);
    await _notifyCompanion((r['speaker'] as String?) ?? '', text);
    AppLog.info('동반자 체크인: ${r['speaker']} — $text');
  } catch (e) {
    AppLog.info('동반자 체크인 실패: $e');
  }
}

/// 동반자 한마디 알림 — 백그라운드 isolate라 plugin 직접 생성(_notify와 같은 패턴).
Future<void> _notifyCompanion(String speaker, String text) async {
  final plugin = FlutterLocalNotificationsPlugin();
  await plugin.initialize(const InitializationSettings(
    android: AndroidInitializationSettings('@mipmap/ic_launcher'),
  ));
  final icon = speaker == '쿠키' ? '🐦' : (speaker == '베르' ? '🐶' : '🐾');
  // 베르는 캐릭터 얼굴을 큰 아이콘으로(drawable/bert) — 쿠키·기타는 이모지만.
  final largeIcon = speaker == '베르'
      ? const DrawableResourceAndroidBitmap('bert')
      : null;
  await plugin.show(9, '$icon ${speaker.isEmpty ? '동반자' : speaker}', text,
      NotificationDetails(
        android: AndroidNotificationDetails('companion', '동반자',
            channelDescription: '쿠키·베르의 말 걸기',
            importance: Importance.defaultImportance,
            largeIcon: largeIcon,
            styleInformation: const BigTextStyleInformation('')),
      ));
}

/// 새 발행물(조간/석간) 도착 시 1회 알림.
Future<void> _maybeBriefingNotify(SharedPreferences prefs) async {
  try {
    final b = await OracleApi().fetchBriefingLatest();
    if (b == null) return;
    final id = b['id'] as String? ?? '';
    if (id.isEmpty || prefs.getString(_kBriefingSeen) == id) return;
    await prefs.setString(_kBriefingSeen, id);
    final title = b['kind'] == 'morning' ? '☀️ 오늘의 조간' : '🌙 오늘의 석간';
    final text = (b['text'] as String? ?? '').trim();
    final plugin = FlutterLocalNotificationsPlugin();
    await plugin.initialize(const InitializationSettings(
      android: AndroidInitializationSettings('@mipmap/ic_launcher'),
    ));
    await plugin.show(8, title, text,
        const NotificationDetails(
          android: AndroidNotificationDetails('briefing', '발행물',
              channelDescription: '조간·석간 발행물',
              importance: Importance.defaultImportance,
              styleInformation: BigTextStyleInformation('')),
        ));
  } catch (_) {}
}

Future<void> _notify(String summary,
    {required int smsCount, required int callCount}) async {
  final plugin = FlutterLocalNotificationsPlugin();
  await plugin.initialize(const InitializationSettings(
    android: AndroidInitializationSettings('@mipmap/ic_launcher'),
  ));
  final parts = <String>[
    if (smsCount > 0) '문자 $smsCount',
    if (callCount > 0) '부재중 $callCount',
  ];
  await plugin.show(
    7,
    '📨 대신 읽어드림 — ${parts.join(' · ')}',
    summary,
    const NotificationDetails(
      android: AndroidNotificationDetails(
        'signals', '신호 요약',
        channelDescription: '미읽음 문자·부재중 통화 30분 요약',
        importance: Importance.defaultImportance,
        styleInformation: BigTextStyleInformation(''),
      ),
    ),
  );
}

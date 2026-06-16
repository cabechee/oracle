import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:http/http.dart' as http;

import 'applog.dart';
import 'models.dart';

class OracleApi {
  final String baseUrl;

  /// opt-in API 토큰 — backend ORACLE_TOKEN과 같은 값으로 빌드:
  /// flutter build apk --dart-define=ORACLE_TOKEN=...  (비우면 헤더 미전송)
  static const _token = String.fromEnvironment('ORACLE_TOKEN');

  OracleApi({String? baseUrl})
      : baseUrl = baseUrl ??
            // 웹: FastAPI가 같은 origin에 서빙 → 자기가 로드된 곳으로 API 호출(CORS 불필요).
            // 모바일: Tailscale magic DNS 고정 (빌드타임 override 가능).
            (kIsWeb
                ? Uri.base.origin
                : const String.fromEnvironment(
                    'ORACLE_API',
                    defaultValue: 'http://chocolat.tail575fea.ts.net:8001',
                  ));

  // 타임아웃 — LLM 경유(query/chat)는 길게, 단순 조회는 짧게.
  // ingest는 비동기(즉시 202성 응답)지만 영상 업로드가 있어 넉넉히.
  // digest 수동 실행은 월요일/1일에 일+주+월 배치가 겹치면 매우 길다 — plist max-time(1800)에 맞춤.
  static const _ingestTimeout = Duration(seconds: 300);
  static const _llmTimeout = Duration(seconds: 300);
  static const _digestRunTimeout = Duration(seconds: 1800);
  static const _getTimeout = Duration(seconds: 15);

  /// 공통 헤더 — 토큰 빌드 시에만 부착.
  Map<String, String> get authHeaders =>
      _token.isEmpty ? const {} : const {'X-Oracle-Token': _token};

  /// Image.network 등 미디어 로딩용 헤더 (토큰 없으면 null).
  Map<String, String>? get photoHeaders =>
      _token.isEmpty ? null : const {'X-Oracle-Token': _token};

  static String _short(String s) =>
      s.length > 200 ? '${s.substring(0, 200)}…' : s;

  /// 공통 HTTP 래퍼 — 타임아웃 + 구조적 로깅(요청·상태·소요·에러종류).
  Future<http.Response> _req(
    String label,
    Future<http.Response> Function() send, {
    Duration timeout = _getTimeout,
    String? sent, // 요청 본문 요약 (있으면 "앱→서버 보낸 데이터"로 기록)
  }) async {
    if (sent != null && sent.isNotEmpty) AppLog.net('$label ← 보냄 ${_short(sent)}');
    final sw = Stopwatch()..start();
    try {
      final r = await send().timeout(timeout);
      final ms = sw.elapsedMilliseconds;
      if (r.statusCode >= 400) {
        AppLog.err('$label → HTTP ${r.statusCode} (${ms}ms) ${_short(r.body)}');
      } else {
        // 성공 응답도 본문 요약까지 — "서버→폰 넘어온 데이터" 추적.
        AppLog.net('$label → ${r.statusCode} (${ms}ms) ${_short(utf8.decode(r.bodyBytes, allowMalformed: true))}');
      }
      return r;
    } on TimeoutException {
      AppLog.err('$label → TIMEOUT after ${timeout.inSeconds}s');
      rethrow;
    } on SocketException catch (e) {
      AppLog.err('$label → NETWORK ${e.osError?.message ?? e.message}');
      rethrow;
    } catch (e) {
      AppLog.err('$label → ${e.runtimeType}: $e');
      rethrow;
    }
  }

  Future<Record> ingest({
    String? comment,
    List<File> imageFiles = const [],
    List<({List<int> bytes, String name})> imageBytesList = const [],
    File? audioFile,
    File? videoFile,
    String? model,
    bool asyncMode = true,
    bool backfill = false,
    String? companionPrompt,   // 동반자 선제 멘트의 답이면 그 멘트 (즉답이 맥락 알게)
    String? companionSpeaker,  // 베르 | 쿠키
  }) async {
    final uri = Uri.parse('$baseUrl/ingest');
    final req = http.MultipartRequest('POST', uri);
    req.headers.addAll(authHeaders);
    if (comment != null && comment.isNotEmpty) req.fields['comment'] = comment;
    if (model != null && model.isNotEmpty) req.fields['model'] = model;
    // 비동기 인입 — 백엔드가 stub(status=processing)을 즉시 반환, 완료는 폴링으로
    if (asyncMode) req.fields['async_mode'] = '1';
    if (backfill) req.fields['backfill'] = '1'; // 지나간 사진 — EXIF 촬영시각을 ts로
    if (companionPrompt != null && companionPrompt.isNotEmpty) {
      req.fields['companion_prompt'] = companionPrompt;
    }
    if (companionSpeaker != null && companionSpeaker.isNotEmpty) {
      req.fields['companion_speaker'] = companionSpeaker;
    }
    // 사진은 'file' 필드를 여러 번 — 백엔드가 한 record로 묶음(구앱은 1개 → 호환)
    for (final f in imageFiles) {
      req.files.add(await http.MultipartFile.fromPath('file', f.path));
    }
    for (final b in imageBytesList) {
      // 웹/백필 — 경로 없는 bytes 업로드
      req.files.add(http.MultipartFile.fromBytes('file', b.bytes, filename: b.name));
    }
    if (audioFile != null) {
      req.files.add(await http.MultipartFile.fromPath('audio', audioFile.path));
    }
    if (videoFile != null) {
      req.files.add(await http.MultipartFile.fromPath('video', videoFile.path));
    }
    final sw = Stopwatch()..start();
    try {
      final streamed = await req.send().timeout(_ingestTimeout);
      final resp = await http.Response.fromStream(streamed);
      final ms = sw.elapsedMilliseconds;
      if (resp.statusCode != 200) {
        AppLog.err(
            'POST /ingest → HTTP ${resp.statusCode} (${ms}ms) ${_short(resp.body)}');
        throw Exception('ingest 실패: ${resp.statusCode} ${resp.body}');
      }
      AppLog.info('POST /ingest → 200 (${ms}ms)');
      return Record.fromIngest(jsonDecode(utf8.decode(resp.bodyBytes)));
    } on TimeoutException {
      AppLog.err('POST /ingest → TIMEOUT after ${_ingestTimeout.inSeconds}s');
      rethrow;
    } on SocketException catch (e) {
      AppLog.err('POST /ingest → NETWORK ${e.osError?.message ?? e.message}');
      rethrow;
    }
  }

  /// 자정 배치로 생성된 다이제스트 목록 (최신순).
  Future<List<DigestEntry>> listDigests() async {
    final resp = await _req(
        'GET /digest/list', () => http.get(Uri.parse('$baseUrl/digest/list'), headers: authHeaders));
    if (resp.statusCode != 200) {
      throw Exception('digest/list 실패: ${resp.statusCode}');
    }
    final data = jsonDecode(utf8.decode(resp.bodyBytes));
    final items = (data['items'] as List).cast<Map<String, dynamic>>();
    return items.map(DigestEntry.fromJson).toList();
  }

  /// 특정 날짜의 다이제스트 마크다운 본문.
  Future<String> getDigest(String dateStr) async {
    final resp = await _req('GET /digest/$dateStr',
        () => http.get(Uri.parse('$baseUrl/digest/$dateStr'), headers: authHeaders));
    if (resp.statusCode != 200) {
      throw Exception('digest 실패: ${resp.statusCode}');
    }
    final data = jsonDecode(utf8.decode(resp.bodyBytes));
    return (data['text'] as String?) ?? '';
  }

  /// 상위 인덱스 vault master.md 본문.
  Future<String> getMasterIndex() async {
    final resp = await _req('GET /index/master',
        () => http.get(Uri.parse('$baseUrl/index/master'), headers: authHeaders));
    if (resp.statusCode == 404) return '';
    if (resp.statusCode != 200) {
      throw Exception('index/master 실패: ${resp.statusCode}');
    }
    final data = jsonDecode(utf8.decode(resp.bodyBytes));
    return (data['text'] as String?) ?? '';
  }

  /// MongoDB index_meta (월별 가벼운 구조).
  Future<List<Map<String, dynamic>>> getIndexMeta() async {
    final resp = await _req(
        'GET /index/meta', () => http.get(Uri.parse('$baseUrl/index/meta'), headers: authHeaders));
    if (resp.statusCode != 200) {
      throw Exception('index/meta 실패: ${resp.statusCode}');
    }
    final data = jsonDecode(utf8.decode(resp.bodyBytes));
    return ((data['months'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
  }

  /// 자연어 질의 — backend query 모듈. 답변 + 참조 record_id.
  Future<QueryResult> query(String question, {int limit = 30}) async {
    final body = jsonEncode({'question': question, 'limit': limit});
    final resp = await _req(
      'POST /query',
      () => http.post(Uri.parse('$baseUrl/query'),
          headers: {'Content-Type': 'application/json', ...authHeaders},
          body: body),
      timeout: _llmTimeout,
      sent: body,
    );
    if (resp.statusCode != 200) {
      throw Exception('query 실패: ${resp.statusCode} ${resp.body}');
    }
    final data = jsonDecode(utf8.decode(resp.bodyBytes));
    return QueryResult(
      answer: (data['answer'] as String?) ?? '',
      referenced: ((data['referenced'] as List?) ?? const []).cast<String>(),
      alias: data['alias'] as String?,
    );
  }

  /// 펜딩 thread (X일 무언급) 후보 목록.
  Future<List<Map<String, dynamic>>> getSilentThreads({
    int minDays = 3,
    int maxDays = 30,
  }) async {
    final resp = await _req(
        'GET /threads/silent',
        () => http.get(
            Uri.parse(
                '$baseUrl/threads/silent?min_days=$minDays&max_days=$maxDays'),
            headers: authHeaders));
    if (resp.statusCode != 200) {
      throw Exception('silent 실패: ${resp.statusCode}');
    }
    final data = jsonDecode(utf8.decode(resp.bodyBytes));
    return ((data['items'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
  }

  /// 자정 배치 수동 트리거 (target_date 안 주면 어제).
  Future<Map<String, dynamic>> runDigest({String? targetDate}) async {
    final qp = targetDate != null ? '?target_date=$targetDate' : '';
    final resp = await _req(
        'POST /digest/run', () => http.post(Uri.parse('$baseUrl/digest/run$qp'), headers: authHeaders),
        timeout: _digestRunTimeout);
    if (resp.statusCode != 200) {
      throw Exception('digest/run 실패: ${resp.statusCode} ${resp.body}');
    }
    return jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
  }

  /// Nest 등록 모델 + council 목록. AppBar 모델 선택용.
  Future<LlmCatalog> listLlmModels() async {
    final resp = await _req(
        'GET /llm/models', () => http.get(Uri.parse('$baseUrl/llm/models'), headers: authHeaders));
    if (resp.statusCode != 200) {
      throw Exception('models 실패: ${resp.statusCode}');
    }
    return LlmCatalog.fromJson(
      jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>,
    );
  }

  Future<List<Record>> listRecent({int limit = 50, int offset = 0}) async {
    final resp = await _req(
        'GET /records?limit=$limit&offset=$offset',
        () => http.get(
            Uri.parse('$baseUrl/records?limit=$limit&offset=$offset'),
            headers: authHeaders));
    if (resp.statusCode != 200) {
      throw Exception('records 실패: ${resp.statusCode}');
    }
    final data = jsonDecode(utf8.decode(resp.bodyBytes));
    final items = (data['items'] as List).cast<Map<String, dynamic>>();
    return items.map(Record.fromMongo).toList();
  }

  /// record 단건 조회 — 비동기 ingest 완료 폴링 + 참조 카드용.
  Future<Record> getRecord(String recordId) async {
    final resp = await _req(
        'GET /records/$recordId',
        () => http.get(Uri.parse('$baseUrl/records/$recordId'),
            headers: authHeaders));
    if (resp.statusCode != 200) {
      throw Exception('record 조회 실패: ${resp.statusCode}');
    }
    return Record.fromMongo(
        jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>);
  }

  /// 재처리 — 같은 사진·코멘트로 다시 돌려 갱신된 record 반환.
  /// part = all|quick|analysis|comment|discovery (부분 재처리).
  Future<Record> reprocess(String recordId, {String part = 'all'}) async {
    final resp = await _req(
        'POST /records/$recordId/reprocess',
        () => http.post(
            Uri.parse('$baseUrl/records/$recordId/reprocess?part=$part'),
            headers: authHeaders),
        timeout: _llmTimeout);
    if (resp.statusCode != 200) {
      throw Exception('재처리 실패: ${resp.statusCode}');
    }
    return Record.fromMongo(
        jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>);
  }

  /// 실수 업로드 취소 — record를 흐름에서 숨김 (soft delete, 어드민엔 남음).
  Future<void> hideRecord(String recordId) async {
    await _req(
        'POST /records/$recordId/hide',
        () => http.post(Uri.parse('$baseUrl/records/$recordId/hide'),
            headers: authHeaders));
  }

  /// 대화 한 턴 — user/assistant 메시지 쌍 반환 (서버에 저장됨).
  Future<List<ChatMessage>> sendChat(String message,
      {List<String> mentionIds = const []}) async {
    final body = jsonEncode({'message': message, 'mention_ids': mentionIds});
    final resp = await _req(
      'POST /chat',
      () => http.post(Uri.parse('$baseUrl/chat'),
          headers: {'Content-Type': 'application/json', ...authHeaders},
          body: body),
      timeout: _llmTimeout,
      sent: body,
    );
    if (resp.statusCode != 200) {
      throw Exception('chat 실패: ${resp.statusCode} ${resp.body}');
    }
    final data = jsonDecode(utf8.decode(resp.bodyBytes));
    return ((data['messages'] as List?) ?? const [])
        .cast<Map<String, dynamic>>()
        .map(ChatMessage.fromJson)
        .toList();
  }

  /// 대화 메시지 목록 (최신순) — record 타임라인과 merge용.
  Future<List<ChatMessage>> listChatMessages({int limit = 200}) async {
    final resp = await _req(
        'GET /chat/history',
        () => http.get(Uri.parse('$baseUrl/chat/history?limit=$limit'),
            headers: authHeaders));
    if (resp.statusCode != 200) {
      throw Exception('chat/history 실패: ${resp.statusCode}');
    }
    final data = jsonDecode(utf8.decode(resp.bodyBytes));
    return ((data['items'] as List?) ?? const [])
        .cast<Map<String, dynamic>>()
        .map(ChatMessage.fromJson)
        .toList();
  }

  /// vault-relative 경로 → 전체 URL (`<baseUrl>/photos/<rel>`).
  /// 이미 절대 URL이면 그대로.
  String photoUrl(String relOrAbs) {
    if (relOrAbs.startsWith('http://') || relOrAbs.startsWith('https://')) {
      return relOrAbs;
    }
    return '$baseUrl/photos/$relOrAbs';
  }

  /// record user_comment 수정 (vault 평문은 변경 없음, Mongo만 갱신).
  Future<void> updateComment(String recordId, String newComment) async {
    final body = jsonEncode({'user_comment': newComment});
    final resp = await _req(
        'PATCH /records/$recordId',
        () => http.patch(Uri.parse('$baseUrl/records/$recordId'),
            headers: {'Content-Type': 'application/json', ...authHeaders},
            body: body),
        sent: body);
    if (resp.statusCode != 200) {
      throw Exception('record 수정 실패: ${resp.statusCode} ${resp.body}');
    }
  }

  /// 홈 표지 — 오늘 요약·어제 한 줄·신호 brief·그날의 오늘 (조회 전용, 빠름).
  /// [date]=YYYY-MM-DD 주면 그날 표지(달력으로 지난 날 재현), 없으면 오늘.
  Future<Map<String, dynamic>> fetchHomeCover({String? date}) async {
    final qp = (date != null && date.isNotEmpty) ? '?date=$date' : '';
    final resp = await _req('GET /home/cover$qp',
        () => http.get(Uri.parse('$baseUrl/home/cover$qp'), headers: authHeaders));
    if (resp.statusCode != 200) {
      throw Exception('home/cover 실패: ${resp.statusCode}');
    }
    return jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
  }

  /// 데스크 — 처리 대시보드 (당장 처리·대신 읽어드림·오래 못 챙긴 사람·오늘 정리).
  Future<Map<String, dynamic>> fetchDashboard() async {
    final resp = await _req('GET /dashboard',
        () => http.get(Uri.parse('$baseUrl/dashboard'), headers: authHeaders));
    if (resp.statusCode != 200) {
      throw Exception('dashboard 실패: ${resp.statusCode}');
    }
    return jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
  }

  /// 데스크 항목 확인 처리 — 재조회 시 사라진다. key='action:...' | 'pending:...'.
  Future<void> dismissDashboard(String key) async {
    final body = jsonEncode({'key': key});
    final resp = await _req(
        'POST /dashboard/dismiss',
        () => http.post(Uri.parse('$baseUrl/dashboard/dismiss'),
            headers: {'Content-Type': 'application/json', ...authHeaders},
            body: body),
        sent: body);
    if (resp.statusCode != 200) {
      throw Exception('dismiss 실패: ${resp.statusCode}');
    }
  }

  /// companion 한마디 — event(checkin/arrive_home 등) → {speaker, text, alias}.
  Future<Map<String, dynamic>> companionSay(String event,
      {String? place, String? speaker}) async {
    final body = jsonEncode({
      'event': event,
      'place': ?place,
      'speaker': ?speaker,
    });
    final resp = await _req(
        'POST /companion/say',
        () => http.post(Uri.parse('$baseUrl/companion/say'),
            headers: {'Content-Type': 'application/json', ...authHeaders},
            body: body),
        timeout: _llmTimeout,
        sent: body);
    if (resp.statusCode != 200) {
      throw Exception('companion 실패: ${resp.statusCode}');
    }
    return jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
  }

  /// 동반자 선제 멘트를 흐름에 남긴다 — 아빠가 그 멘트에 '기록'으로 답할 때.
  /// tappedAt = 알림을 탭해 들어온 순간(흐름에서 답한 기록 바로 위에 얹힘). 반환=흐름 메시지.
  Future<ChatMessage> companionAsked(String speaker, String text,
      DateTime tappedAt) async {
    final body = jsonEncode({
      'speaker': speaker,
      'text': text,
      'ts': tappedAt.millisecondsSinceEpoch,
    });
    final resp = await _req(
        'POST /companion/asked',
        () => http.post(Uri.parse('$baseUrl/companion/asked'),
            headers: {'Content-Type': 'application/json', ...authHeaders},
            body: body),
        sent: body);
    if (resp.statusCode != 200) {
      throw Exception('companion/asked 실패: ${resp.statusCode}');
    }
    return ChatMessage.fromJson(
        jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>);
  }

  // ── 장소 레지스트리 (집·작업실·자주 가는 곳) ────────────────
  /// 등록된 장소 목록 — 폰 지오펜스 동기화 + 설정 화면 표시.
  Future<List<Map<String, dynamic>>> listPlaces() async {
    final resp = await _req('GET /places',
        () => http.get(Uri.parse('$baseUrl/places'), headers: authHeaders));
    if (resp.statusCode != 200) {
      throw Exception('places 실패: ${resp.statusCode}');
    }
    final d = jsonDecode(utf8.decode(resp.bodyBytes));
    return ((d['items'] as List?) ?? const []).cast<Map<String, dynamic>>();
  }

  /// 장소 등록/수정 — WiFi 감지·수동 추가(폰) 또는 설명 편집. id 주면 그 문서 갱신.
  Future<Map<String, dynamic>> upsertPlace({
    required String name,
    String? kind,
    double? lat,
    double? lng,
    String? wifi,
    String? bt,
    String? description,
    String? id,
  }) async {
    final body = jsonEncode({
      'name': name,
      'kind': ?kind,
      'lat': ?lat,
      'lng': ?lng,
      'wifi': ?wifi,
      'bt': ?bt,
      'description': ?description,
      'id': ?id,
    });
    final resp = await _req(
        'POST /places',
        () => http.post(Uri.parse('$baseUrl/places'),
            headers: {'Content-Type': 'application/json', ...authHeaders},
            body: body),
        sent: body);
    if (resp.statusCode != 200) {
      throw Exception('place 추가 실패: ${resp.statusCode}');
    }
    return jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
  }

  Future<void> deletePlace(String id) async {
    await _req(
        'DELETE /places/$id',
        () => http.delete(Uri.parse('$baseUrl/places/${Uri.encodeComponent(id)}'),
            headers: authHeaders));
  }

  /// 위치 확인(센싱) 설정 — {poll_interval_sec, skip_on_known_wifi}. 어드민(📍 장소)에서 조정.
  Future<Map<String, dynamic>> getLocationConfig() async {
    final resp = await _req('GET /location-config',
        () => http.get(Uri.parse('$baseUrl/location-config'), headers: authHeaders));
    if (resp.statusCode != 200) {
      throw Exception('location-config 실패: ${resp.statusCode}');
    }
    final d = jsonDecode(utf8.decode(resp.bodyBytes));
    return (d['config'] as Map?)?.cast<String, dynamic>() ?? const {};
  }

  // ── 리마인더 (자체) ────────────────────────────────────────
  Future<List<Map<String, dynamic>>> listReminders(
      {bool includeDone = false}) async {
    final resp = await _req(
        'GET /reminders',
        () => http.get(
            Uri.parse('$baseUrl/reminders?include_done=$includeDone'),
            headers: authHeaders));
    if (resp.statusCode != 200) {
      throw Exception('reminders 실패: ${resp.statusCode}');
    }
    final d = jsonDecode(utf8.decode(resp.bodyBytes));
    return ((d['items'] as List?) ?? const []).cast<Map<String, dynamic>>();
  }

  /// 리마인더 추가 — 반환 id. signalId 주면 그 신호로 멱등(중복 승격 방지).
  Future<String> addReminder(String text,
      {String? due, String source = 'manual', String? signalId}) async {
    final body = jsonEncode({
      'text': text,
      'due': ?due,
      'source': source,
      'signal_id': ?signalId,
    });
    final resp = await _req(
        'POST /reminders',
        () => http.post(Uri.parse('$baseUrl/reminders'),
            headers: {'Content-Type': 'application/json', ...authHeaders},
            body: body),
        sent: body);
    if (resp.statusCode != 200) {
      throw Exception('reminder 추가 실패: ${resp.statusCode}');
    }
    return (jsonDecode(utf8.decode(resp.bodyBytes))['id'] as String?) ?? '';
  }

  Future<void> setReminderDone(String id, bool done) async {
    await _req(
        'POST /reminders/$id/done',
        () => http.post(Uri.parse('$baseUrl/reminders/$id/done'),
            headers: {'Content-Type': 'application/json', ...authHeaders},
            body: jsonEncode({'done': done})));
  }

  Future<void> removeReminder(String id) async {
    await _req(
        'DELETE /reminders/$id',
        () => http.delete(Uri.parse('$baseUrl/reminders/$id'),
            headers: authHeaders));
  }

  /// 가계부 — 오늘(또는 date) 지출 {total, count, items}.
  Future<Map<String, dynamic>> fetchLedger({String? date}) async {
    final qp = (date != null && date.isNotEmpty) ? '?date=$date' : '';
    final resp = await _req('GET /ledger$qp',
        () => http.get(Uri.parse('$baseUrl/ledger$qp'), headers: authHeaders));
    if (resp.statusCode != 200) {
      throw Exception('ledger 실패: ${resp.statusCode}');
    }
    return jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
  }

  /// 최신 발행물 (조간/석간) — 알림 폴링용. 없으면 null.
  Future<Map<String, dynamic>?> fetchBriefingLatest() async {
    final resp = await _req('GET /briefing/latest',
        () => http.get(Uri.parse('$baseUrl/briefing/latest'),
            headers: authHeaders));
    if (resp.statusCode != 200) return null;
    final d = jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
    return d.isEmpty ? null : d;
  }

  /// 건강 지표 동기화 — 오늘 걸음·어젯밤 수면(분). 있는 값만 부분 갱신.
  Future<void> syncMetrics({int? sleepMin, int? steps}) async {
    final today =
        '${DateTime.now().year.toString().padLeft(4, '0')}-${DateTime.now().month.toString().padLeft(2, '0')}-${DateTime.now().day.toString().padLeft(2, '0')}';
    await _req(
        'POST /metrics/sync',
        () => http.post(Uri.parse('$baseUrl/metrics/sync'),
            headers: {'Content-Type': 'application/json', ...authHeaders},
            body: jsonEncode(
                {'date': today, 'sleep_min': sleepMin, 'steps': steps})));
  }

  /// 신호 분류 항목 피드백 — "inaccurate"(부정확) 또는 null(해제).
  Future<void> setBriefFeedback(
      String briefId, int itemIndex, String? feedback) async {
    final resp = await _req(
        'POST /signals/brief/$briefId/feedback',
        () => http.post(
            Uri.parse('$baseUrl/signals/brief/$briefId/feedback'),
            headers: {'Content-Type': 'application/json', ...authHeaders},
            body: jsonEncode({'item_index': itemIndex, 'feedback': feedback})));
    if (resp.statusCode != 200) {
      throw Exception('feedback 실패: ${resp.statusCode}');
    }
  }

  /// 신호 로그 — 과거 요약(brief) + 원본 신호(문자·부재중) 최신순.
  Future<Map<String, dynamic>> fetchSignalsRecent() async {
    final resp = await _req('GET /signals/recent',
        () => http.get(Uri.parse('$baseUrl/signals/recent'),
            headers: authHeaders));
    if (resp.statusCode != 200) {
      throw Exception('signals/recent 실패: ${resp.statusCode}');
    }
    return jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
  }

  /// 신호 동기화 — 미읽음 SMS·부재중·앱 알림 → 백엔드 저장+로컬 LLM 분류·요약.
  /// 반환: {new_sms, new_calls, new_notif, summary} (새 신호 없으면 summary 빈 문자열).
  Future<Map<String, dynamic>> syncSignals(
      List<Map<String, dynamic>> sms, List<Map<String, dynamic>> calls,
      {List<Map<String, dynamic>> notifications = const []}) async {
    final body = jsonEncode(
        {'sms': sms, 'calls': calls, 'notifications': notifications});
    final resp = await _req(
        'POST /signals/sync',
        () => http.post(Uri.parse('$baseUrl/signals/sync'),
            headers: {'Content-Type': 'application/json', ...authHeaders},
            body: body),
        sent: body);
    if (resp.statusCode != 200) {
      throw Exception('signals 실패: ${resp.statusCode} ${resp.body}');
    }
    return jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
  }

  /// 섹션별 리액션 (analysis|comment|discovery). reaction 빈 문자열 = 해제.
  Future<void> setReaction(String recordId, String reaction,
      {String? section}) async {
    final resp = await _req(
        'POST /records/$recordId/reaction',
        () => http.post(Uri.parse('$baseUrl/records/$recordId/reaction'),
            headers: {'Content-Type': 'application/json', ...authHeaders},
            body: jsonEncode({
              'reaction': reaction,
              'section': ?section,
            })));
    if (resp.statusCode != 200) {
      throw Exception('reaction 실패: ${resp.statusCode}');
    }
  }
}

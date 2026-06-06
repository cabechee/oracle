import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import 'applog.dart';
import 'models.dart';

class OracleApi {
  final String baseUrl;

  OracleApi({String? baseUrl})
      : baseUrl = baseUrl ??
            const String.fromEnvironment(
              'ORACLE_API',
              defaultValue: 'http://chocolat.tail575fea.ts.net:8001',
            );

  // 타임아웃 — LLM 경유(ingest/query/digest)는 길게, 단순 조회는 짧게.
  static const _ingestTimeout = Duration(seconds: 120);
  static const _llmTimeout = Duration(seconds: 120);
  static const _getTimeout = Duration(seconds: 15);

  static String _short(String s) =>
      s.length > 200 ? '${s.substring(0, 200)}…' : s;

  /// 공통 HTTP 래퍼 — 타임아웃 + 구조적 로깅(요청·상태·소요·에러종류).
  Future<http.Response> _req(
    String label,
    Future<http.Response> Function() send, {
    Duration timeout = _getTimeout,
  }) async {
    final sw = Stopwatch()..start();
    try {
      final r = await send().timeout(timeout);
      final ms = sw.elapsedMilliseconds;
      if (r.statusCode >= 400) {
        AppLog.err('$label → HTTP ${r.statusCode} (${ms}ms) ${_short(r.body)}');
      } else {
        AppLog.info('$label → ${r.statusCode} (${ms}ms)');
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
    File? imageFile,
    File? audioFile,
    File? videoFile,
    String? model,
  }) async {
    final uri = Uri.parse('$baseUrl/ingest');
    final req = http.MultipartRequest('POST', uri);
    if (comment != null && comment.isNotEmpty) req.fields['comment'] = comment;
    if (model != null && model.isNotEmpty) req.fields['model'] = model;
    if (imageFile != null) {
      req.files.add(await http.MultipartFile.fromPath('file', imageFile.path));
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
        'GET /digest/list', () => http.get(Uri.parse('$baseUrl/digest/list')));
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
        () => http.get(Uri.parse('$baseUrl/digest/$dateStr')));
    if (resp.statusCode != 200) {
      throw Exception('digest 실패: ${resp.statusCode}');
    }
    final data = jsonDecode(utf8.decode(resp.bodyBytes));
    return (data['text'] as String?) ?? '';
  }

  /// 상위 인덱스 vault master.md 본문.
  Future<String> getMasterIndex() async {
    final resp = await _req('GET /index/master',
        () => http.get(Uri.parse('$baseUrl/index/master')));
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
        'GET /index/meta', () => http.get(Uri.parse('$baseUrl/index/meta')));
    if (resp.statusCode != 200) {
      throw Exception('index/meta 실패: ${resp.statusCode}');
    }
    final data = jsonDecode(utf8.decode(resp.bodyBytes));
    return ((data['months'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
  }

  /// 자연어 질의 — backend query 모듈. 답변 + 참조 record_id.
  Future<QueryResult> query(String question, {int limit = 30}) async {
    final resp = await _req(
      'POST /query',
      () => http.post(Uri.parse('$baseUrl/query'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'question': question, 'limit': limit})),
      timeout: _llmTimeout,
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
        () => http.get(Uri.parse(
            '$baseUrl/threads/silent?min_days=$minDays&max_days=$maxDays')));
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
        'POST /digest/run', () => http.post(Uri.parse('$baseUrl/digest/run$qp')),
        timeout: _llmTimeout);
    if (resp.statusCode != 200) {
      throw Exception('digest/run 실패: ${resp.statusCode} ${resp.body}');
    }
    return jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
  }

  /// Nest 등록 모델 + council 목록. AppBar 모델 선택용.
  Future<LlmCatalog> listLlmModels() async {
    final resp = await _req(
        'GET /llm/models', () => http.get(Uri.parse('$baseUrl/llm/models')));
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
        () => http
            .get(Uri.parse('$baseUrl/records?limit=$limit&offset=$offset')));
    if (resp.statusCode != 200) {
      throw Exception('records 실패: ${resp.statusCode}');
    }
    final data = jsonDecode(utf8.decode(resp.bodyBytes));
    final items = (data['items'] as List).cast<Map<String, dynamic>>();
    return items.map(Record.fromMongo).toList();
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
    final resp = await _req(
        'PATCH /records/$recordId',
        () => http.patch(Uri.parse('$baseUrl/records/$recordId'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'user_comment': newComment})));
    if (resp.statusCode != 200) {
      throw Exception('record 수정 실패: ${resp.statusCode} ${resp.body}');
    }
  }

  Future<void> setReaction(String recordId, String reaction) async {
    final resp = await _req(
        'POST /records/$recordId/reaction',
        () => http.post(Uri.parse('$baseUrl/records/$recordId/reaction'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'reaction': reaction})));
    if (resp.statusCode != 200) {
      throw Exception('reaction 실패: ${resp.statusCode}');
    }
  }
}

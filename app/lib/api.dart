import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import 'models.dart';

class OracleApi {
  final String baseUrl;

  OracleApi({String? baseUrl})
      : baseUrl = baseUrl ??
            const String.fromEnvironment(
              'ORACLE_API',
              defaultValue: 'http://chocolat.tail575fea.ts.net:8001',
            );

  Future<Record> ingest({
    String? comment,
    File? imageFile,
    String? model,
  }) async {
    final uri = Uri.parse('$baseUrl/ingest');
    final req = http.MultipartRequest('POST', uri);
    if (comment != null && comment.isNotEmpty) {
      req.fields['comment'] = comment;
    }
    if (model != null && model.isNotEmpty) {
      req.fields['model'] = model;
    }
    if (imageFile != null) {
      req.files
          .add(await http.MultipartFile.fromPath('file', imageFile.path));
    }
    final streamed = await req.send();
    final resp = await http.Response.fromStream(streamed);
    if (resp.statusCode != 200) {
      throw Exception('ingest 실패: ${resp.statusCode} ${resp.body}');
    }
    return Record.fromIngest(jsonDecode(utf8.decode(resp.bodyBytes)));
  }

  /// 자정 배치로 생성된 다이제스트 목록 (최신순).
  Future<List<DigestEntry>> listDigests() async {
    final uri = Uri.parse('$baseUrl/digest/list');
    final resp = await http.get(uri);
    if (resp.statusCode != 200) {
      throw Exception('digest/list 실패: ${resp.statusCode}');
    }
    final data = jsonDecode(utf8.decode(resp.bodyBytes));
    final items = (data['items'] as List).cast<Map<String, dynamic>>();
    return items.map(DigestEntry.fromJson).toList();
  }

  /// 특정 날짜의 다이제스트 마크다운 본문.
  Future<String> getDigest(String dateStr) async {
    final uri = Uri.parse('$baseUrl/digest/$dateStr');
    final resp = await http.get(uri);
    if (resp.statusCode != 200) {
      throw Exception('digest 실패: ${resp.statusCode}');
    }
    final data = jsonDecode(utf8.decode(resp.bodyBytes));
    return (data['text'] as String?) ?? '';
  }

  /// 상위 인덱스 vault master.md 본문.
  Future<String> getMasterIndex() async {
    final resp = await http.get(Uri.parse('$baseUrl/index/master'));
    if (resp.statusCode == 404) return '';
    if (resp.statusCode != 200) {
      throw Exception('index/master 실패: ${resp.statusCode}');
    }
    final data = jsonDecode(utf8.decode(resp.bodyBytes));
    return (data['text'] as String?) ?? '';
  }

  /// MongoDB index_meta (월별 가벼운 구조).
  Future<List<Map<String, dynamic>>> getIndexMeta() async {
    final resp = await http.get(Uri.parse('$baseUrl/index/meta'));
    if (resp.statusCode != 200) {
      throw Exception('index/meta 실패: ${resp.statusCode}');
    }
    final data = jsonDecode(utf8.decode(resp.bodyBytes));
    return ((data['months'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
  }

  /// 펜딩 thread (X일 무언급) 후보 목록.
  Future<List<Map<String, dynamic>>> getSilentThreads({
    int minDays = 3,
    int maxDays = 30,
  }) async {
    final uri = Uri.parse(
        '$baseUrl/threads/silent?min_days=$minDays&max_days=$maxDays');
    final resp = await http.get(uri);
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
    final uri = Uri.parse('$baseUrl/digest/run$qp');
    final resp = await http.post(uri);
    if (resp.statusCode != 200) {
      throw Exception('digest/run 실패: ${resp.statusCode} ${resp.body}');
    }
    return jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
  }

  /// Nest 등록 모델 + council 목록. AppBar 모델 선택용.
  Future<LlmCatalog> listLlmModels() async {
    final uri = Uri.parse('$baseUrl/llm/models');
    final resp = await http.get(uri);
    if (resp.statusCode != 200) {
      throw Exception('models 실패: ${resp.statusCode}');
    }
    return LlmCatalog.fromJson(
      jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>,
    );
  }

  Future<List<Record>> listRecent({int limit = 50, int offset = 0}) async {
    final uri = Uri.parse('$baseUrl/records?limit=$limit&offset=$offset');
    final resp = await http.get(uri);
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

  Future<void> setReaction(String recordId, String reaction) async {
    final uri = Uri.parse('$baseUrl/records/$recordId/reaction');
    final resp = await http.post(
      uri,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'reaction': reaction}),
    );
    if (resp.statusCode != 200) {
      throw Exception('reaction 실패: ${resp.statusCode}');
    }
  }
}

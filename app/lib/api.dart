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
              defaultValue: 'http://192.168.68.62:8765',
            );

  Future<Record> ingest({String? comment, File? imageFile}) async {
    final uri = Uri.parse('$baseUrl/ingest');
    final req = http.MultipartRequest('POST', uri);
    if (comment != null && comment.isNotEmpty) {
      req.fields['comment'] = comment;
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

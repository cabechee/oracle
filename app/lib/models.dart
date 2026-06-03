class Record {
  final String id;
  final DateTime ts;
  final String userComment;
  final List<String> imagePaths;
  final String? vlmCaption;
  final String insight;
  final String? reaction;

  Record({
    required this.id,
    required this.ts,
    required this.userComment,
    required this.imagePaths,
    required this.vlmCaption,
    required this.insight,
    this.reaction,
  });

  /// POST /ingest 응답 (코멘트는 클라이언트가 따로 보존)
  factory Record.fromIngest(Map<String, dynamic> j) => Record(
        id: j['record_id'] as String,
        ts: DateTime.parse(j['ts'] as String),
        userComment: '',
        imagePaths:
            (j['image_paths'] as List?)?.cast<String>() ?? const <String>[],
        vlmCaption: j['vlm_caption'] as String?,
        insight: (j['insight'] as String?) ?? '',
      );

  /// GET /records 응답 (MongoDB 문서)
  factory Record.fromMongo(Map<String, dynamic> j) {
    final vlm = j['vlm'];
    final insight = j['insight'];
    return Record(
      id: j['_id'] as String,
      ts: DateTime.parse(j['ts'] as String),
      userComment: (j['user_comment'] as String?) ?? '',
      imagePaths:
          (j['image_paths'] as List?)?.cast<String>() ?? const <String>[],
      vlmCaption: vlm is Map ? vlm['caption'] as String? : null,
      insight: insight is Map ? ((insight['text'] as String?) ?? '') : '',
      reaction: j['reaction'] as String?,
    );
  }
}


/// Nest 등록 모델 (단일)
class LlmModel {
  final String alias;
  final String name;
  final String? tier;        // local | cloud
  final String? provider;    // claude | codex | gemini | openai_compat ...
  final String? type;        // cli | api
  final String? effort;      // low/medium/high/xhigh/max
  final bool vision;

  LlmModel({
    required this.alias,
    required this.name,
    this.tier,
    this.provider,
    this.type,
    this.effort,
    required this.vision,
  });

  factory LlmModel.fromJson(Map<String, dynamic> j) => LlmModel(
        alias: j['alias'] as String,
        name: (j['name'] as String?) ?? (j['alias'] as String),
        tier: j['tier'] as String?,
        provider: j['provider'] as String?,
        type: j['type'] as String?,
        effort: j['effort'] as String?,
        vision: ((j['vision'] as int?) ?? 0) == 1,
      );
}

/// Nest council (다중 모델 합성)
class Council {
  final String alias;
  final String name;
  final List<String> members;
  final String? chairAlias;

  Council({
    required this.alias,
    required this.name,
    required this.members,
    this.chairAlias,
  });

  factory Council.fromJson(Map<String, dynamic> j) => Council(
        alias: j['alias'] as String,
        name: (j['name'] as String?) ?? (j['alias'] as String),
        members:
            ((j['member_aliases'] as List?)?.cast<String>()) ?? const <String>[],
        chairAlias: j['chair_alias'] as String?,
      );
}

/// 다이제스트 목록 항목 (GET /digest/list)
class DigestEntry {
  final String date;     // YYYY-MM-DD
  final int size;
  DigestEntry({required this.date, required this.size});
  factory DigestEntry.fromJson(Map<String, dynamic> j) => DigestEntry(
        date: j['date'] as String,
        size: (j['size'] as int?) ?? 0,
      );
}

/// /llm/models 응답 통합
class LlmCatalog {
  final List<LlmModel> models;
  final List<Council> councils;
  LlmCatalog({required this.models, required this.councils});

  factory LlmCatalog.fromJson(Map<String, dynamic> j) => LlmCatalog(
        models: ((j['models'] as List?) ?? const [])
            .map((e) => LlmModel.fromJson(e as Map<String, dynamic>))
            .toList(),
        councils: ((j['councils'] as List?) ?? const [])
            .map((e) => Council.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

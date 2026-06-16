class Record {
  final String id;
  final DateTime ts;
  final String userComment;
  final List<String> imagePaths;
  final List<String> audioPaths;        // 음성 메모 첨부 (vault-relative)
  final List<String> videoPaths;        // 영상 첨부 (vault-relative)
  final String? vlmCaption;
  final String? audioCaption;           // 소리 인식 결과 (ORACLE_AUDIO 설정 시)
  final String insight;                 // 베르(메인) 디스커버리
  final String? quickText;              // 쿠키(서브) 빠른 한마디
  final Map<String, dynamic>? quickAction; // 쿠키가 감지한 액션 {tool,seconds,label}
  final String? suggestion;             // 디스커버리 제안 (사진 3단계)
  final Map<String, dynamic>? analysis; // 사진 분석 JSON (사진 3단계 1단계)
  final String? reaction;               // legacy 단일 (구 record 표시 호환)
  final Map<String, String> reactions;  // 섹션별: analysis|comment|discovery → 값
  final String status;                  // processing | done | failed (구 record는 done)
  final List<Map<String, dynamic>> reprocessLog; // 재처리 이력 [{part, at}]
  final bool backfill;                  // 지나간 사진 (EXIF 촬영시각으로 들어옴)

  Record({
    required this.id,
    required this.ts,
    required this.userComment,
    required this.imagePaths,
    required this.vlmCaption,
    required this.insight,
    this.audioPaths = const [],
    this.videoPaths = const [],
    this.audioCaption,
    this.quickText,
    this.quickAction,
    this.suggestion,
    this.analysis,
    this.reaction,
    this.reactions = const {},
    this.status = 'done',
    this.reprocessLog = const [],
    this.backfill = false,
  });

  bool get isProcessing => status == 'processing';

  /// POST /ingest 응답 (코멘트는 클라이언트가 따로 보존)
  factory Record.fromIngest(Map<String, dynamic> j) => Record(
        id: j['record_id'] as String,
        ts: DateTime.parse(j['ts'] as String),
        userComment: '',
        imagePaths:
            (j['image_paths'] as List?)?.cast<String>() ?? const <String>[],
        audioPaths:
            (j['audio_paths'] as List?)?.cast<String>() ?? const <String>[],
        videoPaths:
            (j['video_paths'] as List?)?.cast<String>() ?? const <String>[],
        vlmCaption: j['vlm_caption'] as String?,
        audioCaption: j['audio_caption'] as String?,
        insight: (j['insight'] as String?) ?? '',
        quickText: _quickText(j['quick']),
        quickAction: _quickAction(j['quick']),
        suggestion: j['suggestion'] as String?,
        analysis: _asMap(j['analysis']),
        status: (j['status'] as String?) ?? 'done',
      );

  /// GET /records 응답 (MongoDB 문서)
  factory Record.fromMongo(Map<String, dynamic> j) {
    final vlm = j['vlm'];
    final audio = j['audio'];
    final insight = j['insight'];
    return Record(
      id: j['_id'] as String,
      ts: DateTime.parse(j['ts'] as String),
      userComment: (j['user_comment'] as String?) ?? '',
      imagePaths:
          (j['image_paths'] as List?)?.cast<String>() ?? const <String>[],
      audioPaths:
          (j['audio_paths'] as List?)?.cast<String>() ?? const <String>[],
      videoPaths:
          (j['video_paths'] as List?)?.cast<String>() ?? const <String>[],
      vlmCaption: vlm is Map ? vlm['caption'] as String? : null,
      audioCaption: audio is Map ? audio['caption'] as String? : null,
      insight: insight is Map ? ((insight['text'] as String?) ?? '') : '',
      quickText: _quickText(j['quick']),
      quickAction: _quickAction(j['quick']),
      suggestion: j['suggestion'] as String?,
      analysis: _asMap(j['analysis']),
      reaction: j['reaction'] as String?,
      reactions: _reactionMap(j['reactions']),
      status: (j['status'] as String?) ?? 'done',
      reprocessLog: ((j['reprocess_log'] as List?) ?? const [])
          .whereType<Map>()
          .map((e) => e.cast<String, dynamic>())
          .toList(),
      backfill: j['backfill'] == true,
    );
  }

  /// JSON 객체를 안전하게 `Map<String, dynamic>`로 (아니면 null).
  static Map<String, dynamic>? _asMap(dynamic v) =>
      v is Map ? v.cast<String, dynamic>() : null;

  /// quick {alias, text, action} → text만 (없으면 null).
  static String? _quickText(dynamic v) {
    if (v is Map) {
      final t = v['text'];
      return (t is String && t.trim().isNotEmpty) ? t : null;
    }
    return null;
  }

  /// quick.action → Map (없으면 null).
  static Map<String, dynamic>? _quickAction(dynamic v) =>
      (v is Map && v['action'] is Map)
          ? (v['action'] as Map).cast<String, dynamic>()
          : null;

  /// reactions JSON → 값 있는 항목만 `Map<String, String>`.
  static Map<String, String> _reactionMap(dynamic v) {
    if (v is! Map) return const {};
    return {
      for (final e in v.entries)
        if (e.value is String && (e.value as String).isNotEmpty)
          e.key.toString(): e.value as String,
    };
  }

  /// 일부 필드만 바꾼 복제본 (리액션·코멘트 편집용).
  Record copyWith({
    String? userComment,
    String? reaction,
    Map<String, String>? reactions,
  }) =>
      Record(
        id: id,
        ts: ts,
        userComment: userComment ?? this.userComment,
        imagePaths: imagePaths,
        audioPaths: audioPaths,
        videoPaths: videoPaths,
        vlmCaption: vlmCaption,
        audioCaption: audioCaption,
        insight: insight,
        quickText: quickText,
        quickAction: quickAction,
        suggestion: suggestion,
        analysis: analysis,
        reaction: reaction ?? this.reaction,
        reactions: reactions ?? this.reactions,
        status: status,
        reprocessLog: reprocessLog,
        backfill: backfill,
      );
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

/// 대화 모드 메시지 (POST /chat · GET /chat/history)
class ChatMessage {
  final String id;
  final String role;               // user | assistant
  final String text;               // 베르(assistant) 본문
  final DateTime ts;
  final List<String> referenced;   // 근거 record_id (assistant)
  final String? quickText;         // 쿠키 첨언 (assistant)
  final String? speaker;           // 동반자 화자 (베르|쿠키) — companion 선제 멘트
  final bool isCompanion;          // 동반자가 먼저 건 말 (대화 응답과 구분)

  ChatMessage({
    required this.id,
    required this.role,
    required this.text,
    required this.ts,
    this.referenced = const [],
    this.quickText,
    this.speaker,
    this.isCompanion = false,
  });

  bool get isUser => role == 'user';

  factory ChatMessage.fromJson(Map<String, dynamic> j) => ChatMessage(
        id: j['_id'] as String,
        role: (j['role'] as String?) ?? 'assistant',
        text: (j['text'] as String?) ?? '',
        ts: DateTime.parse(j['ts'] as String),
        referenced:
            (j['referenced'] as List?)?.cast<String>() ?? const <String>[],
        quickText: Record._quickText(j['quick']),
        speaker: (j['speaker'] as String?)?.trim().isNotEmpty == true
            ? (j['speaker'] as String).trim()
            : null,
        isCompanion: j['companion'] == true,
      );
}

/// 자연어 질의 응답 (POST /query)
class QueryResult {
  final String answer;
  final List<String> referenced;   // record_id 배열
  final String? alias;             // 사용된 LLM alias
  QueryResult({
    required this.answer,
    required this.referenced,
    this.alias,
  });
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

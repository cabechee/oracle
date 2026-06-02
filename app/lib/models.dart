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

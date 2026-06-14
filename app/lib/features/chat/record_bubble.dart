import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import '../../api.dart';
import '../../core/design.dart';
import '../../models.dart';
import '../actions/capture_action.dart';

/// 타임라인의 record 엔트리 — 버블 없는 에디토리얼 문법.
/// 사진은 흰 마진의 인화지, 유저 글은 고딕 잉크, 동반자는 여백의 방주(※).
/// 타임스탬프는 스파인 레일(chat_list)이 그린다.
class RecordBubble extends StatelessWidget {
  final Record record;
  final OracleApi api;
  final Future<void> Function(String section, String value) onReact;
  const RecordBubble({
    super.key,
    required this.record,
    required this.api,
    required this.onReact,
  });

  // 즉답 코멘트(comment)만 좋아/싫어 — 무반응이 곧 중립(그저그래 없음).
  // 디스커버리·분석은 목적이 달라 기존 3값 유지:
  //   discovery=발견 가치(흥미로워≠이미 알아≠관심없어), analysis=분석 정확도.
  static const _commentSet = [('좋아', 'like'), ('싫어', 'dislike')];
  static const _discoverySet = [
    ('흥미로워', 'interesting'), ('이미 알아', 'known'), ('관심없어', 'skip')
  ];
  static const _analysisSet = [
    ('정확해', 'accurate'), ('부족해', 'lacking'), ('틀렸어', 'wrong')
  ];

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (record.backfill)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Text('◆ 지난 사진 (나중에 올림 · 촬영 날짜로 정렬)',
                style: OracleType.marginalia
                    .copyWith(color: OracleColors.vermilion)),
          ),
        if (record.imagePaths.isNotEmpty) _photoPrint(context),
        // 사진 캡션 — 1단계 분석 요약(장면·객체·글자) + 분석 정확도 피드백.
        // (피드백을 분석 바로 아래 두어, 멀리 떨어진 상세 접이와 분리)
        if (record.imagePaths.isNotEmpty &&
            (record.vlmCaption ?? '').trim().isNotEmpty) ...[
          Padding(
            padding: const EdgeInsets.only(top: OracleSpace.inPhoto),
            child: _ExpandableCaption(record.vlmCaption!.trim()),
          ),
          if (record.analysis != null && record.analysis!.isNotEmpty)
            _reactRow('analysis', _analysisSet, left: 0),
        ],
        if (record.audioPaths.isNotEmpty || record.videoPaths.isNotEmpty)
          Padding(
            padding: EdgeInsets.only(
                top: record.imagePaths.isNotEmpty ? OracleSpace.inPhoto : 0),
            child: Row(
              children: [
                if (record.audioPaths.isNotEmpty) _mediaMark('음성 메모'),
                if (record.videoPaths.isNotEmpty) _mediaMark('영상'),
              ],
            ),
          ),
        if (record.userComment.isNotEmpty)
          Padding(
            padding: EdgeInsets.only(
                top: (record.imagePaths.isNotEmpty ||
                        record.audioPaths.isNotEmpty ||
                        record.videoPaths.isNotEmpty)
                    ? OracleSpace.inBlock
                    : 0),
            child: Text(record.userComment, style: OracleType.userBody),
          ),
        if ((record.audioCaption ?? '').trim().isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: OracleSpace.inPhoto),
            child: Text(
              '소리 — ${record.audioCaption!.trim()}',
              style: OracleType.timestamp,
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
            ),
          ),
        if (record.isProcessing)
          Padding(
            padding: const EdgeInsets.only(top: OracleSpace.inBlock),
            child: Row(
              children: [
                const SizedBox(
                  width: 10,
                  height: 10,
                  child: CircularProgressIndicator(
                      strokeWidth: 1, color: OracleColors.faint),
                ),
                const SizedBox(width: 8),
                Text('현상 중',
                    style: OracleType.marginalia
                        .copyWith(color: OracleColors.faint)),
              ],
            ),
          ),
        // 쿠키(오목눈이) 빠른 한마디 — 베르보다 먼저 도착, 짧고 발랄.
        if ((record.quickText ?? '').isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(
                top: OracleSpace.inBlock, left: OracleSpace.gutter),
            child: quickNote(record.quickText!, seed: record.id),
          ),
        // 쿠키가 사진/메모에서 감지한 액션 — 원탭 제안 (불확실하니 자동 X)
        if (record.quickAction != null)
          Builder(builder: (ctx) {
            final a = CaptureAction.fromJson(record.quickAction);
            if (a == null) return const SizedBox.shrink();
            return Padding(
              padding: const EdgeInsets.only(
                  top: 6, left: OracleSpace.gutter + 25),
              child: _actionChip(ctx, a),
            );
          }),
        if (record.insight.isNotEmpty) ...[
          Padding(
            padding: const EdgeInsets.only(
                top: OracleSpace.inBlock, left: OracleSpace.gutter),
            child: marginaliaNote(record.insight),
          ),
          _reactRow('comment', _commentSet),
          if ((record.suggestion ?? '').trim().isNotEmpty) ...[
            Padding(
              padding: const EdgeInsets.only(
                  top: OracleSpace.inBlock, left: OracleSpace.gutter + 17),
              child: Text(
                record.suggestion!.trim(),
                style: OracleType.marginalia
                    .copyWith(color: OracleColors.gray),
              ),
            ),
            _reactRow('discovery', _discoverySet),
          ],
          // 분석 상세(접이) — 피드백은 위 캡션 옆으로 옮김
          if (record.analysis != null && record.analysis!.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(
                  top: OracleSpace.inBlock, left: OracleSpace.gutter + 17),
              child: _AnalysisFold(analysis: record.analysis!),
            ),
        ],
        // 재처리 이력 — 내용이 이상해서 다시 돌린 기록(문제 있던 표시).
        if (record.reprocessLog.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6, left: OracleSpace.gutter),
            child: Text(
              '♻ 재처리됨 · ${record.reprocessLog.length}회',
              style:
                  OracleType.marginalia.copyWith(color: OracleColors.faint),
            ),
          ),
      ],
    );
  }

  /// 섹션 바로 아래 붙는 잔잔한 반응 행 — 단어 버튼, 선택=주홍.
  Widget _reactRow(String section, List<(String, String)> options,
      {double left = OracleSpace.gutter + 17}) {
    return Padding(
      padding: EdgeInsets.only(top: 4, left: left),
      child: Row(
        children: [
          for (var i = 0; i < options.length; i++) ...[
            if (i > 0) const SizedBox(width: 18),
            _reactWord(section, options[i].$1, options[i].$2),
          ],
        ],
      ),
    );
  }

  Widget _photoPrint(BuildContext context) {
    final n = record.imagePaths.length;
    final front = Container(
      color: OracleColors.mat,
      padding: const EdgeInsets.all(4),
      foregroundDecoration: BoxDecoration(
        border: Border.all(color: OracleColors.matBorder, width: 0.5),
      ),
      child: Image.network(
        api.photoUrl(record.imagePaths.first),
        headers: api.photoHeaders,
        width: 232,
        height: 154,
        fit: BoxFit.cover,
        errorBuilder: (_, _, _) => Container(
          width: 208,
          height: 138,
          color: OracleColors.photo,
        ),
        loadingBuilder: (ctx, child, progress) => progress == null
            ? child
            : Container(width: 232, height: 154, color: OracleColors.photo),
      ),
    );
    if (n <= 1) {
      return GestureDetector(
          onTap: () => _showPhotos(context, 0), child: front);
    }
    // 여러 장 — 뒤에 지그재그 스택 카드 + 우하단 "N장" 배지
    Widget stackCard(double dx, double dy) => Positioned(
          left: dx,
          top: dy,
          child: Container(
            width: 240,
            height: 162,
            color: OracleColors.mat,
            foregroundDecoration: BoxDecoration(
              border: Border.all(color: OracleColors.matBorder, width: 0.5),
            ),
          ),
        );
    return GestureDetector(
      onTap: () => _showPhotos(context, 0),
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          if (n > 2) stackCard(10, 10),
          stackCard(5, 5),
          front,
          Positioned(
            right: 8,
            bottom: 8,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              color: Colors.black54,
              child: Text('$n장',
                  style: OracleType.label.copyWith(color: OracleColors.paper)),
            ),
          ),
        ],
      ),
    );
  }

  /// 사진 풀스크린 — 핀치 확대(InteractiveViewer), 탭/스와이프로 닫기.
  void _showPhotos(BuildContext context, int initial) {
    final paths = record.imagePaths;
    Navigator.of(context).push(PageRouteBuilder(
      opaque: false,
      barrierColor: Colors.black,
      pageBuilder: (_, _, _) => _PhotoViewer(api: api, paths: paths),
    ));
  }

  Widget _mediaMark(String label) => Padding(
        padding: const EdgeInsets.only(right: 12),
        child: Text(label,
            style: OracleType.timestamp
                .copyWith(decoration: TextDecoration.underline,
                    decorationColor: OracleColors.hairline)),
      );

  /// 사진 추론 액션 제안 칩 — 탭하면 시계앱이 값을 채운 채 열려 조정·시작
  /// (사진 추정은 정확하지 않을 수 있으니 자동 시작 대신 확인).
  Widget _actionChip(BuildContext context, CaptureAction a) {
    return InkWell(
      onTap: () => runCaptureAction(a, skipUi: false),
      borderRadius: BorderRadius.circular(99),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          border: Border.all(color: OracleColors.vermilion),
          borderRadius: BorderRadius.circular(99),
        ),
        child: Text(a.label_,
            style: OracleType.label.copyWith(
                color: OracleColors.vermilion, fontSize: 12)),
      ),
    );
  }

  Widget _reactWord(String section, String word, String key) {
    final selected = record.reactions[section] == key;
    // 좋아=주홍(강조), 싫어=잉크(중립) — 같은 색이면 무엇을 골랐는지 헷갈림.
    final selColor =
        key == 'dislike' ? OracleColors.ink : OracleColors.vermilion;
    return InkWell(
      onTap: () => onReact(section, key),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Text(
          word,
          style: TextStyle(
            fontFamily: OracleType.sans,
            fontSize: 12.5,
            height: 16 / 12.5,
            letterSpacing: 0.2,
            color: selected ? selColor : OracleColors.faint,
          ),
        ),
      ),
    );
  }
}

/// 사진 분석 캡션 — 기본 3줄 말줄임, 탭하면 전체 펼침/접기.
class _ExpandableCaption extends StatefulWidget {
  final String text;
  const _ExpandableCaption(this.text);
  @override
  State<_ExpandableCaption> createState() => _ExpandableCaptionState();
}

class _ExpandableCaptionState extends State<_ExpandableCaption> {
  bool _expanded = false;
  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () => setState(() => _expanded = !_expanded),
      child: SizedBox(
        width: 240,
        child: Text(
          widget.text,
          style: OracleType.timestamp,
          maxLines: _expanded ? null : 3,
          overflow:
              _expanded ? TextOverflow.visible : TextOverflow.ellipsis,
        ),
      ),
    );
  }
}

/// 쿠키(오목눈이) 한마디 — 발랄·짧음. 베르(고운바탕 방주)와 화자 구분:
/// 산세리프 + 캐릭터 아바타. seed(기록·메시지 id)로 12종 중 하나를 고정 배정
/// — 새 메시지마다 다른 새, 스크롤·리빌드해도 같은 메시지는 같은 새. record/대화 공용.
Widget quickNote(String text, {String seed = ''}) {
  final n = (seed.hashCode.abs() % 12) + 1;
  final asset = 'assets/cookies/cookie_${n.toString().padLeft(2, '0')}.png';
  return Row(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Image.asset(asset,
          width: 26, height: 26, filterQuality: FilterQuality.medium),
      const SizedBox(width: 7),
      Expanded(
        child: Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text(text,
              style: const TextStyle(
                  fontFamily: OracleType.sans,
                  fontSize: 13,
                  height: 20 / 13,
                  letterSpacing: -0.1,
                  color: OracleColors.gray)),
        ),
      ),
    ],
  );
}

/// 방주 — 동반자의 여백 메모. ※표 + 고운바탕 회잉크. record/검색/대화 공용.
Widget marginaliaNote(String markdown) {
  return Row(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text('※',
          style: OracleType.marginalia.copyWith(
            color: OracleColors.vermilion,
            fontSize: 11,
            height: 22 / 11,
          )),
      const SizedBox(width: 8),
      Expanded(child: MarkdownBody(data: markdown, styleSheet: marginaliaMd())),
    ],
  );
}

MarkdownStyleSheet marginaliaMd() => MarkdownStyleSheet(
      p: OracleType.marginalia,
      strong: OracleType.marginalia.copyWith(fontWeight: FontWeight.w700),
      em: OracleType.marginalia,
      listBullet: OracleType.marginalia,
      code: OracleType.timestamp.copyWith(color: OracleColors.marginalia),
      blockquote: OracleType.marginalia,
      h1: OracleType.marginalia.copyWith(fontWeight: FontWeight.w700),
      h2: OracleType.marginalia.copyWith(fontWeight: FontWeight.w700),
      h3: OracleType.marginalia.copyWith(fontWeight: FontWeight.w700),
    );

/// 유저 발화 (대화·검색 컨텍스트) — 우측 정렬 고딕, 배경 없음.
Widget userBubble(BuildContext context, String text) {
  return Align(
    alignment: Alignment.centerRight,
    child: ConstrainedBox(
      constraints: BoxConstraints(
        maxWidth: MediaQuery.of(context).size.width * 0.78,
      ),
      child: Text(
        text,
        textAlign: TextAlign.right,
        style: OracleType.userBody.copyWith(fontWeight: FontWeight.w600),
      ),
    ),
  );
}

/// 음성·영상 첨부 표시 (pending 공용).
Widget mediaChip(BuildContext context, String label) => Text(
      label,
      style: OracleType.timestamp.copyWith(
          decoration: TextDecoration.underline,
          decorationColor: OracleColors.hairline),
    );

/// 사진 분석 — 접힌 한 단어, 펼치면 작은 명세.
class _AnalysisFold extends StatefulWidget {
  final Map<String, dynamic> analysis;
  const _AnalysisFold({required this.analysis});

  @override
  State<_AnalysisFold> createState() => _AnalysisFoldState();
}

class _AnalysisFoldState extends State<_AnalysisFold> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    final rows = _rows(widget.analysis);
    if (rows.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        InkWell(
          onTap: () => setState(() => _open = !_open),
          child: Text(
            _open ? '분석 접기' : '분석',
            style: OracleType.label.copyWith(color: OracleColors.faint),
          ),
        ),
        if (_open)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: rows
                  .map((r) => Padding(
                        padding: const EdgeInsets.only(bottom: 4),
                        child: RichText(
                          text: TextSpan(
                            style: OracleType.timestamp
                                .copyWith(color: OracleColors.gray),
                            children: [
                              TextSpan(
                                  text: '${r.$1}  ',
                                  style: OracleType.label),
                              TextSpan(text: r.$2),
                            ],
                          ),
                        ),
                      ))
                  .toList(),
            ),
          ),
      ],
    );
  }

  List<(String, String)> _rows(Map<String, dynamic> a) {
    final out = <(String, String)>[];
    final used = <String>{};
    String s(dynamic v) => (v ?? '').toString().trim();

    final scene = s(a['scene']);
    if (scene.isNotEmpty) out.add(('장면', scene));
    used.add('scene');

    final objs = a['objects'];
    if (objs is List && objs.isNotEmpty) {
      out.add(('객체', objs.map((e) => e.toString()).join(', ')));
    }
    used.add('objects');

    final attrs = a['attributes'];
    if (attrs is Map && attrs.isNotEmpty) {
      final parts = attrs.entries
          .map((e) => '${e.key}: ${_val(e.value)}')
          .where((x) => x.trim().endsWith(':') == false)
          .toList();
      if (parts.isNotEmpty) out.add(('속성', parts.join(' · ')));
    }
    used.add('attributes');

    final rels = a['relationships'];
    if (rels is List && rels.isNotEmpty) {
      out.add(('관계', rels.map((e) => e.toString()).join(', ')));
    }
    used.add('relationships');

    final ocr = s(a['ocr_text']);
    if (ocr.isNotEmpty) out.add(('글자', ocr));
    used.add('ocr_text');

    for (final e in a.entries) {
      if (used.contains(e.key)) continue;
      final v = _val(e.value);
      if (v.trim().isNotEmpty) out.add((e.key, v));
    }
    return out;
  }

  String _val(dynamic v) {
    if (v is Map) return v.entries.map((e) => '${e.key} ${e.value}').join(', ');
    if (v is List) return v.map((e) => e.toString()).join(', ');
    return v?.toString() ?? '';
  }
}

/// 사진 풀스크린 뷰어 — 핀치/더블탭 확대, 좌우 스와이프(여러 장), 탭/뒤로 닫기.
class _PhotoViewer extends StatefulWidget {
  final OracleApi api;
  final List<String> paths;
  const _PhotoViewer({required this.api, required this.paths});
  @override
  State<_PhotoViewer> createState() => _PhotoViewerState();
}

class _PhotoViewerState extends State<_PhotoViewer> {
  late final PageController _pc = PageController();

  @override
  void dispose() {
    _pc.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        children: [
          PageView.builder(
            controller: _pc,
            itemCount: widget.paths.length,
            itemBuilder: (_, i) => InteractiveViewer(
              minScale: 1,
              maxScale: 5,
              child: Center(
                child: Image.network(
                  widget.api.photoUrl(widget.paths[i]),
                  headers: widget.api.photoHeaders,
                  fit: BoxFit.contain,
                  errorBuilder: (_, _, _) => const Icon(Icons.broken_image,
                      color: Colors.white24, size: 48),
                ),
              ),
            ),
          ),
          // 닫기
          Positioned(
            top: MediaQuery.of(context).padding.top + 8,
            right: 8,
            child: IconButton(
              icon: const Icon(Icons.close, color: Colors.white),
              onPressed: () => Navigator.of(context).pop(),
            ),
          ),
          if (widget.paths.length > 1)
            Positioned(
              bottom: 24,
              left: 0,
              right: 0,
              child: Center(
                child: Text('${widget.paths.length}장 · 좌우로 넘기기',
                    style: const TextStyle(color: Colors.white54, fontSize: 12)),
              ),
            ),
        ],
      ),
    );
  }
}

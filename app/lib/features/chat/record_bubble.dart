import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:intl/intl.dart';

import '../../api.dart';
import '../../models.dart';

/// 채팅 타임라인의 record 카드 — 사진 · 코멘트 · 인사이트 · 💡제안 · 🔍분석 · 리액션.
class RecordBubble extends StatelessWidget {
  final Record record;
  final OracleApi api;
  final Future<void> Function(String) onReact;
  const RecordBubble({
    super.key,
    required this.record,
    required this.api,
    required this.onReact,
  });

  @override
  Widget build(BuildContext context) {
    final tsLocal = record.ts.toLocal();
    final tsStr = DateFormat('M/d HH:mm').format(tsLocal);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            tsStr,
            style: Theme.of(context)
                .textTheme
                .bodySmall
                ?.copyWith(color: Colors.grey),
          ),
          const SizedBox(height: 4),
          if (record.imagePaths.isNotEmpty)
            Align(
              alignment: Alignment.centerRight,
              child: Wrap(
                alignment: WrapAlignment.end,
                spacing: 4,
                runSpacing: 4,
                children: record.imagePaths.map((rel) {
                  return ClipRRect(
                    borderRadius: BorderRadius.circular(10),
                    child: Image.network(
                      api.photoUrl(rel),
                      width: 160,
                      height: 160,
                      fit: BoxFit.cover,
                      errorBuilder: (_, _, _) => Container(
                        width: 160,
                        height: 160,
                        color: Theme.of(context)
                            .colorScheme
                            .surfaceContainerHighest,
                        child: const Center(child: Text('📷')),
                      ),
                      loadingBuilder: (ctx, child, progress) =>
                          progress == null
                              ? child
                              : Container(
                                  width: 160,
                                  height: 160,
                                  color: Theme.of(context)
                                      .colorScheme
                                      .surfaceContainerHighest,
                                  child: const Center(
                                    child: SizedBox(
                                      width: 22,
                                      height: 22,
                                      child: CircularProgressIndicator(
                                          strokeWidth: 2),
                                    ),
                                  ),
                                ),
                    ),
                  );
                }).toList(),
              ),
            ),
          if (record.userComment.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: userBubble(context, record.userComment),
            ),
          if (record.insight.isNotEmpty) ...[
            const SizedBox(height: 6),
            Align(
              alignment: Alignment.centerLeft,
              child: ConstrainedBox(
                constraints: BoxConstraints(
                  maxWidth: MediaQuery.of(context).size.width * 0.82,
                ),
                child: Container(
                  padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
                  decoration: BoxDecoration(
                    color: Theme.of(context)
                        .colorScheme
                        .surfaceContainerHighest,
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: MarkdownBody(
                    data: record.insight,
                    selectable: true,
                  ),
                ),
              ),
            ),
            if ((record.suggestion ?? '').trim().isNotEmpty)
              _suggestionBubble(context, record.suggestion!.trim()),
            if (record.analysis != null && record.analysis!.isNotEmpty)
              _analysisPanel(context, record.analysis!),
            Padding(
              padding: const EdgeInsets.only(top: 4, left: 6),
              child: Row(
                children: [
                  _reactChip(context, '🤔', 'interesting',
                      record.reaction == 'interesting'),
                  _reactChip(context, '👍', 'useful',
                      record.reaction == 'useful'),
                  _reactChip(
                      context, '💤', 'skip', record.reaction == 'skip'),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _reactChip(
      BuildContext context, String emoji, String key, bool selected) {
    return Padding(
      padding: const EdgeInsets.only(right: 6),
      child: InkWell(
        onTap: () => onReact(key),
        borderRadius: BorderRadius.circular(12),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
          decoration: BoxDecoration(
            color: selected
                ? Theme.of(context).colorScheme.primaryContainer
                : Colors.transparent,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Theme.of(context).dividerColor),
          ),
          child: Text(emoji, style: const TextStyle(fontSize: 14)),
        ),
      ),
    );
  }
}

/// 유저 발화 버블 (우측, primary). record/pending 양쪽에서 공용.
Widget userBubble(BuildContext context, String text) {
  final cs = Theme.of(context).colorScheme;
  return Align(
    alignment: Alignment.centerRight,
    child: ConstrainedBox(
      constraints: BoxConstraints(
        maxWidth: MediaQuery.of(context).size.width * 0.78,
      ),
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 2),
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
        decoration: BoxDecoration(
          color: cs.primary,
          borderRadius: BorderRadius.circular(14),
        ),
        child: Text(text, style: TextStyle(color: cs.onPrimary)),
      ),
    ),
  );
}

/// 디스커버리 제안 — 코멘트(중립 버블)와 구분되는 액센트 버블.
Widget _suggestionBubble(BuildContext context, String text) {
  final cs = Theme.of(context).colorScheme;
  return Padding(
    padding: const EdgeInsets.only(top: 6),
    child: Align(
      alignment: Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.82,
        ),
        child: Container(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
          decoration: BoxDecoration(
            color: cs.primaryContainer,
            borderRadius: BorderRadius.circular(14),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '💡 제안',
                style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      color: cs.onPrimaryContainer,
                      fontWeight: FontWeight.bold,
                    ),
              ),
              const SizedBox(height: 2),
              SelectableText(
                text,
                style: TextStyle(color: cs.onPrimaryContainer),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

/// 사진 분석 JSON — 접이식 패널. 비어있는 필드는 생략.
Widget _analysisPanel(BuildContext context, Map<String, dynamic> analysis) {
  final rows = _analysisRows(analysis);
  if (rows.isEmpty) return const SizedBox.shrink();
  final cs = Theme.of(context).colorScheme;
  return Padding(
    padding: const EdgeInsets.only(top: 4),
    child: Theme(
      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        dense: true,
        tilePadding: const EdgeInsets.symmetric(horizontal: 6),
        childrenPadding: const EdgeInsets.fromLTRB(10, 0, 10, 8),
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        title: Text(
          '🔍 분석',
          style: Theme.of(context)
              .textTheme
              .labelLarge
              ?.copyWith(color: cs.outline),
        ),
        children: rows
            .map(
              (r) => Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: RichText(
                  text: TextSpan(
                    style: Theme.of(context).textTheme.bodySmall,
                    children: [
                      TextSpan(
                        text: '${r.$1}  ',
                        style: TextStyle(
                          fontWeight: FontWeight.bold,
                          color: cs.outline,
                        ),
                      ),
                      TextSpan(
                        text: r.$2,
                        style: TextStyle(color: cs.onSurface),
                      ),
                    ],
                  ),
                ),
              ),
            )
            .toList(),
      ),
    ),
  );
}

/// 분석 JSON → (라벨, 값) 행 목록. 빈 값은 건너뜀.
List<(String, String)> _analysisRows(Map<String, dynamic> a) {
  final out = <(String, String)>[];
  String s(dynamic v) => (v ?? '').toString().trim();

  final scene = s(a['scene']);
  if (scene.isNotEmpty) out.add(('장면', scene));

  final objs = a['objects'];
  if (objs is List && objs.isNotEmpty) {
    out.add(('객체', objs.map((e) => e.toString()).join(', ')));
  }

  final attrs = a['attributes'];
  if (attrs is Map && attrs.isNotEmpty) {
    final parts = attrs.entries
        .map((e) => '${e.key}: ${_attrVal(e.value)}')
        .where((x) => x.trim().endsWith(':') == false)
        .toList();
    if (parts.isNotEmpty) out.add(('속성', parts.join(' · ')));
  }

  final rels = a['relationships'];
  if (rels is List && rels.isNotEmpty) {
    out.add(('관계', rels.map((e) => e.toString()).join(', ')));
  }

  final ocr = s(a['ocr_text']);
  if (ocr.isNotEmpty) out.add(('글자', ocr));

  return out;
}

/// attributes 값이 스칼라/리스트/맵 어떤 형태든 한 줄로.
String _attrVal(dynamic v) {
  if (v is Map) {
    return v.entries.map((e) => '${e.key} ${e.value}').join(', ');
  }
  if (v is List) return v.map((e) => e.toString()).join(', ');
  return v?.toString() ?? '';
}

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../api.dart';
import '../../core/design.dart';
import '../../models.dart';
import 'record_bubble.dart' show marginaliaNote;

/// 참조 record 썸네일 카드 — 검색/대화 답변의 근거 기록.
/// record를 lazy 로드해 사진 썸네일 + 날짜를 보여주고, 탭하면 상세 시트.
class RefRecordCard extends StatefulWidget {
  final OracleApi api;
  final String recordId;
  const RefRecordCard({super.key, required this.api, required this.recordId});

  @override
  State<RefRecordCard> createState() => _RefRecordCardState();
}

class _RefRecordCardState extends State<RefRecordCard> {
  Record? _rec;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await widget.api.getRecord(widget.recordId);
      if (mounted) setState(() => _rec = r);
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final rec = _rec;
    return InkWell(
      onTap: rec == null ? null : () => _openDetail(context, rec),
      child: Container(
        width: 96,
        decoration: BoxDecoration(
          color: OracleColors.mat,
          border: Border.all(color: OracleColors.matBorder, width: 0.5),
        ),
        padding: const EdgeInsets.all(3),
        clipBehavior: Clip.antiAlias,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(child: _thumb()),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
              child: Text(
                rec != null
                    ? DateFormat('M.d HH:mm').format(rec.ts.toLocal())
                    : (_failed ? '조회 실패' : '...'),
                style: OracleType.timestamp.copyWith(fontSize: 10),
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _thumb() {
    final rec = _rec;
    if (rec != null && rec.imagePaths.isNotEmpty) {
      return Image.network(
        widget.api.photoUrl(rec.imagePaths.first),
        headers: widget.api.photoHeaders,
        fit: BoxFit.cover,
        errorBuilder: (_, _, _) => const ColoredBox(color: OracleColors.photo),
      );
    }
    var mark = '글';
    if (rec != null && rec.audioPaths.isNotEmpty) mark = '소리';
    if (rec != null && rec.videoPaths.isNotEmpty) mark = '영상';
    return Container(
      color: OracleColors.paper,
      alignment: Alignment.center,
      child: Text(mark,
          style: OracleType.marginalia.copyWith(color: OracleColors.faint)),
    );
  }

  void _openDetail(BuildContext context, Record rec) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      backgroundColor: OracleColors.paper,
      builder: (ctx) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.6,
        builder: (ctx, scroll) => ListView(
          controller: scroll,
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
          children: [
            Text(
              DateFormat('yyyy.M.d HH:mm').format(rec.ts.toLocal()),
              style: OracleType.dateHeader,
            ),
            const SizedBox(height: 8),
            if (rec.imagePaths.isNotEmpty)
              ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: Image.network(
                  widget.api.photoUrl(rec.imagePaths.first),
                  headers: widget.api.photoHeaders,
                  fit: BoxFit.contain,
                ),
              ),
            if (rec.userComment.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(rec.userComment, style: OracleType.userBody),
            ],
            if (rec.insight.isNotEmpty) ...[
              const SizedBox(height: 12),
              marginaliaNote(rec.insight),
            ],
          ],
        ),
      ),
    );
  }
}

/// referenced id 리스트 → 가로 스크롤 카드 행 (없으면 빈 위젯).
Widget refRecordRow(BuildContext context, OracleApi api, List<String> ids) {
  if (ids.isEmpty) return const SizedBox.shrink();
  return SizedBox(
    height: 96,
    child: ListView.separated(
      scrollDirection: Axis.horizontal,
      itemCount: ids.length,
      separatorBuilder: (_, _) => const SizedBox(width: 8),
      itemBuilder: (ctx, i) => RefRecordCard(api: api, recordId: ids[i]),
    ),
  );
}

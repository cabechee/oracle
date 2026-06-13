import 'package:flutter/material.dart';

import '../../api.dart';
import '../../core/design.dart';
import '../../models.dart';

/// 타임라인 하단의 다이제스트 발행 행 — "No.N — 어제의 일기 / 읽기".
class DigestPreviewCard extends StatefulWidget {
  final OracleApi api;
  final DigestEntry entry;
  final int? issueNo;
  final VoidCallback onTap;
  const DigestPreviewCard({
    super.key,
    required this.api,
    required this.entry,
    required this.issueNo,
    required this.onTap,
  });
  @override
  State<DigestPreviewCard> createState() => _DigestPreviewCardState();
}

class _DigestPreviewCardState extends State<DigestPreviewCard> {
  String? _preview;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final body = await widget.api.getDigest(widget.entry.date);
      if (!mounted) return;
      final lines = body
          .split('\n')
          .where((l) => l.trim().isNotEmpty && !l.startsWith('#'))
          .toList();
      final preview = lines.take(2).join(' ').trim();
      setState(() => _preview = preview.isEmpty ? '(빈 일기)' : preview);
    } catch (_) {
      if (mounted) setState(() => _preview = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final title = widget.issueNo != null
        ? 'No.${widget.issueNo} — 어제의 일기'
        : '어제의 일기';
    return InkWell(
      onTap: widget.onTap,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
            OracleSpace.screenH, 8, OracleSpace.screenH, 12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title,
                      style: OracleType.marginalia
                          .copyWith(color: OracleColors.inkSoft)),
                  if (_preview != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Text(
                        _preview!,
                        style: OracleType.label
                            .copyWith(color: OracleColors.gray, fontSize: 11),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                ],
              ),
            ),
            const SizedBox(width: 16),
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text('읽기',
                  style: TextStyle(
                    fontFamily: OracleType.sans,
                    fontSize: 11,
                    letterSpacing: 0.3,
                    color: OracleColors.vermilion,
                  )),
            ),
          ],
        ),
      ),
    );
  }
}

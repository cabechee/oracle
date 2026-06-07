import 'package:flutter/material.dart';

import '../../api.dart';
import '../../models.dart';

/// 채팅 타임라인 하단의 다이제스트 미리보기 카드 (탭 → DigestScreen).
class DigestPreviewCard extends StatefulWidget {
  final OracleApi api;
  final DigestEntry entry;
  final VoidCallback onTap;
  const DigestPreviewCard({
    super.key,
    required this.api,
    required this.entry,
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
      setState(() => _preview = preview.isEmpty ? '(빈 다이제스트)' : preview);
    } catch (_) {
      if (mounted) setState(() => _preview = '(미리보기 실패)');
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: InkWell(
        onTap: widget.onTap,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
          decoration: BoxDecoration(
            color: cs.secondaryContainer,
            borderRadius: BorderRadius.circular(12),
          ),
          child: Row(
            children: [
              Icon(Icons.auto_stories, color: cs.onSecondaryContainer),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '📓 ${widget.entry.date} 다이제스트',
                      style: TextStyle(
                        fontWeight: FontWeight.bold,
                        color: cs.onSecondaryContainer,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      _preview ?? '(불러오는 중...)',
                      style: TextStyle(color: cs.onSecondaryContainer),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
              Icon(Icons.chevron_right, color: cs.onSecondaryContainer),
            ],
          ),
        ),
      ),
    );
  }
}

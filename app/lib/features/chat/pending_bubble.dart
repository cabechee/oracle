import 'dart:io';

import 'package:flutter/material.dart';

import 'record_bubble.dart' show userBubble;

/// 처리 중인 캡처 버블 — "생각 중..." (탭하면 큐에서 제거).
class PendingBubble extends StatelessWidget {
  final String? comment;
  final File? photo;
  const PendingBubble({super.key, this.comment, this.photo});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (photo != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: Image.file(
                  photo!,
                  width: 180,
                  height: 180,
                  fit: BoxFit.cover,
                ),
              ),
            ),
          if (comment != null && comment!.isNotEmpty)
            userBubble(context, comment!),
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
                const SizedBox(width: 8),
                const Text('생각 중...'),
                const SizedBox(width: 6),
                Text(
                  '· 탭해서 큐에서 제거',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.outline,
                      ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

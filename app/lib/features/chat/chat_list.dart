import 'package:flutter/material.dart';

import '../../api.dart';
import '../../core/record_store.dart';
import '../../models.dart';
import 'chat_controller.dart';
import 'digest_preview_card.dart';
import 'pending_bubble.dart';
import 'record_bubble.dart';

/// 히스토리 타임라인 — 다이제스트 미리보기 + pending + record 버블을 섞어 렌더.
/// store(records/pendings) 구독, 취소/편집 같은 UI는 여기서(context), 로직은 [chat].
class ChatList extends StatelessWidget {
  final RecordStore store;
  final ChatController chat;
  final OracleApi api;
  final DigestEntry? latestDigest;
  final VoidCallback onOpenDigest;

  const ChatList({
    super.key,
    required this.store,
    required this.chat,
    required this.api,
    required this.latestDigest,
    required this.onOpenDigest,
  });

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: store,
      builder: (context, _) {
        final showDigestCard = latestDigest != null;
        final total =
            store.records.length + store.pendings.length + (showDigestCard ? 1 : 0);
        return ListView.builder(
          controller: chat.scroll,
          reverse: true,
          padding: const EdgeInsets.symmetric(vertical: 8),
          itemCount: total,
          itemBuilder: (ctx, i) {
            if (showDigestCard && i == total - 1) {
              return DigestPreviewCard(
                api: api,
                entry: latestDigest!,
                onTap: onOpenDigest,
              );
            }
            if (i < store.pendings.length) {
              final p = store.pendings[i];
              return GestureDetector(
                onTap: () => _cancelPending(context, p),
                child: PendingBubble(comment: p.comment, photo: p.photo),
              );
            }
            final idx = i - store.pendings.length;
            return GestureDetector(
              onLongPress: () => _editRecord(context, idx),
              child: RecordBubble(
                record: store.records[idx],
                api: api,
                onReact: (emoji) => chat.react(idx, emoji),
              ),
            );
          },
        );
      },
    );
  }

  Future<void> _cancelPending(BuildContext context, PendingCapture p) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('이 요청 큐에서 제거?'),
        content: const Text(
          '큐에서 사라집니다. 단 백엔드가 이미 처리 중이면 결과 record는 채팅에 도착할 수 있습니다.',
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('아니요')),
          TextButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('제거')),
        ],
      ),
    );
    if (ok == true) store.removePending(p.id);
  }

  // ── record 편집 (잘못 보낸 거 정정) ──────────────────────
  Future<void> _editRecord(BuildContext context, int idx) async {
    if (idx < 0 || idx >= store.records.length) return;
    final ctrl = TextEditingController(text: store.records[idx].userComment);
    final newText = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) {
        return Padding(
          padding: EdgeInsets.fromLTRB(
            16,
            16,
            16,
            MediaQuery.of(ctx).viewInsets.bottom + 16,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('코멘트 수정', style: Theme.of(ctx).textTheme.titleMedium),
              const SizedBox(height: 12),
              TextField(
                controller: ctrl,
                autofocus: true,
                minLines: 2,
                maxLines: 5,
                decoration: const InputDecoration(
                  border: OutlineInputBorder(),
                  hintText: '코멘트 (비우면 빈 코멘트로 갱신)',
                ),
              ),
              const SizedBox(height: 8),
              Text(
                '* vault 정본 평문은 변경되지 않습니다(append-only). UI source(Mongo)만 갱신.',
                style: Theme.of(ctx).textTheme.bodySmall?.copyWith(
                      color: Theme.of(ctx).colorScheme.outline,
                    ),
              ),
              const SizedBox(height: 12),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: () => Navigator.pop(ctx, null),
                    child: const Text('취소'),
                  ),
                  const SizedBox(width: 8),
                  FilledButton(
                    onPressed: () => Navigator.pop(ctx, ctrl.text),
                    child: const Text('저장'),
                  ),
                ],
              ),
            ],
          ),
        );
      },
    );
    if (newText != null) await chat.updateComment(idx, newText);
  }
}

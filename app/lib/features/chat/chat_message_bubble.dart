import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import '../../api.dart';
import '../../core/design.dart';
import '../../models.dart';
import 'record_bubble.dart' show userBubble, quickNote, bertAvatar;
import 'ref_record_card.dart';

/// 대화 메시지 — 유저는 우측 고딕(굵게), 동반자는 명조 본문.
/// 기록의 방주(작은 메모)와 달리 대화는 동반자의 온전한 목소리라 본문 크기.
class ChatMessageBubble extends StatelessWidget {
  final ChatMessage message;
  final OracleApi api;
  const ChatMessageBubble({super.key, required this.message, required this.api});

  @override
  Widget build(BuildContext context) {
    if (message.isUser) {
      return userBubble(context, message.text);
    }
    // 베르(강아지) 아바타 + 본문 — 동반자의 온전한 목소리. 쿠키 첨언·참조는 옆 컬럼에.
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: 2),
          child: bertAvatar(26),
        ),
        const SizedBox(width: 9),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              MarkdownBody(
                data: message.text,
                styleSheet: _chatMd(),
              ),
              // 쿠키 첨언 — 베르 답 아래 짧게 거듦
              if ((message.quickText ?? '').isNotEmpty) ...[
                const SizedBox(height: OracleSpace.inBlock),
                quickNote(message.quickText!, seed: message.id),
              ],
              if (message.referenced.isNotEmpty) ...[
                const SizedBox(height: OracleSpace.inBlock),
                refRecordRow(context, api, message.referenced),
              ],
            ],
          ),
        ),
      ],
    );
  }

  MarkdownStyleSheet _chatMd() {
    const body = TextStyle(
      fontFamily: OracleType.serif,
      fontSize: 14,
      height: 24 / 14,
      color: OracleColors.inkSoft,
    );
    return MarkdownStyleSheet(
      p: body,
      strong: body.copyWith(fontWeight: FontWeight.w700),
      em: body,
      listBullet: body,
      code: OracleType.timestamp.copyWith(color: OracleColors.marginalia),
      h1: body.copyWith(fontWeight: FontWeight.w700),
      h2: body.copyWith(fontWeight: FontWeight.w700),
      h3: body.copyWith(fontWeight: FontWeight.w700),
      blockquote: body.copyWith(color: OracleColors.marginalia),
    );
  }
}

/// 응답 대기 중 (대화 전송 직후).
class PendingChatBubble extends StatelessWidget {
  final String text;
  const PendingChatBubble({super.key, required this.text});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        userBubble(context, text),
        Padding(
          padding: const EdgeInsets.only(top: OracleSpace.inPhoto),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const SizedBox(
                width: 10,
                height: 10,
                child: CircularProgressIndicator(
                    strokeWidth: 1, color: OracleColors.faint),
              ),
              const SizedBox(width: 8),
              Text('생각 중',
                  style: OracleType.marginalia
                      .copyWith(color: OracleColors.faint)),
            ],
          ),
        ),
      ],
    );
  }
}

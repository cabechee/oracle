import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import '../../api.dart';
import '../../core/design.dart';
import '../../models.dart';
import 'record_bubble.dart'
    show userBubble, quickNote, bertAvatar, cookieAvatar;
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
    // 동반자 아바타 + 본문. 화자가 쿠키면 쿠키 아바타, 아니면 베르.
    // companion(선제 멘트)은 화자명을 작은 라벨로 얹어 "베르: …" 느낌을 준다.
    final isCookie = message.speaker == '쿠키';
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: 2),
          child: isCookie
              ? cookieAvatar(26, seed: message.id)
              : bertAvatar(26),
        ),
        const SizedBox(width: 9),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 계기 주석 — 이 수다를 일으킨 것 (예: '집에 도착했다.')
              if ((message.trigger ?? '').isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(bottom: 3),
                  child: Text('( ${message.trigger} )',
                      style: OracleType.label.copyWith(
                          color: OracleColors.faint,
                          fontStyle: FontStyle.italic)),
                ),
              if (message.isCompanion && (message.speaker ?? '').isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(bottom: 2),
                  child: Text(message.speaker!,
                      style: OracleType.label
                          .copyWith(color: OracleColors.vermilion)),
                ),
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
              // 실행 제안(일정 등록 등) — 확인 카드
              if (message.action?['type'] == 'create_event') ...[
                const SizedBox(height: OracleSpace.inBlock),
                _ActionCard(message: message, api: api),
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

/// 실행 제안 확인 카드 — '일정 넣을까요?' [넣기]/[취소]. 확인 시 백엔드가 실제 등록.
class _ActionCard extends StatefulWidget {
  final ChatMessage message;
  final OracleApi api;
  const _ActionCard({required this.message, required this.api});

  @override
  State<_ActionCard> createState() => _ActionCardState();
}

class _ActionCardState extends State<_ActionCard> {
  late String _status; // proposed | done | cancelled
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _status = (widget.message.action?['status'] as String?) ?? 'proposed';
  }

  Future<void> _confirm() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final r = await widget.api.confirmChatAction(widget.message.id);
      if (!mounted) return;
      if (r['ok'] == true) {
        setState(() => _status = 'done');
      } else {
        final reason = (r['reason'] as String?) ?? '실패';
        setState(() => _error = reason.contains('미인증')
            ? '캘린더 연동이 먼저 필요해요 (어드민 📅)'
            : reason);
      }
    } catch (e) {
      if (mounted) setState(() => _error = '실패 — 다시 시도해주세요');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _cancel() async {
    setState(() => _busy = true);
    try {
      await widget.api.cancelChatAction(widget.message.id);
    } catch (_) {}
    if (mounted) {
      setState(() {
        _status = 'cancelled';
        _busy = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final action = widget.message.action!;
    final ev = (action['event'] as Map?)?.cast<String, dynamic>() ?? const {};
    final preview = (action['preview'] as String?) ?? '';
    final loc = (ev['location'] as String?)?.trim() ?? '';
    return Container(
      margin: const EdgeInsets.only(top: 2),
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(
        border: Border.all(color: OracleColors.hairline),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            const Icon(Icons.event_outlined,
                size: 15, color: OracleColors.gray),
            const SizedBox(width: 6),
            Expanded(child: Text(preview, style: OracleType.userBody)),
          ]),
          if (loc.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(left: 21, top: 2),
              child: Text(loc,
                  style: OracleType.marginalia
                      .copyWith(color: OracleColors.gray)),
            ),
          const SizedBox(height: 9),
          if (_status == 'proposed')
            Row(children: [
              _btn('넣기', OracleColors.vermilion, _busy ? null : _confirm,
                  filled: true),
              const SizedBox(width: 8),
              _btn('취소', OracleColors.gray, _busy ? null : _cancel),
              if (_busy) ...[
                const SizedBox(width: 10),
                const SizedBox(
                    width: 12,
                    height: 12,
                    child: CircularProgressIndicator(
                        strokeWidth: 1, color: OracleColors.faint)),
              ],
            ])
          else if (_status == 'done')
            Text('📅 캘린더에 넣었어요 ✓',
                style: OracleType.label.copyWith(color: OracleColors.ink))
          else
            Text('취소됨',
                style: OracleType.label.copyWith(color: OracleColors.gray)),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(_error!,
                  style:
                      OracleType.label.copyWith(color: OracleColors.vermilion)),
            ),
        ],
      ),
    );
  }

  Widget _btn(String label, Color color, VoidCallback? onTap,
      {bool filled = false}) {
    return InkWell(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 5),
        decoration: BoxDecoration(
          color: filled ? color : null,
          border: Border.all(color: color),
          borderRadius: BorderRadius.circular(99),
        ),
        child: Text(label,
            style: OracleType.label
                .copyWith(color: filled ? OracleColors.paper : color)),
      ),
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

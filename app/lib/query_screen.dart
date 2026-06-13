import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import 'api.dart';
import 'core/design.dart';
import 'features/chat/record_bubble.dart' show userBubble;
import 'features/chat/ref_record_card.dart';
import 'models.dart';

/// 자연어 검색·질의 화면.
/// 검색바 입력 → backend /query → LLM 답변 + 참조 record_id thumbnail.
class QueryScreen extends StatefulWidget {
  final OracleApi api;
  const QueryScreen({super.key, required this.api});

  @override
  State<QueryScreen> createState() => _QueryScreenState();
}

class _QueryScreenState extends State<QueryScreen> {
  final _ctrl = TextEditingController();
  final List<_Turn> _history = [];   // 질의·답변 누적 (한 세션)
  bool _busy = false;

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final q = _ctrl.text.trim();
    if (q.isEmpty || _busy) return;
    setState(() {
      _busy = true;
      _history.insert(0, _Turn.user(q));
    });
    _ctrl.clear();
    try {
      final r = await widget.api.query(q);
      if (!mounted) return;
      setState(() => _history.insert(0, _Turn.llm(r)));
    } catch (e) {
      if (mounted) {
        setState(() => _history.insert(0, _Turn.error('$e')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('검색')),
      body: Column(
        children: [
          Expanded(
            child: _history.isEmpty
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(OracleSpace.screenH),
                      child: Text(
                        '자연어로 물어보세요.\n\n"이번 주에 마우스 관련 뭐 봤었지?"\n"지난번 영수증 어디?"',
                        textAlign: TextAlign.center,
                        style: OracleType.marginalia,
                      ),
                    ),
                  )
                : ListView.builder(
                    reverse: true,
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    itemCount: _history.length,
                    itemBuilder: (ctx, i) => _TurnBubble(
                      turn: _history[i],
                      api: widget.api,
                    ),
                  ),
          ),
          Container(
            padding: const EdgeInsets.fromLTRB(
                OracleSpace.screenH, 4, OracleSpace.screenH, 8),
            decoration: const BoxDecoration(
              border: Border(
                top: BorderSide(color: OracleColors.hairline, width: 0.5),
              ),
            ),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _ctrl,
                    style: OracleType.userBody,
                    decoration: InputDecoration(
                      hintText: '물어보기',
                      hintStyle: OracleType.userBody
                          .copyWith(color: OracleColors.faint),
                      border: InputBorder.none,
                      isDense: true,
                      contentPadding:
                          const EdgeInsets.symmetric(vertical: 12),
                    ),
                    minLines: 1,
                    maxLines: 3,
                    onSubmitted: (_) => _submit(),
                  ),
                ),
                const SizedBox(width: 12),
                _busy
                    ? const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(
                            strokeWidth: 1, color: OracleColors.faint),
                      )
                    : InkWell(
                        onTap: _submit,
                        child: Padding(
                          padding: const EdgeInsets.all(6),
                          child: Text('\u2192',
                              style: OracleType.dateHeader.copyWith(
                                  fontSize: 17, color: OracleColors.ink)),
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

class _Turn {
  final bool isUser;
  final String? text;
  final QueryResult? result;
  final String? error;
  _Turn._({required this.isUser, this.text, this.result, this.error});
  factory _Turn.user(String t) => _Turn._(isUser: true, text: t);
  factory _Turn.llm(QueryResult r) => _Turn._(isUser: false, result: r);
  factory _Turn.error(String e) => _Turn._(isUser: false, error: e);
}

class _TurnBubble extends StatelessWidget {
  final _Turn turn;
  final OracleApi api;
  const _TurnBubble({required this.turn, required this.api});

  @override
  Widget build(BuildContext context) {
    if (turn.isUser) {
      return Padding(
        padding: const EdgeInsets.symmetric(
            horizontal: OracleSpace.screenH, vertical: 10),
        child: userBubble(context, turn.text!),
      );
    }
    if (turn.error != null) {
      return Padding(
        padding: const EdgeInsets.symmetric(
            horizontal: OracleSpace.screenH, vertical: 10),
        child: Text('실패: ${turn.error}',
            style: OracleType.marginalia
                .copyWith(color: OracleColors.vermilion)),
      );
    }
    final r = turn.result!;
    return Padding(
      padding: const EdgeInsets.symmetric(
          horizontal: OracleSpace.screenH, vertical: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          MarkdownBody(
            data: r.answer,
            selectable: true,
            styleSheet: MarkdownStyleSheet(
              p: OracleType.journal.copyWith(fontSize: 12.5, height: 22 / 12.5),
              strong: OracleType.journal.copyWith(
                  fontSize: 12.5, height: 22 / 12.5, fontWeight: FontWeight.w700),
              listBullet:
                  OracleType.journal.copyWith(fontSize: 12.5, height: 22 / 12.5),
            ),
          ),
          if (r.referenced.isNotEmpty) ...[
            const SizedBox(height: 6),
            // 근거 record 썸네일 카드 — 탭하면 사진·코멘트·인사이트 상세 시트
            refRecordRow(context, api, r.referenced),
          ],
          if (r.alias != null)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text('via ${r.alias}', style: OracleType.label),
            ),
        ],
      ),
    );
  }
}

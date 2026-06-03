import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import 'api.dart';
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
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('검색·질의')),
      body: Column(
        children: [
          Expanded(
            child: _history.isEmpty
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.search, size: 48, color: cs.outline),
                          const SizedBox(height: 12),
                          const Text(
                            '자연어로 물어보세요.\n예: "이번 주에 마우스 관련 뭐 봤었지?"\n   "지난번 회의 메모 어디?"',
                            textAlign: TextAlign.center,
                          ),
                        ],
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
            padding: const EdgeInsets.fromLTRB(8, 8, 8, 12),
            decoration: BoxDecoration(
              border: Border(
                top: BorderSide(color: Theme.of(context).dividerColor),
              ),
            ),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _ctrl,
                    decoration: const InputDecoration(
                      hintText: '질문 입력...',
                      border: OutlineInputBorder(),
                      isDense: true,
                    ),
                    minLines: 1,
                    maxLines: 3,
                    onSubmitted: (_) => _submit(),
                  ),
                ),
                const SizedBox(width: 4),
                IconButton(
                  icon: _busy
                      ? const SizedBox(
                          width: 22,
                          height: 22,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.send),
                  onPressed: _busy ? null : _submit,
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
    final cs = Theme.of(context).colorScheme;
    if (turn.isUser) {
      return Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
        child: Align(
          alignment: Alignment.centerRight,
          child: ConstrainedBox(
            constraints: BoxConstraints(
              maxWidth: MediaQuery.of(context).size.width * 0.78,
            ),
            child: Container(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
              decoration: BoxDecoration(
                color: cs.primary,
                borderRadius: BorderRadius.circular(14),
              ),
              child: Text(turn.text!, style: TextStyle(color: cs.onPrimary)),
            ),
          ),
        ),
      );
    }
    if (turn.error != null) {
      return Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
        child: Align(
          alignment: Alignment.centerLeft,
          child: Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: cs.errorContainer,
              borderRadius: BorderRadius.circular(14),
            ),
            child: Text('실패: ${turn.error}',
                style: TextStyle(color: cs.onErrorContainer)),
          ),
        ),
      );
    }
    final r = turn.result!;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ConstrainedBox(
            constraints: BoxConstraints(
              maxWidth: MediaQuery.of(context).size.width * 0.86,
            ),
            child: Container(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
              decoration: BoxDecoration(
                color: cs.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(14),
              ),
              child: MarkdownBody(data: r.answer, selectable: true),
            ),
          ),
          if (r.referenced.isNotEmpty) ...[
            const SizedBox(height: 6),
            SizedBox(
              height: 90,
              child: ListView.builder(
                scrollDirection: Axis.horizontal,
                itemCount: r.referenced.length,
                itemBuilder: (ctx, i) {
                  final rid = r.referenced[i];
                  return Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: Container(
                      width: 90,
                      decoration: BoxDecoration(
                        color: cs.surfaceContainerHighest,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      padding: const EdgeInsets.all(6),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text('📎 참조',
                              style: Theme.of(context).textTheme.bodySmall),
                          const SizedBox(height: 2),
                          Text(
                            rid.substring(rid.length > 14 ? rid.length - 14 : 0),
                            style: const TextStyle(fontSize: 11),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ],
                      ),
                    ),
                  );
                },
              ),
            ),
          ],
          if (r.alias != null)
            Padding(
              padding: const EdgeInsets.only(top: 4, left: 6),
              child: Text(
                'via ${r.alias}',
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: cs.outline),
              ),
            ),
        ],
      ),
    );
  }
}

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:intl/intl.dart';

import 'api.dart';
import 'chat_input.dart';
import 'models.dart';

void main() => runApp(const OracleApp());

class OracleApp extends StatelessWidget {
  const OracleApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Oracle',
      theme: ThemeData(colorSchemeSeed: Colors.blue, useMaterial3: true),
      darkTheme: ThemeData(
        colorSchemeSeed: Colors.blue,
        brightness: Brightness.dark,
        useMaterial3: true,
      ),
      home: const HomePage(),
    );
  }
}

class HomePage extends StatefulWidget {
  const HomePage({super.key});
  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  final _api = OracleApi();
  final _scroll = ScrollController();
  final List<Record> _records = [];
  bool _loading = false;
  bool _hasMore = true;

  // 진행 중인 ingest (optimistic UI — "생각 중...")
  String? _pendingComment;

  @override
  void initState() {
    super.initState();
    _load(initial: true);
    _scroll.addListener(_onScroll);
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  void _onScroll() {
    // reverse:true 라 maxScrollExtent에 가까워질수록 옛날 records
    if (_scroll.position.pixels >=
        _scroll.position.maxScrollExtent - 200) {
      _load();
    }
  }

  Future<void> _load({bool initial = false}) async {
    if (_loading || (!initial && !_hasMore)) return;
    setState(() => _loading = true);
    try {
      final more =
          await _api.listRecent(limit: 30, offset: _records.length);
      setState(() {
        _records.addAll(more);
        _hasMore = more.length >= 30;
      });
    } catch (e) {
      _toast('읽기 실패: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _submit(String? comment, File? imageFile) async {
    setState(() => _pendingComment =
        comment ?? (imageFile != null ? '(사진)' : ''));
    try {
      await _api.ingest(comment: comment, imageFile: imageFile);
      setState(() {
        _records.clear();
        _hasMore = true;
        _pendingComment = null;
      });
      await _load(initial: true);
    } catch (e) {
      _toast('전송 실패: $e');
      setState(() => _pendingComment = null);
    }
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(msg)));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Oracle'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: '새로고침',
            onPressed: () async {
              setState(() {
                _records.clear();
                _hasMore = true;
              });
              await _load(initial: true);
            },
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: ListView.builder(
              controller: _scroll,
              reverse: true, // 최신이 화면 아래
              padding: const EdgeInsets.symmetric(vertical: 8),
              itemCount:
                  _records.length + (_pendingComment != null ? 1 : 0),
              itemBuilder: (ctx, i) {
                if (_pendingComment != null && i == 0) {
                  return _PendingBubble(comment: _pendingComment!);
                }
                final idx = i - (_pendingComment != null ? 1 : 0);
                return _RecordBubble(
                  record: _records[idx],
                  onReact: (emoji) async {
                    try {
                      await _api.setReaction(_records[idx].id, emoji);
                      setState(() {
                        _records[idx] = Record(
                          id: _records[idx].id,
                          ts: _records[idx].ts,
                          userComment: _records[idx].userComment,
                          imagePaths: _records[idx].imagePaths,
                          vlmCaption: _records[idx].vlmCaption,
                          insight: _records[idx].insight,
                          reaction: emoji,
                        );
                      });
                    } catch (e) {
                      _toast('반응 실패: $e');
                    }
                  },
                );
              },
            ),
          ),
          ChatInput(onSubmit: _submit),
        ],
      ),
    );
  }
}

// ── 버블 위젯들 ───────────────────────────────────────────────

class _PendingBubble extends StatelessWidget {
  final String comment;
  const _PendingBubble({required this.comment});
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (comment.isNotEmpty) _userBubble(context, comment),
          const Padding(
            padding: EdgeInsets.only(top: 6),
            child: Row(
              children: [
                SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
                SizedBox(width: 8),
                Text('생각 중...'),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _RecordBubble extends StatelessWidget {
  final Record record;
  final Future<void> Function(String) onReact;
  const _RecordBubble({required this.record, required this.onReact});

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
          // 유저 입력 — 우측 정렬
          if (record.userComment.isNotEmpty)
            _userBubble(context, record.userComment),
          if (record.imagePaths.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Align(
                alignment: Alignment.centerRight,
                child: Text(
                  '📷 ${record.imagePaths.length}장',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
            ),
          // LLM 즉답 — 좌측
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
          padding:
              const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
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

Widget _userBubble(BuildContext context, String text) {
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

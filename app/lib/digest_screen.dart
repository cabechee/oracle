import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:intl/intl.dart';

import 'api.dart';
import 'core/design.dart';
import 'models.dart';

/// 다이제스트 — 매일 자정 발행되는 일기. 목록 + 본문(하루 한 페이지).
class DigestScreen extends StatefulWidget {
  final OracleApi api;
  const DigestScreen({super.key, required this.api});

  @override
  State<DigestScreen> createState() => _DigestScreenState();
}

class _DigestScreenState extends State<DigestScreen> {
  List<DigestEntry>? _entries;
  String? _error;
  bool _running = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final items = await widget.api.listDigests();
      if (!mounted) return;
      setState(() {
        _entries = items;
        _error = null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  Future<void> _runYesterday() async {
    setState(() => _running = true);
    try {
      final r = await widget.api.runDigest();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('발행 완료 — ${r["date"]}, 기록 ${r["records"]}건'),
        ),
      );
      await _load();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('실패: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _running = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('일기'),
        actions: [
          TextButton(
            onPressed: _running ? null : _runYesterday,
            child: _running
                ? const SizedBox(
                    width: 14,
                    height: 14,
                    child: CircularProgressIndicator(strokeWidth: 1),
                  )
                : const Text('발행',
                    style: TextStyle(
                      fontFamily: OracleType.sans,
                      fontSize: 12.5,
                      color: OracleColors.ink,
                    )),
          ),
          TextButton(
            onPressed: _load,
            child: const Text('새로고침',
                style: TextStyle(
                  fontFamily: OracleType.sans,
                  fontSize: 12.5,
                  color: OracleColors.gray,
                )),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: _error != null
          ? Center(
              child: Padding(
                padding: const EdgeInsets.all(OracleSpace.screenH),
                child: Text('읽기 실패: $_error', style: OracleType.marginalia),
              ),
            )
          : _entries == null
              ? const Center(
                  child: SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 1.5)))
              : _entries!.isEmpty
                  ? Center(
                      child: Padding(
                        padding: const EdgeInsets.all(OracleSpace.screenH),
                        child: Text(
                          '아직 발행된 일기가 없어요.\n자정에 첫 호가 나오거나, ▶ 로 어제치를 발행할 수 있어요.',
                          textAlign: TextAlign.center,
                          style: OracleType.marginalia,
                        ),
                      ),
                    )
                  : ListView.builder(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      itemCount: _entries!.length,
                      itemBuilder: (ctx, i) {
                        final e = _entries![i];
                        final issueNo = _entries!.length - i;
                        return InkWell(
                          onTap: () => Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (_) => DigestDetailScreen(
                                api: widget.api,
                                date: e.date,
                                issueNo: issueNo,
                              ),
                            ),
                          ),
                          child: Container(
                            decoration: const BoxDecoration(
                              border: Border(
                                bottom: BorderSide(
                                    color: OracleColors.hairline, width: 0.5),
                              ),
                            ),
                            padding: const EdgeInsets.symmetric(
                                horizontal: OracleSpace.screenH, vertical: 16),
                            child: Row(
                              children: [
                                SizedBox(
                                  width: 64,
                                  child: Text('No.$issueNo',
                                      style: OracleType.dateHeader),
                                ),
                                Expanded(
                                  child: Text(_korDate(e.date),
                                      style: OracleType.userBody
                                          .copyWith(color: OracleColors.gray)),
                                ),
                                Text('\u2192',
                                    style: OracleType.dateHeader.copyWith(
                                        fontSize: 14,
                                        color: OracleColors.faint)),
                              ],
                            ),
                          ),
                        );
                      },
                    ),
    );
  }

  String _korDate(String iso) {
    try {
      final d = DateTime.parse(iso);
      return DateFormat('M월 d일 EEEE', 'ko').format(d);
    } catch (_) {
      return iso;
    }
  }
}

class DigestDetailScreen extends StatefulWidget {
  final OracleApi api;
  final String date;
  final int? issueNo;
  const DigestDetailScreen(
      {super.key, required this.api, required this.date, this.issueNo});

  @override
  State<DigestDetailScreen> createState() => _DigestDetailScreenState();
}

class _DigestDetailScreenState extends State<DigestDetailScreen> {
  String? _text;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final t = await widget.api.getDigest(widget.date);
      if (!mounted) return;
      setState(() {
        _text = _stripHeading(t);
        _error = null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  /// 본문 첫 '# 날짜' 헤딩 제거 — 발행 헤더가 날짜를 이미 보여줌.
  String _stripHeading(String t) {
    final lines = t.split('\n');
    if (lines.isNotEmpty && lines.first.trimLeft().startsWith('# ')) {
      return lines.skip(1).join('\n').trimLeft();
    }
    return t;
  }

  @override
  Widget build(BuildContext context) {
    String dateLine;
    try {
      dateLine =
          DateFormat('M월 d일 EEEE', 'ko').format(DateTime.parse(widget.date));
    } catch (_) {
      dateLine = widget.date;
    }
    return Scaffold(
      appBar: AppBar(),
      body: _error != null
          ? Center(
              child: Padding(
                padding: const EdgeInsets.all(OracleSpace.screenH),
                child: Text('읽기 실패: $_error', style: OracleType.marginalia),
              ),
            )
          : _text == null
              ? const Center(
                  child: SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 1.5)))
              : ListView(
                  padding: const EdgeInsets.fromLTRB(
                      OracleSpace.screenH, 8, OracleSpace.screenH, 40),
                  children: [
                    Text('매일 자정 발행', style: OracleType.label),
                    const SizedBox(height: 16),
                    Text(
                      widget.issueNo != null
                          ? 'No.${widget.issueNo}'
                          : widget.date,
                      style: OracleType.display,
                    ),
                    const SizedBox(height: OracleSpace.inBlock),
                    Text(dateLine,
                        style: OracleType.userBody
                            .copyWith(color: OracleColors.gray)),
                    const SizedBox(height: 20),
                    const SizedBox(
                        height: 0.5,
                        child: ColoredBox(color: OracleColors.ink)),
                    const SizedBox(height: OracleSpace.screenH),
                    MarkdownBody(
                      data: _text!,
                      selectable: true,
                      styleSheet: _journalMd(),
                    ),
                  ],
                ),
    );
  }

  MarkdownStyleSheet _journalMd() {
    const body = OracleType.journal;
    return MarkdownStyleSheet(
      p: body,
      strong: body.copyWith(fontWeight: FontWeight.w700),
      em: body,
      listBullet: body,
      blockquote: body.copyWith(color: OracleColors.marginalia),
      code: OracleType.timestamp.copyWith(color: OracleColors.marginalia),
      h1: body.copyWith(fontWeight: FontWeight.w700, fontSize: 15),
      h2: body.copyWith(fontWeight: FontWeight.w700, fontSize: 14),
      h3: body.copyWith(fontWeight: FontWeight.w700),
      horizontalRuleDecoration: const BoxDecoration(
        border: Border(
            top: BorderSide(color: OracleColors.hairline, width: 0.5)),
      ),
    );
  }
}

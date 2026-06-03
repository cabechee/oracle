import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import 'api.dart';
import 'models.dart';

/// 다이제스트 목록(왼쪽) + 선택된 다이제스트 본문(오른쪽) 화면.
/// 좁은 화면(폰)에서는 목록만 보이고 탭하면 새 화면으로 본문 push.
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
          content: Text('자정 배치 완료 — ${r["date"]}, records=${r["records"]}'),
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
        title: const Text('다이제스트'),
        actions: [
          IconButton(
            icon: _running
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.play_circle_outline),
            tooltip: '어제 자정 배치 수동 실행',
            onPressed: _running ? null : _runYesterday,
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: '새로고침',
            onPressed: _load,
          ),
        ],
      ),
      body: _error != null
          ? Center(child: Padding(
              padding: const EdgeInsets.all(16),
              child: Text('읽기 실패: $_error'),
            ))
          : _entries == null
              ? const Center(child: CircularProgressIndicator())
              : _entries!.isEmpty
                  ? const Center(
                      child: Padding(
                        padding: EdgeInsets.all(24),
                        child: Text(
                          '아직 다이제스트가 없어요.\n자정 배치가 실행되거나 위 ▶ 버튼으로 어제치를 수동 실행해보세요.',
                          textAlign: TextAlign.center,
                        ),
                      ),
                    )
                  : ListView.separated(
                      itemCount: _entries!.length,
                      separatorBuilder: (_, _) => const Divider(height: 1),
                      itemBuilder: (ctx, i) {
                        final e = _entries![i];
                        return ListTile(
                          leading: const Icon(Icons.calendar_today_outlined),
                          title: Text(e.date),
                          subtitle: Text('${e.size} bytes'),
                          trailing: const Icon(Icons.chevron_right),
                          onTap: () => Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (_) => DigestDetailScreen(
                                api: widget.api,
                                date: e.date,
                              ),
                            ),
                          ),
                        );
                      },
                    ),
    );
  }
}

class DigestDetailScreen extends StatefulWidget {
  final OracleApi api;
  final String date;
  const DigestDetailScreen({super.key, required this.api, required this.date});

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
        _text = t;
        _error = null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.date)),
      body: _error != null
          ? Center(child: Padding(
              padding: const EdgeInsets.all(16),
              child: Text('읽기 실패: $_error'),
            ))
          : _text == null
              ? const Center(child: CircularProgressIndicator())
              : Markdown(
                  data: _text!,
                  selectable: true,
                  padding: const EdgeInsets.all(16),
                ),
    );
  }
}

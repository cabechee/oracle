import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import 'api.dart';

/// 상위 인덱스 — vault master.md (사람용 검색 진입점) + 펜딩 thread 환기.
class IndexScreen extends StatefulWidget {
  final OracleApi api;
  const IndexScreen({super.key, required this.api});

  @override
  State<IndexScreen> createState() => _IndexScreenState();
}

class _IndexScreenState extends State<IndexScreen> {
  String? _master;
  List<Map<String, dynamic>>? _silent;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final results = await Future.wait([
        widget.api.getMasterIndex(),
        widget.api.getSilentThreads(minDays: 3, maxDays: 30),
      ]);
      if (!mounted) return;
      setState(() {
        _master = results[0] as String;
        _silent = results[1] as List<Map<String, dynamic>>;
        _error = null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: const Text('상위 인덱스'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _load,
          ),
        ],
      ),
      body: _error != null
          ? Center(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Text('읽기 실패: $_error'),
              ),
            )
          : _master == null
              ? const Center(child: CircularProgressIndicator())
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    // 펜딩 thread 환기 카드 (위로)
                    if (_silent != null && _silent!.isNotEmpty) ...[
                      Card(
                        color: cs.tertiaryContainer,
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Icon(Icons.notifications_outlined,
                                      color: cs.onTertiaryContainer),
                                  const SizedBox(width: 8),
                                  Text(
                                    '펜딩 환기 ${_silent!.length}건',
                                    style: TextStyle(
                                      fontWeight: FontWeight.bold,
                                      color: cs.onTertiaryContainer,
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 8),
                              ..._silent!.map((s) => Padding(
                                    padding:
                                        const EdgeInsets.symmetric(vertical: 2),
                                    child: Text(
                                      '#${s["id"]} ${s["name"]} — ${s["days_silent"] ?? "?"}일 무언급',
                                      style: TextStyle(
                                          color: cs.onTertiaryContainer),
                                    ),
                                  )),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),
                    ],
                    // 본문 master.md
                    if (_master!.isEmpty)
                      const Padding(
                        padding: EdgeInsets.all(24),
                        child: Center(
                          child: Text(
                            '인덱스 아직 없음.\n자정 배치 한 번 이상 돌아야 생성.',
                            textAlign: TextAlign.center,
                          ),
                        ),
                      )
                    else
                      MarkdownBody(
                        data: _master!,
                        selectable: true,
                      ),
                  ],
                ),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'applog.dart';

/// 인앱 진단 로그 뷰 — AppLog 링버퍼(최신순). 앱바 타이틀 long-press로 진입.
/// "서버 살아있는데 접속 에러" 같은 증상을 폰에서 바로 확인하기 위한 디버그 화면.
class LogScreen extends StatefulWidget {
  const LogScreen({super.key});

  @override
  State<LogScreen> createState() => _LogScreenState();
}

class _LogScreenState extends State<LogScreen> {
  List<String> _lines = AppLog.recent();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('진단 로그 (${_lines.length})'),
        actions: [
          IconButton(
            icon: const Icon(Icons.copy_all),
            tooltip: '전체 복사',
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: _lines.join('\n')));
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('로그 복사됨')),
                );
              }
            },
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => setState(() => _lines = AppLog.recent()),
          ),
        ],
      ),
      body: _lines.isEmpty
          ? const Center(child: Text('로그 없음'))
          : ListView.builder(
              padding: const EdgeInsets.all(8),
              itemCount: _lines.length,
              itemBuilder: (ctx, i) {
                final line = _lines[i];
                final isErr = line.contains('[ERROR]');
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Text(
                    line,
                    style: TextStyle(
                      fontSize: 11,
                      fontFamily: 'monospace',
                      color: isErr
                          ? Theme.of(context).colorScheme.error
                          : Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                  ),
                );
              },
            ),
    );
  }
}

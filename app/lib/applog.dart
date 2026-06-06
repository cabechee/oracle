import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

/// 앱 진단 로그 — 콘솔(debug) + 파일 + 인메모리 링버퍼.
///
/// 서버 통신을 시각·요청·상태코드·소요시간·에러종류까지 남겨서,
/// "서버 살아있는데 접속 에러" 같은 증상의 정체를 데이터로 잡기 위함.
/// 인앱 로그뷰(recent())로 폰에서 바로 확인 가능.
class AppLog {
  static final List<String> _buf = [];
  static File? _file;
  static const _maxBuf = 800;

  static Future<void> init() async {
    try {
      final dir = await getApplicationDocumentsDirectory();
      _file = File('${dir.path}/oracle.log');
    } catch (_) {}
  }

  static void log(String level, String msg) {
    final line = '${DateTime.now().toIso8601String()} [$level] $msg';
    if (kDebugMode) debugPrint(line);
    _buf.add(line);
    if (_buf.length > _maxBuf) _buf.removeRange(0, _buf.length - _maxBuf);
    try {
      _file?.writeAsStringSync('$line\n', mode: FileMode.append, flush: false);
    } catch (_) {}
  }

  static void info(String m) => log('INFO', m);
  static void warn(String m) => log('WARN', m);
  static void err(String m) => log('ERROR', m);

  /// 최신순 로그 (인앱 로그뷰용).
  static List<String> recent() => _buf.reversed.toList(growable: false);

  static Future<String?> filePath() async {
    try {
      final dir = await getApplicationDocumentsDirectory();
      return '${dir.path}/oracle.log';
    } catch (_) {
      return null;
    }
  }
}

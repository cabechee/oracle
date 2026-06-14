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
      // 단순 로테이션 — 2MB 넘으면 비움 (append-only라 방치 시 무한 증식)
      if (await _file!.exists() && await _file!.length() > 2 * 1024 * 1024) {
        await _file!.writeAsString('');
      }
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

  // 카테고리 — 사용자 행동·흐름 추적용 (진단 로그 외에 "무엇을 언제 했나").
  static void life(String m) => log('LIFE', m);   // 앱 생명주기 (foreground/background)
  static void ui(String m) => log('UI', m);       // 탭·버튼·네비게이션·스크롤
  static void media(String m) => log('MEDIA', m); // 카메라·영상·음성·갤러리·공유
  static void net(String m) => log('NET', m);     // 요청/응답 본문 요약

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

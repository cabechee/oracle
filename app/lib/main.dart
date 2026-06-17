import 'package:flutter/foundation.dart'
    show kIsWeb, defaultTargetPlatform, TargetPlatform;
import 'package:flutter/material.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'app.dart';
import 'core/flags.dart';
import 'features/signals/signals_sync.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('ko');   // 한국어 날짜 포맷 (M월 d일 EEEE)
  // 수집(신호·위치)은 별도 네이티브 수집기 앱이 전담 — Flutter는 인터페이스만.
  // (flutterCollects=true면 옛 동작: Flutter가 직접 수집)
  if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
    if (flutterCollects) {
      FlutterForegroundTask.initCommunicationPort(); // 위치 서비스 ↔ UI isolate
      await initSignalsSync();
    } else {
      await cancelSignalsSync(); // 단독화 — 기존 신호 주기 작업 취소
    }
  }
  runApp(const OracleApp());
}

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'app.dart';
import 'features/signals/signals_sync.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('ko');   // 한국어 날짜 포맷 (M월 d일 EEEE)
  // 신호 동기화·위치 포그라운드 서비스는 Android 전용 — 웹에선 skip.
  if (!kIsWeb) {
    FlutterForegroundTask.initCommunicationPort(); // 위치 서비스 ↔ UI isolate
    await initSignalsSync();
  }
  runApp(const OracleApp());
}

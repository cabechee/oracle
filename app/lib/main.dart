import 'package:flutter/foundation.dart'
    show kIsWeb, defaultTargetPlatform, TargetPlatform;
import 'package:flutter/material.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'app.dart';
import 'features/signals/signals_sync.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('ko');   // 한국어 날짜 포맷 (M월 d일 EEEE)
  // 수동 수집·위치 포그라운드 서비스는 Android 전용(별도 수집기 앱으로 이전 중).
  // iPhone은 능동 인터페이스(채팅·카메라·큐레이션)만 — 웹·iOS는 skip.
  if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
    FlutterForegroundTask.initCommunicationPort(); // 위치 서비스 ↔ UI isolate
    await initSignalsSync();
  }
  runApp(const OracleApp());
}

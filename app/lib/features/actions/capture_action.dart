/// 캡처 액션 — 폰 도구화 v1. 캡처 코멘트에서 시간 명령을 폰 온디바이스로 파싱해
/// LLM 없이 0초에 타이머·알람 인텐트 실행 (라면 끓이며 "라면" → 바로 타이머).
///
/// 명시 텍스트 전용(빠름). 사진 추론 액션은 쿠키 빠른 트랙(백엔드)이 별도로 담당.
library;

import 'package:android_intent_plus/android_intent.dart';

class CaptureAction {
  final String kind; // 'timer' | 'alarm'
  final int? seconds; // timer
  final int? hour, minute; // alarm
  final String label;
  CaptureAction(this.kind,
      {this.seconds, this.hour, this.minute, this.label = ''});

  String get toast => kind == 'timer'
      ? '⏲ ${label.isNotEmpty ? '$label ' : ''}${_mmss(seconds ?? 0)} 타이머'
      : '⏰ ${hour?.toString().padLeft(2, '0')}:${minute?.toString().padLeft(2, '0')} 알람';

  /// 제안 칩 라벨 (사진 추론 액션용)
  String get label_ => kind == 'timer'
      ? '⏲ ${label.isNotEmpty ? '$label ' : ''}${_mmss(seconds ?? 0)} 타이머 시작'
      : toast;

  static String _mmss(int s) =>
      '${s ~/ 60}:${(s % 60).toString().padLeft(2, '0')}';

  /// 백엔드 쿠키 action JSON → CaptureAction (사진 추론). 현재 timer만.
  static CaptureAction? fromJson(Map<String, dynamic>? j) {
    if (j == null) return null;
    if (j['tool'] == 'timer') {
      final s = (j['seconds'] as num?)?.toInt();
      if (s != null && s > 0) {
        return CaptureAction('timer',
            seconds: s, label: (j['label'] as String?) ?? '');
      }
    }
    return null;
  }
}

// 음식·관용 → 초. "라면 끓인다" 같은 사진/메모에 즉답.
const _foodTimers = <String, int>{
  '컵라면': 180, '신라면': 270, '진라면': 270, '라면': 270,
  '반숙': 390, '완숙': 600, '삶은 계란': 600,
  '녹차': 120, '홍차': 240, '차 우려': 180,
  '파스타': 600, '스파게티': 600, '면 삶': 300,
};

/// 코멘트에서 액션 1건 추출 (없으면 null). 우선순위: 알람 > 명시 타이머 > 음식.
CaptureAction? parseCaptureAction(String text) {
  final t = text.trim();
  if (t.isEmpty) return null;

  // 알람: "(오전/오후) N시 (M분) 알람/맞춰/깨워"
  final am = RegExp(r'(오전|오후)?\s*(\d{1,2})\s*시\s*(?:(\d{1,2})\s*분)?\s*(?:에)?\s*(알람|맞춰|깨워|기상)')
      .firstMatch(t);
  if (am != null) {
    var h = int.parse(am[2]!);
    final mn = am[3] != null ? int.parse(am[3]!) : 0;
    if (am[1] == '오후' && h < 12) h += 12;
    if (am[1] == '오전' && h == 12) h = 0;
    if (h <= 23 && mn <= 59) {
      return CaptureAction('alarm', hour: h, minute: mn, label: t);
    }
  }

  // 타이머: "N분/시간 (타이머/후/뒤/이따/있다가)"
  final tm = RegExp(r'(\d+)\s*(시간|분|초)\s*(?:뒤|후|이따|있다가|만에)?\s*(?:타이머|알려|재)?')
      .firstMatch(t);
  if (tm != null && (t.contains('타이머') ||
      RegExp(r'\d+\s*(시간|분|초)\s*(뒤|후|이따|있다가)').hasMatch(t))) {
    final n = int.parse(tm[1]!);
    final unit = tm[2]!;
    final sec = unit == '시간' ? n * 3600 : (unit == '분' ? n * 60 : n);
    if (sec > 0 && sec <= 86400) {
      return CaptureAction('timer', seconds: sec, label: '');
    }
  }

  // 음식·관용 사전
  for (final e in _foodTimers.entries) {
    if (t.contains(e.key)) {
      return CaptureAction('timer', seconds: e.value, label: e.key);
    }
  }
  return null;
}

/// 액션 실행. skipUi=true(텍스트 명시)면 바로 셋업, false(사진 추론)면
/// 시계앱이 값을 채운 채 열려 사용자가 시간을 확인·조정 후 시작.
Future<void> runCaptureAction(CaptureAction a, {bool skipUi = true}) async {
  if (a.kind == 'timer') {
    await AndroidIntent(
      action: 'android.intent.action.SET_TIMER',
      arguments: <String, dynamic>{
        'android.intent.extra.alarm.LENGTH': a.seconds,
        'android.intent.extra.alarm.MESSAGE': a.label.isEmpty ? 'Oracle' : a.label,
        'android.intent.extra.alarm.SKIP_UI': skipUi,
      },
    ).launch();
  } else if (a.kind == 'alarm') {
    await AndroidIntent(
      action: 'android.intent.action.SET_ALARM',
      arguments: <String, dynamic>{
        'android.intent.extra.alarm.HOUR': a.hour,
        'android.intent.extra.alarm.MINUTES': a.minute,
        'android.intent.extra.alarm.MESSAGE': 'Oracle',
        'android.intent.extra.alarm.SKIP_UI': skipUi,
      },
    ).launch();
  }
}

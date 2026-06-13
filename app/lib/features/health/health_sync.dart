/// Health Connect 동기화 — 오늘 걸음 + 어젯밤 수면을 백엔드 metrics로.
///
/// 삼성헬스/구글핏이 Health Connect에 쌓은 데이터를 읽는다(갤럭시 자동 동기화).
/// 홈 표지·조간(슬라이스③)의 재료. 권한 없으면 조용히 skip.
library;

import 'package:health/health.dart';

import '../../api.dart';
import '../../applog.dart';

final _health = Health();
const _types = [HealthDataType.STEPS, HealthDataType.SLEEP_SESSION];

bool _configured = false;

/// 동기화 1회 — 권한 있으면 걸음·수면 읽어 전송. 실패/거부는 graceful.
Future<void> syncHealth() async {
  try {
    if (!_configured) {
      await _health.configure();
      _configured = true;
    }
    final granted = await _health.requestAuthorization(_types);
    if (!granted) return;

    final now = DateTime.now();
    final midnight = DateTime(now.year, now.month, now.day);

    // 오늘 누적 걸음
    int? steps;
    try {
      steps = await _health.getTotalStepsInInterval(midnight, now);
    } catch (e) {
      AppLog.info('걸음 읽기 실패: $e');
    }

    // 어젯밤 수면 — 어제 18시 ~ 지금 사이 세션 합(분)
    int sleepMin = 0;
    try {
      final pts = await _health.getHealthDataFromTypes(
        types: const [HealthDataType.SLEEP_SESSION],
        startTime: midnight.subtract(const Duration(hours: 6)),
        endTime: now,
      );
      for (final p in pts) {
        sleepMin += p.dateTo.difference(p.dateFrom).inMinutes;
      }
    } catch (e) {
      AppLog.info('수면 읽기 실패: $e');
    }

    if (steps == null && sleepMin == 0) return;
    await OracleApi()
        .syncMetrics(steps: steps, sleepMin: sleepMin > 0 ? sleepMin : null);
  } catch (e) {
    AppLog.info('health sync 실패: $e');
  }
}

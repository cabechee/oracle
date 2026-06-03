import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _kOnboardingDoneKey = 'onboarding_done';

/// 첫 실행 안내 화면. SharedPreferences 플래그로 다음에는 안 뜸.
class OnboardingScreen extends StatelessWidget {
  final VoidCallback onDone;
  const OnboardingScreen({super.key, required this.onDone});

  Future<void> _finish(BuildContext context) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_kOnboardingDoneKey, true);
    onDone();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 24),
              Icon(Icons.psychology_alt_outlined, size: 56, color: cs.primary),
              const SizedBox(height: 16),
              Text(
                'Oracle에 오신 걸 환영합니다',
                style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                      fontWeight: FontWeight.bold,
                    ),
              ),
              const SizedBox(height: 12),
              Text(
                '일상을 사진·텍스트·음성으로 던지면 LLM이 반응하는 채팅 동반자이자 비서입니다.',
                style: Theme.of(context).textTheme.bodyLarge,
              ),
              const SizedBox(height: 28),
              _stepRow(context, '📷', '카메라 셔터 1회',
                  '앱을 켜면 바로 프리뷰. 셔터 한 번에 캡처.'),
              _stepRow(context, '🎤', '음성 또는 텍스트 코멘트',
                  '마이크 탭 → 한국어 음성 인식 또는 텍스트 직접 입력 (둘 다 선택).'),
              _stepRow(context, '📤', '전송 → 즉답',
                  '전송 누르는 즉시 입력 비워지고 LLM이 백그라운드에서 응답. 계속 던질 수 있음.'),
              _stepRow(context, '📓', '매일 자정 다이제스트',
                  '자정에 자동으로 그날 묶음 + 펜딩 환기. AppBar의 📖 아이콘 또는 검색·인덱스로 회상.'),
              const SizedBox(height: 12),
              Text(
                '권한: 카메라·마이크·알림 popup이 뜨면 허용해주세요. 다음 번부터 자동.',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: cs.outline,
                    ),
              ),
              const Spacer(),
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: () => _finish(context),
                  icon: const Icon(Icons.arrow_forward),
                  label: const Text('시작'),
                  style: FilledButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 14),
                  ),
                ),
              ),
              const SizedBox(height: 8),
            ],
          ),
        ),
      ),
    );
  }

  Widget _stepRow(BuildContext context, String emoji, String title, String desc) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(emoji, style: const TextStyle(fontSize: 22)),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 2),
                Text(
                  desc,
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// 첫 실행 여부 체크.
Future<bool> isOnboardingDone() async {
  final prefs = await SharedPreferences.getInstance();
  return prefs.getBool(_kOnboardingDoneKey) ?? false;
}

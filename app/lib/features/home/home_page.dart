import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../api.dart';
import '../../applog.dart';
import '../../core/design.dart';
import '../../core/record_store.dart';
import '../../digest_screen.dart';
import '../../index_screen.dart';
import '../../llm_picker.dart';
import '../../log_screen.dart';
import '../../onboarding_screen.dart';
import '../../query_screen.dart';
import '../capture/capture_controller.dart';
import '../capture/record_tab.dart';
import '../chat/chat_controller.dart';
import '../chat/chat_list.dart';
import '../desk/desk_screen.dart';
import '../health/health_sync.dart';
import '../notifications/notif_service.dart';
import '../signals/signals_sync.dart';
import 'home_tab.dart';

const _kModelKey = 'selected_model';
const _kLastSeenDigestKey = 'last_seen_digest_date';

/// 앱 셸 — 3탭 스캐폴드 + 생명주기 + 모델 선택 + 스토어·컨트롤러 생성·주입.
class HomePage extends StatefulWidget {
  const HomePage({super.key});
  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage>
    with WidgetsBindingObserver, SingleTickerProviderStateMixin {
  final OracleApi _api = OracleApi();
  late final TabController _tab;
  int _lastTab = 3;
  static const _tabNames = ['오늘', '흐름', '데스크', '기록'];

  late final RecordStore _store;
  late final CaptureController _capture;
  late final ChatController _chat;
  final NotifService _notif = NotifService();

  String? _selectedModel;

  @override
  void initState() {
    super.initState();
    AppLog.init();
    AppLog.life('앱 시작');
    _tab = TabController(length: 4, vsync: this, initialIndex: 3); // 첫 실행 = 기록 탭
    _tab.addListener(() {
      if (_tab.index != _lastTab) {
        _lastTab = _tab.index;
        AppLog.ui('탭 → ${_tabNames[_tab.index]}');
      }
    });
    WidgetsBinding.instance.addObserver(this);

    _store = RecordStore();
    _capture = CaptureController(
      api: _api,
      store: _store,
      onToast: _toast,
      modelProvider: () => _selectedModel,
    );
    _chat = ChatController(api: _api, store: _store, onToast: _toast);

    _notif.init(onTap: _onNotifTap);
    _loadSelectedModel();
    _chat.load(initial: true);
    _chat.loadMessages();
    _loadLatestDigest();
    // 카메라·SMS·통화·알림·WorkManager는 폰 전용 — 웹에선 조회/검색/대화만.
    if (!kIsWeb) {
      _capture.init();
      _ensureSignalsPermissions();
      maybeForegroundSync();
      initNotificationListener();   // 앱 알림 수집 시작 (권한 있으면 구독)
      syncHealth();                 // 수면·걸음 (Health Connect)
    }
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _maybeShowOnboarding();
      _checkLaunchNotif(); // 알림 탭으로 켜졌으면(cold start) 기록 탭으로
    });
  }

  /// 신호 동기화용 권한 — 1회만 요청, 거부해도 해당 소스만 건너뜀 (graceful).
  Future<void> _ensureSignalsPermissions() async {
    final prefs = await SharedPreferences.getInstance();
    if (prefs.getBool('signals_perm_asked') ?? false) return;
    await prefs.setBool('signals_perm_asked', true);
    await [Permission.sms, Permission.phone].request();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _capture.dispose();
    _chat.dispose();
    _store.dispose();
    _tab.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (kIsWeb) return; // 웹은 카메라·신호 생명주기 처리 없음
    if (state == AppLifecycleState.inactive ||
        state == AppLifecycleState.paused) {
      _capture.onAppPause();
    } else if (state == AppLifecycleState.resumed) {
      _capture.onAppResume();
      _loadLatestDigest();
      _chat.refresh(); // 복귀 시 최신 record 반영 (백그라운드 중 완료분)
      maybeForegroundSync(); // 신호 동기화 — 배터리 최적화로 주기 밀려도 복귀 시 보장
    }
  }

  // ── 온보딩 — 첫 실행 시 한 번 ──────────────────────────────
  Future<void> _maybeShowOnboarding() async {
    final done = await isOnboardingDone();
    if (done || !mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (ctx) => OnboardingScreen(onDone: () => Navigator.of(ctx).pop()),
      ),
    );
  }

  // ── 다이제스트 미리보기 + 새 다이제스트 알림 ──────────────
  /// 새 다이제스트 도착 시 알림만 — 표시는 홈 탭(다이제스트는 히스토리에서 뺌).
  Future<void> _loadLatestDigest() async {
    try {
      final list = await _api.listDigests();
      if (!mounted) return;
      final latest = list.isNotEmpty ? list.first : null;
      if (latest != null) {
        final prefs = await SharedPreferences.getInstance();
        final lastSeen = prefs.getString(_kLastSeenDigestKey);
        if (lastSeen != latest.date) {
          _notif.notifyNewDigest(latest.date);
          await prefs.setString(_kLastSeenDigestKey, latest.date);
        }
      }
    } catch (_) {}
  }

  // ── LLM 선택 ───────────────────────────────────────────────
  Future<void> _loadSelectedModel() async {
    final prefs = await SharedPreferences.getInstance();
    final v = prefs.getString(_kModelKey);
    if (!mounted) return;
    setState(() => _selectedModel = (v == null || v.isEmpty) ? null : v);
  }

  Future<void> _saveSelectedModel(String? alias) async {
    final prefs = await SharedPreferences.getInstance();
    if (alias == null || alias.isEmpty) {
      await prefs.remove(_kModelKey);
    } else {
      await prefs.setString(_kModelKey, alias);
    }
    if (!mounted) return;
    setState(() => _selectedModel = (alias == null || alias.isEmpty) ? null : alias);
  }

  Future<void> _openLlmPicker() async {
    final picked = await showLlmPicker(context, _api, _selectedModel);
    if (picked == null) return;
    await _saveSelectedModel(picked.isEmpty ? null : picked);
    AppLog.ui('모델 선택 → ${picked.isEmpty ? "자동" : picked}');
  }

  Widget _textAction(String label, VoidCallback onTap) {
    return TextButton(
      onPressed: onTap,
      style: TextButton.styleFrom(
        minimumSize: const Size(40, 40),
        padding: const EdgeInsets.symmetric(horizontal: 10),
      ),
      child: Text(label,
          style: const TextStyle(
            fontFamily: OracleType.sans,
            fontSize: 12.5,
            letterSpacing: 0.2,
            color: OracleColors.ink,
          )),
    );
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<void> _onRefresh() async {
    AppLog.ui('당겨서 새로고침');
    await _chat.refresh();
    await _loadLatestDigest();
  }

  void _openDigest() {
    AppLog.ui('화면 열기 — 일기');
    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => DigestScreen(api: _api)),
    );
  }

  /// 알림 탭 라우팅 — companion 'ask:' 멘트면 기록 탭에서 답, 아니면 다이제스트.
  void _onNotifTap(String? payload) {
    if (payload == null || !mounted) return;
    if (payload.startsWith('ask:')) {
      AppLog.ui('알림 답하기 → 기록 탭');
      _tab.animateTo(3); // 기록 탭
      _capture.setAsk(payload.substring(4));
    } else {
      _openDigestFromNotif(payload);
    }
  }

  /// 알림 탭으로 앱이 켜졌으면(cold start) 그 payload 처리.
  Future<void> _checkLaunchNotif() async {
    final payload = await _notif.launchPayload();
    if (payload != null) _onNotifTap(payload);
  }

  /// 알림 탭 — payload(날짜) 있으면 그 다이제스트 본문으로 바로.
  void _openDigestFromNotif(String? date) {
    if (!mounted) return;
    if (date != null && date.isNotEmpty) {
      Navigator.push(
        context,
        MaterialPageRoute(
            builder: (_) => DigestDetailScreen(api: _api, date: date)),
      );
    } else {
      _openDigest();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        // 타이틀 long-press = 숨은 진단 로그 뷰 (개인용 디버그)
        title: GestureDetector(
          onLongPress: () {
            AppLog.ui('화면 열기 — 진단 로그');
            Navigator.push(context,
                MaterialPageRoute(builder: (_) => const LogScreen()));
          },
          child: const Text('Oracle'),
        ),
        bottom: TabBar(
          controller: _tab,
          tabs: const [
            Tab(text: '오늘'),
            Tab(text: '흐름'),
            Tab(text: '데스크'),
            Tab(text: '기록'),
          ],
        ),
        actions: [
          Center(
            child: InkWell(
              onTap: _openLlmPicker,
              borderRadius: BorderRadius.circular(99),
              child: Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
                decoration: BoxDecoration(
                  border:
                      Border.all(color: OracleColors.hairline, width: 0.5),
                  borderRadius: BorderRadius.circular(99),
                ),
                child: Text(
                  _selectedModel ?? '자동',
                  style: OracleType.label
                      .copyWith(color: OracleColors.gray, fontSize: 11),
                ),
              ),
            ),
          ),
          _textAction('검색', () {
            AppLog.ui('화면 열기 — 검색');
            Navigator.push(context,
                MaterialPageRoute(builder: (_) => QueryScreen(api: _api)));
          }),
          _textAction('색인', () {
            AppLog.ui('화면 열기 — 색인');
            Navigator.push(context,
                MaterialPageRoute(builder: (_) => IndexScreen(api: _api)));
          }),
          _textAction('일기', _openDigest),
          const SizedBox(width: 8),
        ],
      ),
      body: SafeArea(
        top: false,
        child: TabBarView(
          controller: _tab,
          children: [
            HomeTab(api: _api, onGoHistory: () => _tab.animateTo(1)),
            RefreshIndicator(
              onRefresh: _onRefresh,
              child: ChatList(
                store: _store,
                chat: _chat,
                api: _api,
                // 지나간 사진 백필은 웹에서만 (폰은 기록 탭 카메라로 지금 촬영)
                onBackfill: kIsWeb ? _capture.backfillUpload : null,
              ),
            ),
            DeskScreen(api: _api, embedded: true),
            kIsWeb ? const _WebCaptureNotice() : RecordTab(c: _capture),
          ],
        ),
      ),
    );
  }
}

/// 웹 기록 탭 — 카메라·녹음은 폰 전용이라 안내만.
class _WebCaptureNotice extends StatelessWidget {
  const _WebCaptureNotice();
  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(40),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.photo_camera_outlined,
                size: 48, color: OracleColors.faint),
            const SizedBox(height: 16),
            Text('캡처는 폰 앱에서',
                style: OracleType.dateHeader, textAlign: TextAlign.center),
            const SizedBox(height: 8),
            Text('웹에서는 기록을 보고, 검색하고, 대화할 수 있어요.\n'
                '사진·음성 캡처는 폰에서 이어집니다.',
                style: OracleType.marginalia, textAlign: TextAlign.center),
          ],
        ),
      ),
    );
  }
}

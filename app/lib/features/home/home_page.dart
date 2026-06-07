import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../api.dart';
import '../../applog.dart';
import '../../core/record_store.dart';
import '../../digest_screen.dart';
import '../../index_screen.dart';
import '../../llm_picker.dart';
import '../../models.dart';
import '../../onboarding_screen.dart';
import '../../query_screen.dart';
import '../capture/capture_controller.dart';
import '../capture/record_tab.dart';
import '../chat/chat_controller.dart';
import '../chat/chat_list.dart';
import '../notifications/notif_service.dart';
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

  late final RecordStore _store;
  late final CaptureController _capture;
  late final ChatController _chat;
  final NotifService _notif = NotifService();

  String? _selectedModel;
  DigestEntry? _latestDigest;

  @override
  void initState() {
    super.initState();
    AppLog.init();
    _tab = TabController(length: 3, vsync: this, initialIndex: 2); // 첫 실행 = 기록 탭
    WidgetsBinding.instance.addObserver(this);

    _store = RecordStore();
    _capture = CaptureController(
      api: _api,
      store: _store,
      onToast: _toast,
      modelProvider: () => _selectedModel,
    );
    _chat = ChatController(api: _api, store: _store, onToast: _toast);

    _notif.init();
    _capture.init();
    _loadSelectedModel();
    _chat.load(initial: true);
    _loadLatestDigest();
    WidgetsBinding.instance.addPostFrameCallback((_) => _maybeShowOnboarding());
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
    if (state == AppLifecycleState.inactive ||
        state == AppLifecycleState.paused) {
      _capture.onAppPause();
    } else if (state == AppLifecycleState.resumed) {
      _capture.onAppResume();
      _loadLatestDigest();
      _chat.refresh(); // 복귀 시 최신 record 반영 (백그라운드 중 완료분)
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
  Future<void> _loadLatestDigest() async {
    try {
      final list = await _api.listDigests();
      if (!mounted) return;
      final latest = list.isNotEmpty ? list.first : null;
      setState(() => _latestDigest = latest);
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
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<void> _onRefresh() async {
    await _chat.refresh();
    await _loadLatestDigest();
  }

  void _openDigest() {
    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => DigestScreen(api: _api)),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Oracle'),
        bottom: TabBar(
          controller: _tab,
          tabs: const [
            Tab(text: '홈'),
            Tab(text: '히스토리'),
            Tab(text: '기록'),
          ],
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 4),
            child: ActionChip(
              avatar: const Icon(Icons.psychology_outlined, size: 18),
              label: Text(
                _selectedModel ?? '(자동)',
                overflow: TextOverflow.ellipsis,
              ),
              onPressed: _openLlmPicker,
              tooltip: 'LLM 선택',
            ),
          ),
          IconButton(
            icon: const Icon(Icons.search),
            tooltip: '검색·질의 (자연어)',
            onPressed: () => Navigator.push(context,
                MaterialPageRoute(builder: (_) => QueryScreen(api: _api))),
          ),
          IconButton(
            icon: const Icon(Icons.travel_explore_outlined),
            tooltip: '상위 인덱스 + 펜딩 환기',
            onPressed: () => Navigator.push(context,
                MaterialPageRoute(builder: (_) => IndexScreen(api: _api))),
          ),
          IconButton(
            icon: const Icon(Icons.auto_stories_outlined),
            tooltip: '다이제스트 보기',
            onPressed: _openDigest,
          ),
        ],
      ),
      body: SafeArea(
        top: false,
        child: TabBarView(
          controller: _tab,
          children: [
            const HomeTab(),
            RefreshIndicator(
              onRefresh: _onRefresh,
              child: ChatList(
                store: _store,
                chat: _chat,
                api: _api,
                latestDigest: _latestDigest,
                onOpenDigest: _openDigest,
              ),
            ),
            RecordTab(c: _capture),
          ],
        ),
      ),
    );
  }
}

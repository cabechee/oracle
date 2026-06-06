import 'dart:async';
import 'dart:io';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:image_picker/image_picker.dart';
import 'package:intl/intl.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:receive_sharing_intent/receive_sharing_intent.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:record/record.dart';
import 'package:path_provider/path_provider.dart';

import 'api.dart';
import 'applog.dart';
import 'digest_screen.dart';
import 'index_screen.dart';
import 'llm_picker.dart';
import 'models.dart';
import 'onboarding_screen.dart';
import 'query_screen.dart';

const _kModelKey = 'selected_model';
const _kLastSeenDigestKey = 'last_seen_digest_date';

/// 진행 중인 ingest 단위. 동시에 여러 개 가능 (fire-and-forget).
class _Pending {
  final String id;
  final String? comment;
  final File? photo;
  final String? audioPath;
  final String? videoPath;
  _Pending(
      {required this.id,
      this.comment,
      this.photo,
      this.audioPath,
      this.videoPath});
}

void main() => runApp(const OracleApp());

class OracleApp extends StatelessWidget {
  const OracleApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Oracle',
      theme: ThemeData(colorSchemeSeed: Colors.blue, useMaterial3: true),
      darkTheme: ThemeData(
        colorSchemeSeed: Colors.blue,
        brightness: Brightness.dark,
        useMaterial3: true,
      ),
      home: const HomePage(),
    );
  }
}

class HomePage extends StatefulWidget {
  const HomePage({super.key});
  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage>
    with WidgetsBindingObserver, SingleTickerProviderStateMixin {
  final _api = OracleApi();
  final _scroll = ScrollController();
  final List<Record> _records = [];
  final List<_Pending> _pendings = [];
  bool _loading = false;
  bool _hasMore = true;

  // ── 카메라 ─────────────────────────────────────────────────
  CameraController? _camera;
  bool _cameraReady = false;
  String? _cameraError;

  // ── 입력 ───────────────────────────────────────────────────
  File? _photo;
  File? _video;
  bool _recordingVideo = false;
  final _commentCtrl = TextEditingController();

  // ── LLM 선택 ───────────────────────────────────────────────
  String? _selectedModel;

  // ── 음성: 순수 녹음 (받아쓰기 STT 제거) ────────────────────
  bool _listening = false;   // 음성 녹음 중
  final AudioRecorder _recorder = AudioRecorder();
  bool _recordAvailable = false;
  String? _audioPath;

  // ── 탭 (홈 / 히스토리 / 기록) ──────────────────────────────
  late final TabController _tab;

  // ── 갤러리·외부 공유 ───────────────────────────────────────
  final ImagePicker _picker = ImagePicker();
  StreamSubscription<List<SharedMediaFile>>? _shareSub;

  // ── 다이제스트 미리보기 ────────────────────────────────────
  DigestEntry? _latestDigest;

  // ── 푸시 알림 ──────────────────────────────────────────────
  final FlutterLocalNotificationsPlugin _notifications =
      FlutterLocalNotificationsPlugin();

  @override
  void initState() {
    super.initState();
    AppLog.init();
    _tab = TabController(length: 3, vsync: this, initialIndex: 2); // 첫 실행 = 기록 탭
    WidgetsBinding.instance.addObserver(this);
    _initCamera();
    _initRecord();
    _initShareListener();
    _initNotifications();
    _loadSelectedModel();
    _load(initial: true);
    _loadLatestDigest();
    _scroll.addListener(_onScroll);
    WidgetsBinding.instance.addPostFrameCallback((_) => _maybeShowOnboarding());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _camera?.dispose();
    _scroll.dispose();
    _commentCtrl.dispose();
    _shareSub?.cancel();
    _recorder.dispose();
    _tab.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.inactive ||
        state == AppLifecycleState.paused) {
      _camera?.dispose();
      _camera = null;
      if (mounted) setState(() => _cameraReady = false);
    } else if (state == AppLifecycleState.resumed) {
      if (!_cameraReady) _initCamera();
      _loadLatestDigest();
      _refresh(); // 복귀 시 최신 record 반영 (백그라운드 중 완료분 표시)
    }
  }

  // ── 푸시 알림 init + 새 다이제스트 알림 ────────────────────
  Future<void> _initNotifications() async {
    try {
      const init = InitializationSettings(
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
      );
      await _notifications.initialize(init);
      // Android 13+ 권한 요청 (없으면 silent)
      await _notifications
          .resolvePlatformSpecificImplementation<
              AndroidFlutterLocalNotificationsPlugin>()
          ?.requestNotificationsPermission();
    } catch (_) {}
  }

  Future<void> _notifyNewDigest(String date) async {
    try {
      const details = NotificationDetails(
        android: AndroidNotificationDetails(
          'oracle_digest',
          '다이제스트',
          channelDescription: '자정 다이제스트 도착 알림',
          importance: Importance.high,
          priority: Priority.high,
        ),
      );
      await _notifications.show(
        0,
        '📓 새 다이제스트',
        '$date — 탭해서 보기',
        details,
      );
    } catch (_) {}
  }

  // ── 온보딩 라우팅 — 첫 실행 시 한 번 ──────────────────────
  Future<void> _maybeShowOnboarding() async {
    final done = await isOnboardingDone();
    if (done || !mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (ctx) => OnboardingScreen(
          onDone: () => Navigator.of(ctx).pop(),
        ),
      ),
    );
  }

  // ── 카메라 ───────────────────────────────────────────────
  Future<void> _initCamera() async {
    try {
      var status = await Permission.camera.status;
      if (!status.isGranted) {
        status = await Permission.camera.request();
      }
      if (!status.isGranted) {
        if (mounted) {
          setState(() => _cameraError = '카메라 권한 거부됨 — 설정에서 허용 필요');
        }
        return;
      }
      final cams = await availableCameras();
      if (cams.isEmpty) {
        if (mounted) setState(() => _cameraError = '카메라를 찾을 수 없음');
        return;
      }
      final back = cams.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.back,
        orElse: () => cams.first,
      );
      final ctrl = CameraController(back, ResolutionPreset.high,
          enableAudio: true);   // 영상 녹화에 소리 포함
      await ctrl.initialize();
      if (!mounted) {
        await ctrl.dispose();
        return;
      }
      setState(() {
        _camera = ctrl;
        _cameraReady = true;
        _cameraError = null;
      });
    } catch (e) {
      if (mounted) setState(() => _cameraError = '$e');
    }
  }

  Future<void> _capture() async {
    if (!_cameraReady || _camera == null) return;
    try {
      final pic = await _camera!.takePicture();
      if (!mounted) return;
      setState(() => _photo = File(pic.path));
    } catch (e) {
      _toast('촬영 실패: $e');
    }
  }

  void _clearPhoto() => setState(() => _photo = null);

  // ── 갤러리에서 사진 선택 ──────────────────────────────────
  Future<void> _pickFromGallery() async {
    try {
      final x = await _picker.pickImage(
        source: ImageSource.gallery,
        imageQuality: 85,
        maxWidth: 2048,
      );
      if (x != null && mounted) setState(() => _photo = File(x.path));
    } catch (e) {
      _toast('갤러리 실패: $e');
    }
  }

  // ── 영상: 카메라 녹화(셔터 길게) + 갤러리 선택 ─────────────
  Future<void> _startVideoRecording() async {
    if (!_cameraReady || _camera == null || _camera!.value.isRecordingVideo) {
      return;
    }
    try {
      await _camera!.startVideoRecording();
      if (mounted) setState(() => _recordingVideo = true);
    } catch (e) {
      _toast('영상 녹화 실패: $e');
    }
  }

  Future<void> _stopVideoRecording() async {
    if (_camera == null || !_camera!.value.isRecordingVideo) return;
    try {
      final f = await _camera!.stopVideoRecording();
      if (!mounted) return;
      setState(() {
        _recordingVideo = false;
        _video = File(f.path);
      });
    } catch (e) {
      if (mounted) setState(() => _recordingVideo = false);
      _toast('영상 저장 실패: $e');
    }
  }

  Future<void> _pickVideoFromGallery() async {
    try {
      final x = await _picker.pickVideo(source: ImageSource.gallery);
      if (x != null && mounted) setState(() => _video = File(x.path));
    } catch (e) {
      _toast('영상 갤러리 실패: $e');
    }
  }

  void _clearVideo() => setState(() => _video = null);

  // ── 공유 인텐트 ───────────────────────────────────────────
  Future<void> _initShareListener() async {
    try {
      _shareSub = ReceiveSharingIntent.instance
          .getMediaStream()
          .listen(_handleSharedMedia, onError: (_) {});
      final initial =
          await ReceiveSharingIntent.instance.getInitialMedia();
      if (initial.isNotEmpty) {
        _handleSharedMedia(initial);
        ReceiveSharingIntent.instance.reset();
      }
    } catch (_) {}
  }

  void _handleSharedMedia(List<SharedMediaFile> files) {
    if (!mounted || files.isEmpty) return;
    File? firstImage;
    final textParts = <String>[];
    for (final f in files) {
      switch (f.type) {
        case SharedMediaType.image:
          firstImage ??= File(f.path);
          break;
        case SharedMediaType.text:
        case SharedMediaType.url:
          textParts.add(f.path);
          break;
        case SharedMediaType.video:
        case SharedMediaType.file:
          break;
      }
    }
    setState(() {
      if (firstImage != null) _photo = firstImage;
      if (textParts.isNotEmpty) {
        final joined = textParts.join('\n');
        _commentCtrl.text = _commentCtrl.text.isEmpty
            ? joined
            : '${_commentCtrl.text}\n$joined';
      }
    });
    _toast('공유 받음 — 검토 후 전송');
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
          _notifyNewDigest(latest.date);
          await prefs.setString(_kLastSeenDigestKey, latest.date);
        }
      }
    } catch (_) {}
  }

  // ── 음성 인식 ─────────────────────────────────────────────
  Future<void> _initRecord() async {
    try {
      var status = await Permission.microphone.status;
      if (!status.isGranted) status = await Permission.microphone.request();
      _recordAvailable = status.isGranted && await _recorder.hasPermission();
    } catch (_) {
      _recordAvailable = false;
    }
    if (mounted) setState(() {});
  }

  Future<void> _toggleAudioRecord() async {
    if (_listening) {
      String? path;
      try {
        path = await _recorder.stop();
      } catch (e) {
        AppLog.err('audio stop: $e');
      }
      if (mounted) {
        setState(() {
          _listening = false;
          if (path != null) _audioPath = path;
        });
      }
      return;
    }
    try {
      if (await _recorder.hasPermission()) {
        final dir = await getTemporaryDirectory();
        final fp =
            '${dir.path}/oracle_rec_${DateTime.now().millisecondsSinceEpoch}.m4a';
        await _recorder.start(
          const RecordConfig(encoder: AudioEncoder.aacLc),
          path: fp,
        );
        if (mounted) setState(() => _listening = true);
      } else {
        _toast('녹음 사용 불가 (마이크 권한 확인)');
      }
    } catch (e) {
      AppLog.err('audio start: $e');
      _toast('녹음 실패: $e');
    }
  }

  Future<void> _toggleVideoRecord() async {
    if (_recordingVideo) {
      await _stopVideoRecording();
    } else {
      await _startVideoRecording();
    }
  }

  // ── 전송 ──────────────────────────────────────────────────
  Future<void> _submit() async {
    if (_listening) {
      // 녹음 중이면 정지하고 오디오 확보
      try {
        final p = await _recorder.stop();
        if (p != null) _audioPath = p;
      } catch (_) {}
      if (mounted) setState(() => _listening = false);
    }

    final comment = _commentCtrl.text.trim();
    if (_photo == null &&
        comment.isEmpty &&
        _audioPath == null &&
        _video == null) {
      _toast('사진·영상·코멘트·녹음 중 하나는 있어야 해요');
      return;
    }
    final pending = _Pending(
      id: DateTime.now().microsecondsSinceEpoch.toString(),
      comment: comment.isEmpty ? null : comment,
      photo: _photo,
      audioPath: _audioPath,
      videoPath: _video?.path,
    );
    setState(() {
      _pendings.insert(0, pending);
      _photo = null;
      _video = null;
      _audioPath = null;
      _commentCtrl.clear();
    });
    unawaited(_processIngest(pending));
  }

  Future<void> _processIngest(_Pending p) async {
    try {
      final r = await _api.ingest(
        comment: p.comment,
        imageFile: p.photo,
        audioFile: p.audioPath != null ? File(p.audioPath!) : null,
        videoFile: p.videoPath != null ? File(p.videoPath!) : null,
        model: _selectedModel,
      );
      final recWithComment = Record(
        id: r.id,
        ts: r.ts,
        userComment: p.comment ?? '',
        imagePaths: r.imagePaths,
        vlmCaption: r.vlmCaption,
        insight: r.insight,
      );
      if (!mounted) return;
      setState(() {
        _pendings.removeWhere((x) => x.id == p.id);
        _records.insert(0, recWithComment);
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _pendings.removeWhere((x) => x.id == p.id));
      _toast('전송 실패: $e');
    }
  }

  Future<void> _cancelPending(_Pending p) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('이 요청 큐에서 제거?'),
        content: const Text(
          '큐에서 사라집니다. 단 백엔드가 이미 처리 중이면 결과 record는 채팅에 도착할 수 있습니다.',
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('아니요')),
          TextButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('제거')),
        ],
      ),
    );
    if (ok == true && mounted) {
      setState(() => _pendings.removeWhere((x) => x.id == p.id));
    }
  }

  // ── record 편집 (잘못 보낸 거 정정) ──────────────────────
  Future<void> _editRecord(int idx) async {
    final ctrl = TextEditingController(text: _records[idx].userComment);
    final newText = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) {
        return Padding(
          padding: EdgeInsets.fromLTRB(
            16,
            16,
            16,
            MediaQuery.of(ctx).viewInsets.bottom + 16,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('코멘트 수정',
                  style: Theme.of(ctx).textTheme.titleMedium),
              const SizedBox(height: 12),
              TextField(
                controller: ctrl,
                autofocus: true,
                minLines: 2,
                maxLines: 5,
                decoration: const InputDecoration(
                  border: OutlineInputBorder(),
                  hintText: '코멘트 (비우면 빈 코멘트로 갱신)',
                ),
              ),
              const SizedBox(height: 8),
              Text(
                '* vault 정본 평문은 변경되지 않습니다(append-only). UI source(Mongo)만 갱신.',
                style: Theme.of(ctx).textTheme.bodySmall?.copyWith(
                      color: Theme.of(ctx).colorScheme.outline,
                    ),
              ),
              const SizedBox(height: 12),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: () => Navigator.pop(ctx, null),
                    child: const Text('취소'),
                  ),
                  const SizedBox(width: 8),
                  FilledButton(
                    onPressed: () => Navigator.pop(ctx, ctrl.text),
                    child: const Text('저장'),
                  ),
                ],
              ),
            ],
          ),
        );
      },
    );
    if (newText == null || !mounted) return;
    try {
      await _api.updateComment(_records[idx].id, newText);
      setState(() {
        _records[idx] = Record(
          id: _records[idx].id,
          ts: _records[idx].ts,
          userComment: newText,
          imagePaths: _records[idx].imagePaths,
          vlmCaption: _records[idx].vlmCaption,
          insight: _records[idx].insight,
          reaction: _records[idx].reaction,
        );
      });
    } catch (e) {
      _toast('수정 실패: $e');
    }
  }

  // ── 기록 무한 스크롤 ──────────────────────────────────────
  void _onScroll() {
    if (_scroll.position.pixels >= _scroll.position.maxScrollExtent - 200) {
      _load();
    }
  }

  Future<void> _load({bool initial = false}) async {
    if (_loading || (!initial && !_hasMore)) return;
    setState(() => _loading = true);
    try {
      final more =
          await _api.listRecent(limit: 30, offset: _records.length);
      setState(() {
        _records.addAll(more);
        _hasMore = more.length >= 30;
      });
    } catch (e) {
      _toast('읽기 실패: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// 최신부터 다시 로드 (당겨서 새로고침 · 앱 복귀 시).
  Future<void> _refresh() async {
    if (!mounted) return;
    setState(() {
      _records.clear();
      _hasMore = true;
    });
    await _load(initial: true);
    await _loadLatestDigest();
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
    setState(() =>
        _selectedModel = (alias == null || alias.isEmpty) ? null : alias);
  }

  Future<void> _openLlmPicker() async {
    final picked = await showLlmPicker(context, _api, _selectedModel);
    if (picked == null) return;
    await _saveSelectedModel(picked.isEmpty ? null : picked);
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(msg)));
  }

  // ── 빌드 ───────────────────────────────────────────────────
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
            onPressed: () => Navigator.push(context,
                MaterialPageRoute(builder: (_) => DigestScreen(api: _api))),
          ),
        ],
      ),
      body: SafeArea(
        top: false,
        child: TabBarView(
          controller: _tab,
          children: [
            _buildHomeTab(),
            RefreshIndicator(onRefresh: _refresh, child: _buildChatList()),
            _buildRecordTab(),
          ],
        ),
      ),
    );
  }

  // 홈 — 비활성 placeholder (추후 채움)
  Widget _buildHomeTab() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.home_outlined,
                size: 56, color: Theme.of(context).disabledColor),
            const SizedBox(height: 12),
            Text('홈은 곧 채워질 예정이에요',
                style: TextStyle(color: Theme.of(context).disabledColor)),
          ],
        ),
      ),
    );
  }

  // 기록 — 카메라 프리뷰 + 사진/영상/음성 + 텍스트 + 전송
  Widget _buildRecordTab() {
    return Column(
      children: [
        Expanded(
          child: ClipRect(
            child: Container(
              color: Colors.black,
              width: double.infinity,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  _cameraOrPhoto(),
                  // 우상단 반투명 갤러리 버튼
                  Positioned(
                    top: 8,
                    right: 8,
                    child: Material(
                      color: Colors.black38,
                      shape: const CircleBorder(),
                      child: IconButton(
                        icon: const Icon(Icons.photo_library_outlined,
                            color: Colors.white),
                        tooltip: '갤러리',
                        onPressed: _pickFromGalleryMenu,
                      ),
                    ),
                  ),
                  // 첨부 제거
                  if (_photo != null || _video != null)
                    Positioned(
                      top: 8,
                      left: 8,
                      child: Material(
                        color: Colors.black54,
                        shape: const CircleBorder(),
                        child: IconButton(
                          icon: const Icon(Icons.close, color: Colors.white),
                          tooltip: '첨부 제거',
                          onPressed: () {
                            _clearPhoto();
                            _clearVideo();
                          },
                        ),
                      ),
                    ),
                  // 음성 녹음 오버레이
                  if (_listening)
                    Container(
                      color: Colors.black54,
                      child: const Center(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(Icons.mic, color: Colors.redAccent, size: 64),
                            SizedBox(height: 12),
                            Text('녹음 중… 음성 버튼을 다시 눌러 정지',
                                style: TextStyle(color: Colors.white)),
                          ],
                        ),
                      ),
                    ),
                  // 영상 녹화 표시
                  if (_recordingVideo)
                    const Positioned(
                      top: 12,
                      left: 0,
                      right: 0,
                      child: Center(
                        child: Chip(
                          backgroundColor: Colors.red,
                          label: Text('● 녹화 중',
                              style: TextStyle(color: Colors.white)),
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 8),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceEvenly,
            children: [
              _captureButton(
                icon: Icons.photo_camera_outlined,
                label: '사진',
                onTap: _cameraReady ? _capture : null,
              ),
              _captureButton(
                icon: _recordingVideo ? Icons.stop : Icons.videocam_outlined,
                label: '영상',
                active: _recordingVideo,
                onTap: _cameraReady ? _toggleVideoRecord : null,
              ),
              _captureButton(
                icon: _listening ? Icons.stop : Icons.mic_none_outlined,
                label: '음성',
                active: _listening,
                onTap: _recordAvailable ? _toggleAudioRecord : null,
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8),
          child: TextField(
            controller: _commentCtrl,
            decoration: const InputDecoration(
              hintText: '코멘트(선택) · 텍스트만 보내도 OK',
              border: OutlineInputBorder(),
              isDense: true,
            ),
            minLines: 1,
            maxLines: 3,
            textInputAction: TextInputAction.newline,
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(8, 8, 8, 12),
          child: SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              icon: const Icon(Icons.send),
              label: const Text('전송'),
              onPressed: _submit,
            ),
          ),
        ),
      ],
    );
  }

  Widget _captureButton({
    required IconData icon,
    required String label,
    required VoidCallback? onTap,
    bool active = false,
  }) {
    final color = active ? Theme.of(context).colorScheme.error : null;
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        IconButton.filledTonal(
          icon: Icon(icon, color: color),
          iconSize: 28,
          onPressed: onTap,
          tooltip: label,
        ),
        const SizedBox(height: 2),
        Text(label, style: TextStyle(fontSize: 12, color: color)),
      ],
    );
  }

  Future<void> _pickFromGalleryMenu() async {
    final choice = await showModalBottomSheet<String>(
      context: context,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.photo_outlined),
              title: const Text('사진'),
              onTap: () => Navigator.pop(context, 'photo'),
            ),
            ListTile(
              leading: const Icon(Icons.movie_outlined),
              title: const Text('영상'),
              onTap: () => Navigator.pop(context, 'video'),
            ),
          ],
        ),
      ),
    );
    if (choice == 'photo') await _pickFromGallery();
    if (choice == 'video') await _pickVideoFromGallery();
  }

  Widget _buildChatList() {
    final showDigestCard = _latestDigest != null;
    final total =
        _records.length + _pendings.length + (showDigestCard ? 1 : 0);
    return ListView.builder(
      controller: _scroll,
      reverse: true,
      padding: const EdgeInsets.symmetric(vertical: 8),
      itemCount: total,
      itemBuilder: (ctx, i) {
        if (showDigestCard && i == total - 1) {
          return _DigestPreviewCard(
            api: _api,
            entry: _latestDigest!,
            onTap: () {
              Navigator.push(
                context,
                MaterialPageRoute(builder: (_) => DigestScreen(api: _api)),
              );
            },
          );
        }
        final idx0 = i;
        if (idx0 < _pendings.length) {
          final p = _pendings[idx0];
          return GestureDetector(
            onTap: () => _cancelPending(p),
            child: _PendingBubble(comment: p.comment, photo: p.photo),
          );
        }
        final idx = idx0 - _pendings.length;
        return GestureDetector(
          onLongPress: () => _editRecord(idx),
          child: _RecordBubble(
            record: _records[idx],
            api: _api,
            onReact: (emoji) async {
              try {
                await _api.setReaction(_records[idx].id, emoji);
                setState(() {
                  _records[idx] = Record(
                    id: _records[idx].id,
                    ts: _records[idx].ts,
                    userComment: _records[idx].userComment,
                    imagePaths: _records[idx].imagePaths,
                    vlmCaption: _records[idx].vlmCaption,
                    insight: _records[idx].insight,
                    reaction: emoji,
                  );
                });
              } catch (e) {
                _toast('반응 실패: $e');
              }
            },
          ),
        );
      },
    );
  }

  Widget _cameraOrPhoto() {
    if (_photo != null) {
      return Image.file(_photo!, fit: BoxFit.cover);
    }
    if (_video != null) {
      return GestureDetector(
        onTap: _clearVideo,
        child: Container(
          color: Colors.black,
          child: const Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.videocam, color: Colors.white, size: 48),
                SizedBox(height: 8),
                Text('영상 첨부됨 · 탭해서 제거',
                    style: TextStyle(color: Colors.white)),
              ],
            ),
          ),
        ),
      );
    }
    if (_cameraReady && _camera != null) {
      return FittedBox(
        fit: BoxFit.cover,
        child: SizedBox(
          width: _camera!.value.previewSize?.height ?? 1,
          height: _camera!.value.previewSize?.width ?? 1,
          child: CameraPreview(_camera!),
        ),
      );
    }
    if (_cameraError != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Text(
            _cameraError!,
            textAlign: TextAlign.center,
            style: const TextStyle(color: Colors.white),
          ),
        ),
      );
    }
    return const Center(
        child: CircularProgressIndicator(color: Colors.white));
  }
}

// ── 다이제스트 미리보기 카드 ──────────────────────────────────

class _DigestPreviewCard extends StatefulWidget {
  final OracleApi api;
  final DigestEntry entry;
  final VoidCallback onTap;
  const _DigestPreviewCard({
    required this.api,
    required this.entry,
    required this.onTap,
  });
  @override
  State<_DigestPreviewCard> createState() => _DigestPreviewCardState();
}

class _DigestPreviewCardState extends State<_DigestPreviewCard> {
  String? _preview;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final body = await widget.api.getDigest(widget.entry.date);
      if (!mounted) return;
      final lines = body
          .split('\n')
          .where((l) => l.trim().isNotEmpty && !l.startsWith('#'))
          .toList();
      final preview = lines.take(2).join(' ').trim();
      setState(() => _preview = preview.isEmpty ? '(빈 다이제스트)' : preview);
    } catch (_) {
      if (mounted) setState(() => _preview = '(미리보기 실패)');
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: InkWell(
        onTap: widget.onTap,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
          decoration: BoxDecoration(
            color: cs.secondaryContainer,
            borderRadius: BorderRadius.circular(12),
          ),
          child: Row(
            children: [
              Icon(Icons.auto_stories, color: cs.onSecondaryContainer),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '📓 ${widget.entry.date} 다이제스트',
                      style: TextStyle(
                        fontWeight: FontWeight.bold,
                        color: cs.onSecondaryContainer,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      _preview ?? '(불러오는 중...)',
                      style: TextStyle(color: cs.onSecondaryContainer),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
              Icon(Icons.chevron_right, color: cs.onSecondaryContainer),
            ],
          ),
        ),
      ),
    );
  }
}

// ── 버블 위젯들 ───────────────────────────────────────────────

class _PendingBubble extends StatelessWidget {
  final String? comment;
  final File? photo;
  const _PendingBubble({this.comment, this.photo});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (photo != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: Image.file(
                  photo!,
                  width: 180,
                  height: 180,
                  fit: BoxFit.cover,
                ),
              ),
            ),
          if (comment != null && comment!.isNotEmpty)
            _userBubble(context, comment!),
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
                const SizedBox(width: 8),
                const Text('생각 중...'),
                const SizedBox(width: 6),
                Text(
                  '· 탭해서 큐에서 제거',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.outline,
                      ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _RecordBubble extends StatelessWidget {
  final Record record;
  final OracleApi api;
  final Future<void> Function(String) onReact;
  const _RecordBubble({
    required this.record,
    required this.api,
    required this.onReact,
  });

  @override
  Widget build(BuildContext context) {
    final tsLocal = record.ts.toLocal();
    final tsStr = DateFormat('M/d HH:mm').format(tsLocal);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            tsStr,
            style: Theme.of(context)
                .textTheme
                .bodySmall
                ?.copyWith(color: Colors.grey),
          ),
          const SizedBox(height: 4),
          if (record.imagePaths.isNotEmpty)
            Align(
              alignment: Alignment.centerRight,
              child: Wrap(
                alignment: WrapAlignment.end,
                spacing: 4,
                runSpacing: 4,
                children: record.imagePaths.map((rel) {
                  return ClipRRect(
                    borderRadius: BorderRadius.circular(10),
                    child: Image.network(
                      api.photoUrl(rel),
                      width: 160,
                      height: 160,
                      fit: BoxFit.cover,
                      errorBuilder: (_, _, _) => Container(
                        width: 160,
                        height: 160,
                        color: Theme.of(context)
                            .colorScheme
                            .surfaceContainerHighest,
                        child: const Center(child: Text('📷')),
                      ),
                      loadingBuilder: (ctx, child, progress) =>
                          progress == null
                              ? child
                              : Container(
                                  width: 160,
                                  height: 160,
                                  color: Theme.of(context)
                                      .colorScheme
                                      .surfaceContainerHighest,
                                  child: const Center(
                                    child: SizedBox(
                                      width: 22,
                                      height: 22,
                                      child: CircularProgressIndicator(
                                          strokeWidth: 2),
                                    ),
                                  ),
                                ),
                    ),
                  );
                }).toList(),
              ),
            ),
          if (record.userComment.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: _userBubble(context, record.userComment),
            ),
          if (record.insight.isNotEmpty) ...[
            const SizedBox(height: 6),
            Align(
              alignment: Alignment.centerLeft,
              child: ConstrainedBox(
                constraints: BoxConstraints(
                  maxWidth: MediaQuery.of(context).size.width * 0.82,
                ),
                child: Container(
                  padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
                  decoration: BoxDecoration(
                    color: Theme.of(context)
                        .colorScheme
                        .surfaceContainerHighest,
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: MarkdownBody(
                    data: record.insight,
                    selectable: true,
                  ),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.only(top: 4, left: 6),
              child: Row(
                children: [
                  _reactChip(context, '🤔', 'interesting',
                      record.reaction == 'interesting'),
                  _reactChip(context, '👍', 'useful',
                      record.reaction == 'useful'),
                  _reactChip(
                      context, '💤', 'skip', record.reaction == 'skip'),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _reactChip(
      BuildContext context, String emoji, String key, bool selected) {
    return Padding(
      padding: const EdgeInsets.only(right: 6),
      child: InkWell(
        onTap: () => onReact(key),
        borderRadius: BorderRadius.circular(12),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
          decoration: BoxDecoration(
            color: selected
                ? Theme.of(context).colorScheme.primaryContainer
                : Colors.transparent,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Theme.of(context).dividerColor),
          ),
          child: Text(emoji, style: const TextStyle(fontSize: 14)),
        ),
      ),
    );
  }
}

Widget _userBubble(BuildContext context, String text) {
  final cs = Theme.of(context).colorScheme;
  return Align(
    alignment: Alignment.centerRight,
    child: ConstrainedBox(
      constraints: BoxConstraints(
        maxWidth: MediaQuery.of(context).size.width * 0.78,
      ),
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 2),
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
        decoration: BoxDecoration(
          color: cs.primary,
          borderRadius: BorderRadius.circular(14),
        ),
        child: Text(text, style: TextStyle(color: cs.onPrimary)),
      ),
    ),
  );
}

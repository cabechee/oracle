import 'dart:async';
import 'dart:io';

import 'package:camera/camera.dart';
import 'package:flutter/widgets.dart';
import 'package:image_picker/image_picker.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:receive_sharing_intent/receive_sharing_intent.dart';
import 'package:record/record.dart';
import 'package:path_provider/path_provider.dart';

import '../../api.dart';
import '../actions/capture_action.dart';
import '../../applog.dart';
import '../../core/record_store.dart';
import '../../models.dart';

/// 캡처 입력 도메인 — 카메라·영상·오디오·갤러리·공유인텐트 + 전송(ingest).
///
/// BuildContext 미접근. UI 알림은 [onToast], 선택 모델은 [modelProvider]로 주입받고,
/// 결과 record는 [store]에만 반영(chat 모듈과 디커플).
class CaptureController extends ChangeNotifier {
  CaptureController({
    required this.api,
    required this.store,
    required this.onToast,
    required this.modelProvider,
  });

  final OracleApi api;
  final RecordStore store;
  final void Function(String) onToast;
  final String? Function() modelProvider;

  bool _disposed = false;
  void _notify() {
    if (!_disposed) notifyListeners();
  }

  // ── 카메라 ─────────────────────────────────────────────────
  CameraController? camera;
  bool cameraReady = false;
  String? cameraError;

  /// init 세대 — pause·재init가 진행 중인 init를 무효화.
  /// (권한 다이얼로그가 inactive→onAppPause를 유발해 resume이 두 번째 init를
  /// 시작하는데, 가드 없으면 컨트롤러 2개가 생기고 하나는 dispose 없이 누수.)
  int _camEpoch = 0;

  // ── 입력 ───────────────────────────────────────────────────
  final List<File> photos = [];   // 여러 장 연속 촬영 — 한 번에 전송
  File? video;
  bool recordingVideo = false;
  final TextEditingController commentCtrl = TextEditingController();

  // ── 음성: 순수 녹음 ────────────────────────────────────────
  bool listening = false;
  final AudioRecorder _recorder = AudioRecorder();
  bool recordAvailable = false;
  String? _audioPath;

  // ── 갤러리·외부 공유 ───────────────────────────────────────
  final ImagePicker _picker = ImagePicker();
  StreamSubscription<List<SharedMediaFile>>? _shareSub;

  /// 홈에서 1회 호출 — 카메라·녹음·공유 리스너 초기화.
  void init() {
    initCamera();
    initRecord();
    initShareListener();
  }

  @override
  void dispose() {
    _disposed = true;
    camera?.dispose();
    _recorder.dispose();
    commentCtrl.dispose();
    _shareSub?.cancel();
    super.dispose();
  }

  // ── 앱 생명주기 (홈이 전달) ────────────────────────────────
  void onAppPause() {
    AppLog.life('앱 background (pause)');
    _camEpoch++; // 진행 중 init 무효화
    final cam = camera;
    camera = null;
    cameraReady = false;
    if (cam != null) unawaited(_teardownCamera(cam));
    _notify();
  }

  /// pause 시 카메라 정리 — 녹화 중이었다면 지금까지 분량을 첨부로 회수.
  /// (리셋 없이 dispose만 하면 recordingVideo가 영영 true로 남아 영상 버튼이 잠김.)
  Future<void> _teardownCamera(CameraController cam) async {
    if (recordingVideo) {
      recordingVideo = false;
      try {
        final f = await cam.stopVideoRecording();
        if (!_disposed) {
          video = File(f.path);
          _notify();
        }
      } catch (_) {} // 회수 실패 — 녹화분 유실(상태는 리셋됨)
    }
    try {
      await cam.dispose();
    } catch (_) {}
  }

  void onAppResume() {
    AppLog.life('앱 foreground (resume)');
    if (!cameraReady) initCamera();
  }

  // ── 카메라 ───────────────────────────────────────────────
  Future<void> initCamera() async {
    final epoch = ++_camEpoch;
    try {
      var status = await Permission.camera.status;
      if (!status.isGranted) {
        status = await Permission.camera.request();
      }
      // 권한 다이얼로그 동안 pause→resume이 새 init를 시작했을 수 있음 — 이 init는 양보.
      if (_disposed || epoch != _camEpoch) return;
      if (!status.isGranted) {
        cameraError = '카메라 권한 거부됨 — 설정에서 허용 필요';
        _notify();
        return;
      }
      final cams = await availableCameras();
      if (_disposed || epoch != _camEpoch) return;
      if (cams.isEmpty) {
        cameraError = '카메라를 찾을 수 없음';
        _notify();
        return;
      }
      final back = cams.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.back,
        orElse: () => cams.first,
      );
      final ctrl = CameraController(back, ResolutionPreset.high,
          enableAudio: true); // 영상 녹화에 소리 포함
      await ctrl.initialize();
      if (_disposed || epoch != _camEpoch) {
        await ctrl.dispose(); // 그 사이 pause/새 init 발생 — 이 컨트롤러는 폐기
        return;
      }
      camera = ctrl;
      cameraReady = true;
      cameraError = null;
      _notify();
    } catch (e) {
      if (epoch == _camEpoch) {
        cameraError = '$e';
        _notify();
      }
    }
  }

  /// 카메라가 준비될 때까지 잠깐 대기(콜드 스타트 직후 init 중이면 ~수백ms).
  /// 첫 탭이 미준비 카메라에 떨어져 무시되던 문제 방지. 권한거부 등은 즉시 false.
  Future<bool> _ensureCameraReady({int timeoutMs = 4000}) async {
    final steps = timeoutMs ~/ 100;
    for (var i = 0; i < steps; i++) {
      if (_disposed) return false;
      if (cameraReady && camera != null) return true;
      if (cameraError != null && camera == null) return false;
      await Future<void>.delayed(const Duration(milliseconds: 100));
    }
    return cameraReady && camera != null;
  }

  /// 한 장 촬영해 photos에 추가(연속 촬영 누적). 성공하면 true.
  Future<bool> capture() async {
    // 콜드 스타트 직후 카메라가 막 init 중일 수 있음 — 준비될 때까지 잠깐 대기 후 촬영.
    if (!await _ensureCameraReady()) {
      // 권한 거부는 프리뷰 영역에 에러 표시됨 — 그 외(준비 지연)는 무반응 대신 안내.
      if (cameraError == null && !_disposed) {
        onToast('카메라가 아직 준비 중 — 잠시 후 다시 시도해주세요');
      }
      return false;
    }
    // 막 띄운 직후 첫 takePicture가 미정착으로 간헐 실패 → 1회 자동 재시도.
    for (var attempt = 0; attempt < 2; attempt++) {
      final cam = camera;
      if (cam == null || _disposed) return false;
      try {
        final pic = await cam.takePicture();
        if (_disposed) return false;
        photos.add(File(pic.path));
        AppLog.media('사진 촬영 — ${photos.length}장째 (recordingVideo=$recordingVideo)');
        _notify();
        return true;
      } catch (e) {
        if (attempt == 0) {
          await Future<void>.delayed(const Duration(milliseconds: 300));
          continue;
        }
        onToast('촬영 실패: $e');
      }
    }
    return false;
  }

  void removePhotoAt(int i) {
    if (i >= 0 && i < photos.length) {
      photos.removeAt(i);
      _notify();
    }
  }

  void clearVideo() {
    video = null;
    _notify();
  }

  void clearAttachments() {
    photos.clear();
    video = null;
    _notify();
  }

  // ── 갤러리 ─────────────────────────────────────────────────
  Future<void> pickFromGallery() async {
    try {
      final xs = await _picker.pickMultiImage(
        imageQuality: 85,
        maxWidth: 2048,
      );
      if (xs.isNotEmpty && !_disposed) {
        photos.addAll(xs.map((x) => File(x.path)));
        _notify();
      }
    } catch (e) {
      onToast('갤러리 실패: $e');
    }
  }

  Future<void> pickVideoFromGallery() async {
    try {
      final x = await _picker.pickVideo(source: ImageSource.gallery);
      if (x != null && !_disposed) {
        video = File(x.path);
        _notify();
      }
    } catch (e) {
      onToast('영상 갤러리 실패: $e');
    }
  }

  // ── 영상 녹화 ──────────────────────────────────────────────
  Future<void> startVideoRecording() async {
    if (!cameraReady || camera == null || camera!.value.isRecordingVideo) {
      return;
    }
    try {
      await camera!.startVideoRecording();
      recordingVideo = true;
      AppLog.media('영상 녹화 시작');
      _notify();
    } catch (e) {
      onToast('영상 녹화 실패: $e');
    }
  }

  Future<void> stopVideoRecording() async {
    if (camera == null || !camera!.value.isRecordingVideo) {
      // 카메라가 사라졌거나(pause 후 재init) 녹화 상태가 증발 — UI 고착 방지.
      if (recordingVideo) {
        recordingVideo = false;
        _notify();
      }
      return;
    }
    try {
      final f = await camera!.stopVideoRecording();
      if (_disposed) return;
      recordingVideo = false;
      video = File(f.path);
      AppLog.media('영상 녹화 정지 — 첨부됨');
      _notify();
    } catch (e) {
      recordingVideo = false;
      _notify();
      onToast('영상 저장 실패: $e');
    }
  }

  Future<void> toggleVideoRecord() async {
    if (recordingVideo) {
      await stopVideoRecording();
    } else {
      await startVideoRecording();
    }
  }

  // ── 공유 인텐트 ───────────────────────────────────────────
  Future<void> initShareListener() async {
    try {
      _shareSub = ReceiveSharingIntent.instance
          .getMediaStream()
          .listen(handleSharedMedia, onError: (_) {});
      final initial = await ReceiveSharingIntent.instance.getInitialMedia();
      if (initial.isNotEmpty) {
        handleSharedMedia(initial);
        ReceiveSharingIntent.instance.reset();
      }
    } catch (_) {}
  }

  void handleSharedMedia(List<SharedMediaFile> files) {
    if (_disposed || files.isEmpty) return;
    final sharedImages = <File>[];
    File? firstVideo;
    final textParts = <String>[];
    for (final f in files) {
      switch (f.type) {
        case SharedMediaType.image:
          sharedImages.add(File(f.path));
          break;
        case SharedMediaType.video:
          firstVideo ??= File(f.path);
          break;
        case SharedMediaType.text:
        case SharedMediaType.url:
          textParts.add(f.path);
          break;
        case SharedMediaType.file:
          break;
      }
    }
    if (sharedImages.isEmpty && firstVideo == null && textParts.isEmpty) {
      return; // 받을 수 있는 게 없으면 토스트도 X (빈 "공유 받음" 방지)
    }
    if (sharedImages.isNotEmpty) photos.addAll(sharedImages);
    if (firstVideo != null) video = firstVideo;
    if (textParts.isNotEmpty) {
      final joined = textParts.join('\n');
      commentCtrl.text = commentCtrl.text.isEmpty
          ? joined
          : '${commentCtrl.text}\n$joined';
    }
    AppLog.media('공유 수신 — 사진 ${sharedImages.length} 영상 ${firstVideo != null ? 1 : 0} 텍스트 ${textParts.length}');
    _notify();
    onToast('공유 받음 — 검토 후 전송');
  }

  // ── 음성 녹음 ──────────────────────────────────────────────
  Future<void> initRecord() async {
    try {
      var status = await Permission.microphone.status;
      if (!status.isGranted) status = await Permission.microphone.request();
      recordAvailable = status.isGranted && await _recorder.hasPermission();
    } catch (_) {
      recordAvailable = false;
    }
    _notify();
  }

  Future<void> toggleAudioRecord() async {
    if (listening) {
      String? path;
      try {
        path = await _recorder.stop();
      } catch (e) {
        AppLog.err('audio stop: $e');
      }
      listening = false;
      if (path != null) _audioPath = path;
      AppLog.media('음성 녹음 정지');
      _notify();
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
        listening = true;
        AppLog.media('음성 녹음 시작');
        _notify();
      } else {
        onToast('녹음 사용 불가 (마이크 권한 확인)');
      }
    } catch (e) {
      AppLog.err('audio start: $e');
      onToast('녹음 실패: $e');
    }
  }

  // ── 전송 ──────────────────────────────────────────────────
  Future<void> submit() async {
    if (listening) {
      // 녹음 중이면 정지하고 오디오 확보
      try {
        final p = await _recorder.stop();
        if (p != null) _audioPath = p;
      } catch (_) {}
      listening = false;
    }
    final wasRecording = recordingVideo;
    if (recordingVideo) {
      // 녹화 중 전송 = 녹화 종료 후 영상 첨부 (음성과 동일 동작 — 조용한 누락 방지)
      AppLog.media('전송 시점에 녹화 중이었음 → 영상 정지·첨부');
      await stopVideoRecording();
    }

    final comment = commentCtrl.text.trim();
    // 아무것도 없는 상태에서 전송 = 지금 프리뷰를 즉석 촬영해 보냄
    // (앱 켜고 바로 전송 누르는 흐름 — 셔터를 따로 누를 필요 없게).
    if (photos.isEmpty && comment.isEmpty && _audioPath == null && video == null) {
      await capture();
      if (photos.isEmpty) return; // 촬영 실패(준비 중·권한 등) — capture가 토스트
    }
    // 폰 도구화 — 코멘트에 명시 시간 명령이 있으면 LLM 전에 0초로 실행.
    final action = parseCaptureAction(comment);
    if (action != null) {
      runCaptureAction(action);
      onToast(action.toast);
    }
    final pending = PendingCapture(
      id: DateTime.now().microsecondsSinceEpoch.toString(),
      comment: comment.isEmpty ? null : comment,
      photos: List.of(photos),
      audioPath: _audioPath,
      videoPath: video?.path,
    );
    // 전송 페이로드 — 사진/영상 오전송 진단의 핵심 (사진 의도인데 영상이 첨부된 경우 등)
    final kinds = <String>[
      if (pending.photos.isNotEmpty) '사진 ${pending.photos.length}장',
      if (pending.videoPath != null) '영상',
      if (pending.audioPath != null) '음성',
      if ((pending.comment ?? '').isNotEmpty) '코멘트',
    ];
    AppLog.media('전송 — ${kinds.isEmpty ? "(빈)" : kinds.join(", ")}'
        '${wasRecording ? " [녹화중 전송]" : ""}');
    store.addPending(pending);
    photos.clear();
    video = null;
    _audioPath = null;
    commentCtrl.clear();
    _notify();
    // 무엇을 보냈는지 토스트에 명시 — 영상 오전송을 즉시 알아채게.
    if (action == null) {
      onToast(kinds.isEmpty
          ? '전송됨 — 흐름 탭에서 확인'
          : '${kinds.join(" · ")} 전송됨 — 흐름 탭에서 확인');
    }
    unawaited(_processIngest(pending));
  }

  // ── 지나간 사진 백필 (웹 흐름 탭) ──────────────────────────
  /// 미처 못 올린 사진을 EXIF 촬영시각으로 흐름에 밀어넣는다.
  /// 베르 즉답은 맥락 없이 간결(백엔드 backfill 처리). 경로 없는 웹이라 bytes로 업로드.
  Future<void> backfillUpload() async {
    List<XFile> xs;
    try {
      xs = await _picker.pickMultiImage(imageQuality: 90);
    } catch (e) {
      onToast('사진 선택 실패: $e');
      return;
    }
    if (xs.isEmpty) return;
    onToast('${xs.length}장 올리는 중 — 지난 사진으로');
    for (final x in xs) {
      final bytes = await x.readAsBytes();
      final id = 'bf-${DateTime.now().microsecondsSinceEpoch}-${x.name}';
      store.addPending(PendingCapture(id: id, comment: '지난 사진'));
      unawaited(_processBackfill(id, bytes, x.name));
    }
  }

  Future<void> _processBackfill(
      String pendingId, List<int> bytes, String name) async {
    try {
      final stub = await api.ingest(
        imageBytesList: [(bytes: bytes, name: name)],
        backfill: true,
      );
      for (final p in store.pendings) {
        if (p.id == pendingId) p.recordId = stub.id;
      }
      for (var i = 0; i < 95; i++) {
        await Future<void>.delayed(Duration(seconds: i < 6 ? 2 : 4));
        if (_disposed) return;
        if (!store.pendings.any((x) => x.id == pendingId)) return; // 취소됨
        Record r;
        try {
          r = await api.getRecord(stub.id);
        } catch (_) {
          continue;
        }
        if (!r.isProcessing) {
          store.resolvePending(pendingId, r);
          return;
        }
      }
      store.removePending(pendingId);
    } catch (e) {
      store.removePending(pendingId);
      onToast('백필 실패: $e');
    }
  }

  Future<void> _processIngest(PendingCapture p) async {
    try {
      // 비동기 인입 — 업로드 직후 stub(status=processing)이 오고, LLM 처리는
      // 백엔드에서 계속된다. 백엔드는 쿠키(quick)를 먼저 채우고 베르(insight)는 나중.
      final stub = await api.ingest(
        comment: p.comment,
        imageFiles: p.photos,
        audioFile: p.audioPath != null ? File(p.audioPath!) : null,
        videoFile: p.videoPath != null ? File(p.videoPath!) : null,
        model: modelProvider(),
      );
      p.recordId = stub.id; // 취소·삭제 시 이 record(쿠키 반응 포함) 숨김용
      AppLog.net('ingest 완료 → ${stub.id} '
          '(img ${p.photos.length} vid ${p.videoPath != null ? 1 : 0} aud ${p.audioPath != null ? 1 : 0})');
      // 폴링 — done까지 기다리지 않는다. 쿠키 한마디가 먼저 도착하면 그 순간
      // pending('현상 중')을 record로 교체해 쿠키를 띄우고(베르는 빈 채로), done이
      // 되면 베르까지 채워 갱신. 초반은 촘촘히(쿠키가 몇 초 내 옴), 이후 4s.
      var shown = false;
      for (var i = 0; i < 95; i++) {
        await Future<void>.delayed(i < 6
            ? const Duration(milliseconds: 1500)
            : const Duration(seconds: 4));
        if (_disposed) return;
        Record r;
        try {
          r = await api.getRecord(stub.id);
        } catch (_) {
          continue; // 일시 네트워크 — 다음 턴 재시도
        }
        if (!r.isProcessing) {
          // 완료 — 최종 반영 (이미 띄웠으면 그 자리를 갱신)
          if (shown) {
            store.updateById(r.id, (_) => r);
          } else {
            store.resolvePending(p.id, r);
          }
          return;
        }
        // 아직 처리 중 — 쿠키가 왔으면 먼저 띄운다(베르 기다리지 않음)
        if (!shown && (r.quickText ?? '').isNotEmpty) {
          store.resolvePending(p.id, r);
          shown = true;
        }
      }
      // 폴링 한도 초과 — 아직 못 띄웠으면 stub로 (히스토리 refresh가 나중에 완성본 갱신)
      if (!shown && !_disposed) {
        store.resolvePending(
          p.id,
          Record(
            id: stub.id,
            ts: stub.ts,
            userComment: p.comment ?? '',
            imagePaths: stub.imagePaths,
            audioPaths: stub.audioPaths,
            videoPaths: stub.videoPaths,
            vlmCaption: stub.vlmCaption,
            insight: stub.insight,
            status: stub.status,
          ),
        );
      }
    } catch (e) {
      store.removePending(p.id);
      onToast('전송 실패: $e');
    }
  }
}

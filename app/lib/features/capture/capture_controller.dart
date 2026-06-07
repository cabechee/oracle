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

  // ── 입력 ───────────────────────────────────────────────────
  File? photo;
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
    camera?.dispose();
    camera = null;
    cameraReady = false;
    _notify();
  }

  void onAppResume() {
    if (!cameraReady) initCamera();
  }

  // ── 카메라 ───────────────────────────────────────────────
  Future<void> initCamera() async {
    try {
      var status = await Permission.camera.status;
      if (!status.isGranted) {
        status = await Permission.camera.request();
      }
      if (!status.isGranted) {
        cameraError = '카메라 권한 거부됨 — 설정에서 허용 필요';
        _notify();
        return;
      }
      final cams = await availableCameras();
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
      if (_disposed) {
        await ctrl.dispose();
        return;
      }
      camera = ctrl;
      cameraReady = true;
      cameraError = null;
      _notify();
    } catch (e) {
      cameraError = '$e';
      _notify();
    }
  }

  Future<void> capture() async {
    if (!cameraReady || camera == null) return;
    // 막 띄운 직후 첫 takePicture가 카메라 미정착으로 간헐 실패 → 1회 자동 재시도.
    for (var attempt = 0; attempt < 2; attempt++) {
      final cam = camera;
      if (cam == null || _disposed) return;
      try {
        final pic = await cam.takePicture();
        if (_disposed) return;
        photo = File(pic.path);
        _notify();
        return;
      } catch (e) {
        if (attempt == 0) {
          await Future<void>.delayed(const Duration(milliseconds: 300));
          continue;
        }
        onToast('촬영 실패: $e');
      }
    }
  }

  void clearPhoto() {
    photo = null;
    _notify();
  }

  void clearVideo() {
    video = null;
    _notify();
  }

  void clearAttachments() {
    photo = null;
    video = null;
    _notify();
  }

  // ── 갤러리 ─────────────────────────────────────────────────
  Future<void> pickFromGallery() async {
    try {
      final x = await _picker.pickImage(
        source: ImageSource.gallery,
        imageQuality: 85,
        maxWidth: 2048,
      );
      if (x != null && !_disposed) {
        photo = File(x.path);
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
      _notify();
    } catch (e) {
      onToast('영상 녹화 실패: $e');
    }
  }

  Future<void> stopVideoRecording() async {
    if (camera == null || !camera!.value.isRecordingVideo) return;
    try {
      final f = await camera!.stopVideoRecording();
      if (_disposed) return;
      recordingVideo = false;
      video = File(f.path);
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
    if (firstImage != null) photo = firstImage;
    if (textParts.isNotEmpty) {
      final joined = textParts.join('\n');
      commentCtrl.text = commentCtrl.text.isEmpty
          ? joined
          : '${commentCtrl.text}\n$joined';
    }
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

    final comment = commentCtrl.text.trim();
    if (photo == null && comment.isEmpty && _audioPath == null && video == null) {
      onToast('사진·영상·코멘트·녹음 중 하나는 있어야 해요');
      return;
    }
    final pending = PendingCapture(
      id: DateTime.now().microsecondsSinceEpoch.toString(),
      comment: comment.isEmpty ? null : comment,
      photo: photo,
      audioPath: _audioPath,
      videoPath: video?.path,
    );
    store.addPending(pending);
    photo = null;
    video = null;
    _audioPath = null;
    commentCtrl.clear();
    _notify();
    onToast('전송됨 — 히스토리 탭에서 결과 확인');
    unawaited(_processIngest(pending));
  }

  Future<void> _processIngest(PendingCapture p) async {
    try {
      final r = await api.ingest(
        comment: p.comment,
        imageFile: p.photo,
        audioFile: p.audioPath != null ? File(p.audioPath!) : null,
        videoFile: p.videoPath != null ? File(p.videoPath!) : null,
        model: modelProvider(),
      );
      final recWithComment = Record(
        id: r.id,
        ts: r.ts,
        userComment: p.comment ?? '',
        imagePaths: r.imagePaths,
        vlmCaption: r.vlmCaption,
        insight: r.insight,
        suggestion: r.suggestion,
        analysis: r.analysis,
      );
      store.resolvePending(p.id, recWithComment);
    } catch (e) {
      store.removePending(p.id);
      onToast('전송 실패: $e');
    }
  }
}

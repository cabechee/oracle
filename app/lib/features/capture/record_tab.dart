import 'package:camera/camera.dart';
import 'package:flutter/material.dart';

import 'capture_controller.dart';

/// 기록 탭 — 카메라 프리뷰 + 사진/영상/음성 버튼 + 코멘트 + 전송.
/// 모든 상태는 [CaptureController]에서, ListenableBuilder로 구독.
class RecordTab extends StatelessWidget {
  final CaptureController c;
  const RecordTab({super.key, required this.c});

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: c,
      builder: (context, _) => Column(
        children: [
          Expanded(
            child: ClipRect(
              child: Container(
                color: Colors.black,
                width: double.infinity,
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    _cameraOrPhoto(context),
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
                          onPressed: () => _pickFromGalleryMenu(context),
                        ),
                      ),
                    ),
                    if (c.photo != null || c.video != null)
                      Positioned(
                        top: 8,
                        left: 8,
                        child: Material(
                          color: Colors.black54,
                          shape: const CircleBorder(),
                          child: IconButton(
                            icon: const Icon(Icons.close, color: Colors.white),
                            tooltip: '첨부 제거',
                            onPressed: c.clearAttachments,
                          ),
                        ),
                      ),
                    if (c.listening)
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
                    if (c.recordingVideo)
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
                  context,
                  icon: Icons.photo_camera_outlined,
                  label: '사진',
                  // 항상 활성 — 콜드 스타트 직후 눌러도 capture()가 준비를 기다렸다 촬영.
                  onTap: c.capture,
                ),
                _captureButton(
                  context,
                  icon: c.recordingVideo ? Icons.stop : Icons.videocam_outlined,
                  label: '영상',
                  active: c.recordingVideo,
                  onTap: c.cameraReady ? c.toggleVideoRecord : null,
                ),
                _captureButton(
                  context,
                  icon: c.listening ? Icons.stop : Icons.mic_none_outlined,
                  label: '음성',
                  active: c.listening,
                  onTap: c.recordAvailable ? c.toggleAudioRecord : null,
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: TextField(
              controller: c.commentCtrl,
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
                onPressed: c.submit,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _captureButton(
    BuildContext context, {
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

  Future<void> _pickFromGalleryMenu(BuildContext context) async {
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
    if (choice == 'photo') await c.pickFromGallery();
    if (choice == 'video') await c.pickVideoFromGallery();
  }

  Widget _cameraOrPhoto(BuildContext context) {
    if (c.photo != null) {
      return Image.file(c.photo!, fit: BoxFit.cover);
    }
    if (c.video != null) {
      return GestureDetector(
        onTap: c.clearVideo,
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
    if (c.cameraReady && c.camera != null) {
      return FittedBox(
        fit: BoxFit.cover,
        child: SizedBox(
          width: c.camera!.value.previewSize?.height ?? 1,
          height: c.camera!.value.previewSize?.width ?? 1,
          child: CameraPreview(c.camera!),
        ),
      );
    }
    if (c.cameraError != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Text(
            c.cameraError!,
            textAlign: TextAlign.center,
            style: const TextStyle(color: Colors.white),
          ),
        ),
      );
    }
    return const Center(child: CircularProgressIndicator(color: Colors.white));
  }
}

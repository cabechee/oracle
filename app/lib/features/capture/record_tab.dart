import 'dart:io';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import '../../core/phosphor_thin.dart';

import '../../core/design.dart';
import 'capture_controller.dart';

/// 기록 탭 — 뷰파인더(필름) + 종이 위의 컨트롤.
/// 아이콘은 Phosphor Thin, 상태는 [CaptureController] 구독.
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
                color: const Color(0xFF14120F),
                width: double.infinity,
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    _cameraOrPhoto(context),
                    Positioned(
                      top: 12,
                      right: 12,
                      child: _overlayButton(
                        icon: PhosphorThin.images,
                        tooltip: '갤러리',
                        onTap: () => _pickFromGalleryMenu(context),
                      ),
                    ),
                    if (c.photos.isNotEmpty || c.video != null)
                      Positioned(
                        top: 12,
                        left: 12,
                        child: _overlayButton(
                          icon: PhosphorThin.x,
                          tooltip: '첨부 모두 제거',
                          onTap: c.clearAttachments,
                        ),
                      ),
                    if (c.photos.isNotEmpty)
                      Positioned(
                        left: 0,
                        right: 0,
                        bottom: 12,
                        child: _photoTray(),
                      ),
                    if (c.listening)
                      Container(
                        color: Colors.black54,
                        child: Center(
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              const Icon(PhosphorThin.microphone,
                                  color: OracleColors.paper, size: 52),
                              const SizedBox(height: 14),
                              Text('녹음 중 — 음성을 다시 누르면 정지',
                                  style: OracleType.label
                                      .copyWith(color: OracleColors.paper)),
                            ],
                          ),
                        ),
                      ),
                    if (c.recordingVideo)
                      Positioned(
                        top: 16,
                        left: 0,
                        right: 0,
                        child: Center(
                          child: Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 12, vertical: 5),
                            decoration: BoxDecoration(
                              color: Colors.black54,
                              borderRadius: BorderRadius.circular(99),
                            ),
                            child: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Container(
                                  width: 6,
                                  height: 6,
                                  decoration: const BoxDecoration(
                                    color: OracleColors.vermilion,
                                    shape: BoxShape.circle,
                                  ),
                                ),
                                const SizedBox(width: 7),
                                Text('녹화 중',
                                    style: OracleType.label
                                        .copyWith(color: OracleColors.paper)),
                              ],
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(
                OracleSpace.screenH, 18, OracleSpace.screenH, 0),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceEvenly,
              children: [
                _RingButton(
                  icon: PhosphorThin.camera,
                  label: c.photos.isEmpty ? '사진' : '사진 ${c.photos.length}',
                  onTap: () => c.capture(),
                ),
                _RingButton(
                  icon: c.recordingVideo
                      ? PhosphorThin.stop
                      : PhosphorThin.videoCamera,
                  label: '영상',
                  active: c.recordingVideo,
                  onTap: c.cameraReady ? c.toggleVideoRecord : null,
                ),
                _RingButton(
                  icon: c.listening
                      ? PhosphorThin.stop
                      : PhosphorThin.microphone,
                  label: '음성',
                  active: c.listening,
                  onTap: c.recordAvailable ? c.toggleAudioRecord : null,
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(
                OracleSpace.screenH, 10, OracleSpace.screenH, 0),
            child: TextField(
              controller: c.commentCtrl,
              style: OracleType.userBody,
              decoration: InputDecoration(
                hintText: '코멘트 (선택)',
                hintStyle:
                    OracleType.userBody.copyWith(color: OracleColors.faint),
                enabledBorder: const UnderlineInputBorder(
                    borderSide:
                        BorderSide(color: OracleColors.hairline, width: 0.5)),
                focusedBorder: const UnderlineInputBorder(
                    borderSide:
                        BorderSide(color: OracleColors.ink, width: 0.5)),
                isDense: true,
                contentPadding: const EdgeInsets.symmetric(vertical: 10),
              ),
              minLines: 1,
              maxLines: 3,
              textInputAction: TextInputAction.newline,
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(
                OracleSpace.screenH, 16, OracleSpace.screenH, 16),
            child: InkWell(
              onTap: c.submit,
              child: Container(
                width: double.infinity,
                height: 46,
                decoration: BoxDecoration(
                  color: OracleColors.ink,
                  borderRadius: BorderRadius.circular(2),
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text('전송',
                        style: TextStyle(
                          fontFamily: OracleType.sans,
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          letterSpacing: 0.3,
                          color: OracleColors.paper,
                        )),
                    const SizedBox(width: 8),
                    Text('→',
                        style: OracleType.dateHeader.copyWith(
                            fontSize: 15, color: OracleColors.paper)),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _overlayButton({
    required IconData icon,
    required String tooltip,
    required VoidCallback onTap,
  }) {
    return Material(
      color: Colors.black38,
      shape: const CircleBorder(),
      child: InkWell(
        customBorder: const CircleBorder(),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(9),
          child: Icon(icon, color: OracleColors.paper, size: 21),
        ),
      ),
    );
  }

  Future<void> _pickFromGalleryMenu(BuildContext context) async {
    final choice = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: OracleColors.paper,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(PhosphorThin.image,
                  size: 22, color: OracleColors.ink),
              title: Text('사진', style: OracleType.userBody),
              onTap: () => Navigator.pop(context, 'photo'),
            ),
            ListTile(
              leading: const Icon(PhosphorThin.filmStrip,
                  size: 22, color: OracleColors.ink),
              title: Text('영상', style: OracleType.userBody),
              onTap: () => Navigator.pop(context, 'video'),
            ),
          ],
        ),
      ),
    );
    if (choice == 'photo') await c.pickFromGallery();
    if (choice == 'video') await c.pickVideoFromGallery();
  }

  /// 찍은 사진들 — 프리뷰 하단 가로 썸네일 트레이. 카메라는 라이브 유지(연속 촬영).
  Widget _photoTray() {
    return SizedBox(
      height: 60,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        itemCount: c.photos.length,
        separatorBuilder: (_, _) => const SizedBox(width: 8),
        itemBuilder: (_, i) => _thumb(c.photos[i], i),
      ),
    );
  }

  Widget _thumb(File f, int i) {
    return Stack(
      clipBehavior: Clip.none,
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(3),
          child: Image.file(f,
              width: 52, height: 60, fit: BoxFit.cover),
        ),
        Positioned(
          top: -5,
          right: -5,
          child: GestureDetector(
            onTap: () => c.removePhotoAt(i),
            child: Container(
              decoration: const BoxDecoration(
                color: Colors.black87, shape: BoxShape.circle),
              padding: const EdgeInsets.all(3),
              child: const Icon(PhosphorThin.x,
                  color: OracleColors.paper, size: 13),
            ),
          ),
        ),
      ],
    );
  }

  Widget _cameraOrPhoto(BuildContext context) {
    if (c.video != null) {
      return GestureDetector(
        onTap: c.clearVideo,
        child: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(PhosphorThin.filmStrip,
                  color: OracleColors.paper, size: 44),
              const SizedBox(height: 10),
              Text('영상 첨부됨 — 탭해서 제거',
                  style: OracleType.label
                      .copyWith(color: OracleColors.paper)),
            ],
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
          padding: const EdgeInsets.all(OracleSpace.screenH),
          child: Text(
            c.cameraError!,
            textAlign: TextAlign.center,
            style: OracleType.marginalia
                .copyWith(color: OracleColors.paper),
          ),
        ),
      );
    }
    return const Center(
      child: SizedBox(
        width: 18,
        height: 18,
        child: CircularProgressIndicator(
            strokeWidth: 1, color: OracleColors.faint),
      ),
    );
  }
}

/// 가는 링 버튼 — 헤어라인 원 + Phosphor Thin 아이콘. 활성 = 주홍.
class _RingButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final bool active;
  final VoidCallback? onTap;
  const _RingButton({
    required this.icon,
    required this.label,
    required this.onTap,
    this.active = false,
  });

  @override
  Widget build(BuildContext context) {
    final enabled = onTap != null;
    final color = active
        ? OracleColors.vermilion
        : enabled
            ? OracleColors.ink
            : OracleColors.faint;
    // 탭 영역 = 원·라벨을 감싸는 사각형 전체(주변 여백 포함) — 아이콘만 한 영역이 아니라
    // 버튼 주변까지 넉넉히 눌리게.
    return InkWell(
      borderRadius: BorderRadius.circular(14),
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 58,
              height: 58,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                border: Border.all(
                  color: active ? OracleColors.vermilion : OracleColors.hairline,
                  width: active ? 1 : 0.5,
                ),
              ),
              child: Icon(icon, size: 25, color: color),
            ),
            const SizedBox(height: 6),
            Text(label,
                style: OracleType.label.copyWith(
                    color: active ? OracleColors.vermilion : OracleColors.gray)),
          ],
        ),
      ),
    );
  }
}

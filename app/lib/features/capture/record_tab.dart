import 'dart:io';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';

import '../../core/design.dart';
import '../../core/phosphor_thin.dart';
import 'capture_controller.dart';

/// 기록 탭 — 전체화면 뷰파인더(필름) 위에 컨트롤을 띄운다.
/// 하단 그라데이션 위 흰 컨트롤(가독성). 아이콘은 Phosphor Thin, 상태는 [CaptureController] 구독.
/// companion 알림에 답하는 중이면 상단에 질문 배너(askPrompt).
class RecordTab extends StatelessWidget {
  final CaptureController c;
  const RecordTab({super.key, required this.c});

  @override
  Widget build(BuildContext context) {
    final keyboard = MediaQuery.of(context).viewInsets.bottom;
    return ListenableBuilder(
      listenable: c,
      builder: (context, _) => Container(
        color: const Color(0xFF14120F),
        child: Stack(
          fit: StackFit.expand,
          children: [
            // 1) 전체화면 프리뷰
            _cameraOrPhoto(context),

            // 2) 상단 — 첨부 제거(좌)·갤러리(우)
            SafeArea(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Row(
                  children: [
                    if (c.photos.isNotEmpty || c.video != null)
                      _overlayButton(
                          icon: PhosphorThin.x,
                          tooltip: '첨부 모두 제거',
                          onTap: c.clearAttachments),
                    const Spacer(),
                    _overlayButton(
                        icon: PhosphorThin.images,
                        tooltip: '갤러리',
                        onTap: () => _pickFromGalleryMenu(context)),
                  ],
                ),
              ),
            ),

            // 3) companion 질문 배너 (알림에 답하는 중)
            if (c.askPrompt != null)
              SafeArea(
                child: Padding(
                  padding: const EdgeInsets.only(top: 60, left: 16, right: 16),
                  child: Align(
                      alignment: Alignment.topCenter,
                      child: _askBanner(c.askPrompt!)),
                ),
              ),

            // 4) 녹음 오버레이
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

            // 5) 녹화 표시
            if (c.recordingVideo)
              Positioned(
                top: MediaQuery.of(context).padding.top + 56,
                left: 0,
                right: 0,
                child: Center(child: _recordingBadge()),
              ),

            // 6) 하단 컨트롤 — 그라데이션 위 버튼/코멘트/전송 (키보드 따라 올라감)
            Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              child: AnimatedPadding(
                duration: const Duration(milliseconds: 150),
                padding: EdgeInsets.only(bottom: keyboard),
                child: _bottomControls(),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ── 하단 컨트롤 ────────────────────────────────────────────
  Widget _bottomControls() {
    return Container(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Colors.transparent, Color(0xD0000000)],
        ),
      ),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (c.photos.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 8, bottom: 2),
                child: _photoTray(),
              ),
            Padding(
              padding: const EdgeInsets.only(top: 10),
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
                  OracleSpace.screenH, 8, OracleSpace.screenH, 12),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Expanded(child: _commentField()),
                  const SizedBox(width: 10),
                  _sendButton(),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _commentField() {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.16),
        borderRadius: BorderRadius.circular(22),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: TextField(
        controller: c.commentCtrl,
        style: OracleType.userBody.copyWith(color: OracleColors.paper),
        cursorColor: OracleColors.paper,
        decoration: InputDecoration(
          hintText: c.askPrompt != null ? '여기에 답해보세요' : '코멘트 (선택)',
          hintStyle: OracleType.userBody.copyWith(color: Colors.white60),
          border: InputBorder.none,
          isDense: true,
          contentPadding: const EdgeInsets.symmetric(vertical: 11),
        ),
        minLines: 1,
        maxLines: 3,
        textInputAction: TextInputAction.newline,
      ),
    );
  }

  Widget _sendButton() {
    return InkWell(
      onTap: c.submit,
      borderRadius: BorderRadius.circular(23),
      child: Container(
        width: 46,
        height: 46,
        decoration: const BoxDecoration(
          color: OracleColors.vermilion,
          shape: BoxShape.circle,
        ),
        child: Center(
          child: Text('→',
              style: OracleType.dateHeader
                  .copyWith(fontSize: 19, color: OracleColors.paper)),
        ),
      ),
    );
  }

  // companion 질문 배너 — 어두운 반투명 카드 + 닫기.
  Widget _askBanner(String prompt) {
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 10, 8, 10),
      decoration: BoxDecoration(
        color: const Color(0xE6201E19),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: OracleColors.vermilion.withValues(alpha: 0.5)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Padding(
            padding: EdgeInsets.only(top: 1),
            child: Text('🐾', style: TextStyle(fontSize: 15)),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(prompt,
                    style: OracleType.userBody.copyWith(
                        color: OracleColors.paper, fontSize: 14.5)),
                const SizedBox(height: 2),
                Text('기록으로 답해보세요',
                    style: OracleType.label.copyWith(color: Colors.white54)),
              ],
            ),
          ),
          InkWell(
            onTap: c.clearAsk,
            customBorder: const CircleBorder(),
            child: const Padding(
              padding: EdgeInsets.all(4),
              child: Icon(PhosphorThin.x, color: Colors.white70, size: 16),
            ),
          ),
        ],
      ),
    );
  }

  Widget _recordingBadge() => Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
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
                  color: OracleColors.vermilion, shape: BoxShape.circle),
            ),
            const SizedBox(width: 7),
            Text('녹화 중',
                style: OracleType.label.copyWith(color: OracleColors.paper)),
          ],
        ),
      );

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

  /// 찍은 사진들 — 컨트롤 위 가로 썸네일 트레이. 카메라는 라이브 유지(연속 촬영).
  Widget _photoTray() {
    return SizedBox(
      height: 58,
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
          child: Image.file(f, width: 50, height: 58, fit: BoxFit.cover),
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
                  style: OracleType.label.copyWith(color: OracleColors.paper)),
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
          child: Text(c.cameraError!,
              textAlign: TextAlign.center,
              style: OracleType.marginalia.copyWith(color: OracleColors.paper)),
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

/// 가는 링 버튼 — 헤어라인 원 + Phosphor Thin 아이콘. 어두운 프리뷰 위라 흰색(onDark).
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
            ? OracleColors.paper
            : Colors.white38;
    return InkWell(
      borderRadius: BorderRadius.circular(14),
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 56,
              height: 56,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: Colors.black.withValues(alpha: 0.18),
                border: Border.all(
                  color: active ? OracleColors.vermilion : Colors.white60,
                  width: active ? 1.2 : 0.8,
                ),
              ),
              child: Icon(icon, size: 24, color: color),
            ),
            const SizedBox(height: 6),
            Text(label,
                style: OracleType.label.copyWith(
                    color:
                        active ? OracleColors.vermilion : Colors.white70)),
          ],
        ),
      ),
    );
  }
}

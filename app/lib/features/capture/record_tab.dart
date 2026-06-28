import 'dart:io';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';

import '../../core/design.dart';
import '../../core/phosphor_thin.dart';
import '../chat/record_bubble.dart' show bertAvatar, cookieAvatar;
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

            // 2) (제거됨) 상단 '첨부 모두 제거' X — 사진은 썸네일별 X, 영상은 풀스크린 '탭해서
            //    제거'로 각각 처리한다. 전역 X와 개별 삭제가 둘 다 떠서 헷갈리던 문제 해소.

            // 3) companion 질문 오버레이 (알림에 답하는 중) — 캐릭터 얼굴+이름과 함께
            if (c.askPrompt != null)
              SafeArea(
                child: Padding(
                  padding: const EdgeInsets.only(top: 60, left: 16, right: 16),
                  child: Align(
                      alignment: Alignment.topCenter,
                      child: _askBanner(c.askPrompt!, c.askSpeaker)),
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
                child: _bottomControls(context),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ── 하단 컨트롤 ────────────────────────────────────────────
  Widget _bottomControls(BuildContext context) {
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
            if (c.mode == CaptureMode.photo && c.photos.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 8, bottom: 2),
                child: _photoTray(),
              ),
            const SizedBox(height: 8),
            _modeTabs(),
            Padding(
              padding: const EdgeInsets.only(top: 6, bottom: 2),
              child: _shutterRow(context),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  OracleSpace.screenH, 4, OracleSpace.screenH, 12),
              child: Column(
                children: [
                  _commentField(),
                  const SizedBox(height: 10),
                  _bigSendButton(),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  // 모드 탭 — 사진 / 영상 / 음성. 현재 모드는 주홍 밑줄 + 밝게.
  Widget _modeTabs() {
    Widget tab(CaptureMode m, String label) {
      final on = c.mode == m;
      return InkWell(
        onTap: () => c.setMode(m),
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
          child: Container(
            padding: const EdgeInsets.only(bottom: 4),
            decoration: BoxDecoration(
              border: Border(
                bottom: BorderSide(
                  color: on ? OracleColors.vermilion : Colors.transparent,
                  width: 2,
                ),
              ),
            ),
            child: Text(label,
                style: OracleType.label.copyWith(
                  color: on ? OracleColors.paper : Colors.white54,
                  fontWeight: on ? FontWeight.w500 : FontWeight.w400,
                )),
          ),
        ),
      );
    }

    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        tab(CaptureMode.photo, '사진'),
        const SizedBox(width: 8),
        tab(CaptureMode.video, '영상'),
        const SizedBox(width: 8),
        tab(CaptureMode.audio, '음성'),
      ],
    );
  }

  // 큰 셔터 + 사이드 갤러리. 셔터 동작은 현재 모드에 따라(촬영/녹화토글/녹음토글).
  // Row로 나란히 — 양쪽 Expanded로 셔터를 중앙에 두고 갤러리는 오른쪽. 좁은 화면(폴드
  // dual-pane·커버화면)에서도 셔터가 갤러리를 덮지 않게(예전 Stack+Positioned는 겹쳐 탭 가림).
  Widget _shutterRow(BuildContext context) {
    return SizedBox(
      height: 78,
      child: Row(
        children: [
          const Expanded(child: SizedBox()),
          _shutter(),
          Expanded(
            child: Align(
              alignment: Alignment.centerRight,
              child: Padding(
                padding: const EdgeInsets.only(right: 22),
                child: _overlayButton(
                  icon: PhosphorThin.images,
                  tooltip: '갤러리',
                  onTap: () => _pickFromGalleryMenu(context),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _shutter() {
    IconData icon;
    VoidCallback? onTap;
    var active = false;
    switch (c.mode) {
      case CaptureMode.photo:
        icon = PhosphorThin.camera;
        onTap = () => c.capture();
      case CaptureMode.video:
        active = c.recordingVideo;
        icon = c.recordingVideo ? PhosphorThin.stop : PhosphorThin.videoCamera;
        onTap = c.cameraReady ? c.toggleVideoRecord : null;
      case CaptureMode.audio:
        active = c.listening;
        icon = c.listening ? PhosphorThin.stop : PhosphorThin.microphone;
        onTap = c.recordAvailable ? c.toggleAudioRecord : null;
    }
    final enabled = onTap != null;
    final tint = active
        ? OracleColors.vermilion
        : enabled
            ? OracleColors.paper
            : Colors.white38;
    return InkWell(
      customBorder: const CircleBorder(),
      onTap: onTap,
      child: Container(
        width: 70,
        height: 70,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: active
              ? OracleColors.vermilion.withValues(alpha: 0.22)
              : Colors.white.withValues(alpha: 0.10),
          border: Border.all(color: tint, width: 3),
        ),
        child: Icon(icon, size: 28, color: tint),
      ),
    );
  }

  // 큰 전송 버튼 — 코멘트 아래 가로 전체. 항상 노출(모드 무관).
  Widget _bigSendButton() {
    return InkWell(
      onTap: c.submit,
      borderRadius: BorderRadius.circular(11),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(vertical: 13),
        decoration: BoxDecoration(
          color: OracleColors.vermilion,
          borderRadius: BorderRadius.circular(11),
        ),
        child: Center(
          child: Text('전송  →',
              style: OracleType.dateHeader
                  .copyWith(fontSize: 16, color: OracleColors.paper)),
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

  // companion 질문 오버레이 — 어두운 반투명 카드 위에 캐릭터 얼굴+이름과 멘트.
  // "베르 — 아빠 뭐해요?"처럼 누가 말 걸었는지 분명히 보이게(기록으로 답하는 맥락).
  Widget _askBanner(String prompt, String? speaker) {
    final name = (speaker != null && speaker.isNotEmpty) ? speaker : '동반자';
    final isCookie = speaker == '쿠키';
    final hasFace = speaker == '베르' || isCookie;
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 11, 8, 12),
      decoration: BoxDecoration(
        color: const Color(0xE6201E19),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: OracleColors.vermilion.withValues(alpha: 0.55)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 1),
            child: hasFace
                ? (isCookie ? cookieAvatar(30, seed: prompt) : bertAvatar(30))
                : const Text('🐾', style: TextStyle(fontSize: 18)),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(name,
                    style: OracleType.label.copyWith(
                        color: OracleColors.vermilion,
                        fontSize: 12,
                        letterSpacing: 0.3)),
                const SizedBox(height: 3),
                Text(prompt,
                    style: OracleType.userBody.copyWith(
                        color: OracleColors.paper, fontSize: 15, height: 1.35)),
                const SizedBox(height: 4),
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

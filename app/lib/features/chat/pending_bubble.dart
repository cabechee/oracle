import 'dart:io';

import 'package:flutter/material.dart';

import '../../core/design.dart';
import 'record_bubble.dart' show mediaChip;

/// 처리 중인 캡처 — "현상 중" (탭하면 큐에서 제거).
class PendingBubble extends StatelessWidget {
  final String? comment;
  final List<File> photos;
  final bool hasAudio;
  final bool hasVideo;
  const PendingBubble({
    super.key,
    this.comment,
    this.photos = const [],
    this.hasAudio = false,
    this.hasVideo = false,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (photos.isNotEmpty)
          Container(
            color: OracleColors.mat,
            padding: const EdgeInsets.all(4),
            foregroundDecoration: BoxDecoration(
              border: Border.all(color: OracleColors.matBorder, width: 0.5),
            ),
            child: Stack(
              children: [
                Image.file(photos.first,
                    width: 232, height: 154, fit: BoxFit.cover),
                if (photos.length > 1)
                  Positioned(
                    right: 6,
                    bottom: 6,
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 7, vertical: 3),
                      color: Colors.black54,
                      child: Text('${photos.length}장',
                          style: OracleType.label
                              .copyWith(color: OracleColors.paper)),
                    ),
                  ),
              ],
            ),
          ),
        if (hasAudio || hasVideo)
          Padding(
            padding:
                EdgeInsets.only(top: photos.isNotEmpty ? OracleSpace.inPhoto : 0),
            child: Row(
              children: [
                if (hasAudio)
                  Padding(
                      padding: const EdgeInsets.only(right: 12),
                      child: mediaChip(context, '음성 메모')),
                if (hasVideo) mediaChip(context, '영상'),
              ],
            ),
          ),
        if (comment != null && comment!.isNotEmpty)
          Padding(
            padding: EdgeInsets.only(
                top: (photos.isNotEmpty || hasAudio || hasVideo)
                    ? OracleSpace.inBlock
                    : 0),
            child: Text(comment!, style: OracleType.userBody),
          ),
        Padding(
          padding: const EdgeInsets.only(top: OracleSpace.inBlock),
          child: Row(
            children: [
              const SizedBox(
                width: 10,
                height: 10,
                child: CircularProgressIndicator(
                    strokeWidth: 1, color: OracleColors.faint),
              ),
              const SizedBox(width: 8),
              Text('현상 중 — 탭해서 취소',
                  style: OracleType.marginalia
                      .copyWith(color: OracleColors.faint)),
            ],
          ),
        ),
      ],
    );
  }
}

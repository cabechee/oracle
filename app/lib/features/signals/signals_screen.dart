import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../api.dart';
import '../../core/design.dart';

/// 신호 로그 — "대신 읽어드림"의 전체 이력.
///
/// 두 단: 과거 요약(brief) 타임라인 + 원본 신호(문자·부재중) 목록.
/// 홈 표지의 '대신 읽어드림' 모듈에서 진입. 발행물 문법(스파인 시각).
class SignalsScreen extends StatefulWidget {
  final OracleApi api;
  final bool embedded; // 탭에 임베드 시 Scaffold/AppBar 생략
  const SignalsScreen({super.key, required this.api, this.embedded = false});

  @override
  State<SignalsScreen> createState() => _SignalsScreenState();
}

class _SignalsScreenState extends State<SignalsScreen> {
  Map<String, dynamic>? _data;
  String? _error;
  bool _showRaw = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final d = await widget.api.fetchSignalsRecent();
      if (mounted) setState(() => _data = d);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final briefs =
        (_data?['briefs'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
    final raw =
        (_data?['signals'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
    final content = RefreshIndicator(
      color: OracleColors.vermilion,
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(
          OracleSpace.screenH,
          20,
          OracleSpace.screenH,
          48,
        ),
        children: [
          if (_error != null)
            Text('읽기 실패 — 당겨서 새로고침', style: OracleType.label)
          else if (_data == null)
            const Padding(
              padding: EdgeInsets.only(top: 80),
              child: Center(
                child: SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 1,
                    color: OracleColors.faint,
                  ),
                ),
              ),
            )
          else ...[
            if (briefs.isEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 40),
                child: Text(
                  '아직 요약이 없어요 — 문자·부재중이 들어오면 30분마다 모아 읽어드려요',
                  style: OracleType.marginalia,
                ),
              ),
            for (final b in briefs) _briefBlock(b),
            if (raw.isNotEmpty) ...[
              const SizedBox(height: OracleSpace.section),
              InkWell(
                onTap: () => setState(() => _showRaw = !_showRaw),
                child: Row(
                  children: [
                    Container(
                      width: 14,
                      height: 1,
                      color: OracleColors.vermilion,
                    ),
                    const SizedBox(width: 8),
                    Text('받은 신호 원본 ${raw.length}건', style: OracleType.label),
                    const SizedBox(width: 6),
                    Icon(
                      _showRaw ? Icons.expand_less : Icons.expand_more,
                      size: 16,
                      color: OracleColors.faint,
                    ),
                  ],
                ),
              ),
              if (_showRaw)
                Padding(
                  padding: const EdgeInsets.only(top: OracleSpace.inBlock),
                  child: Column(children: [for (final s in raw) _rawRow(s)]),
                ),
            ],
          ],
        ],
      ),
    );
    if (widget.embedded) return content;
    return Scaffold(
      appBar: AppBar(title: const Text('대신 읽어드림')),
      body: content,
    );
  }

  // 카테고리 라벨·색 — 백엔드 SIGNAL_CATEGORIES와 일치
  static const _catLabel = {
    'action_needed': '당장 액션',
    'attention': '관심',
    'acquaintance': '지인',
    'low': '일반',
    'spam': '스팸',
  };
  Color _catColor(String c) => c == 'action_needed'
      ? OracleColors.vermilion
      : (c == 'low' || c == 'spam' ? OracleColors.gray : OracleColors.ink);

  // 요약 블록 — 시각 헤더 + 분류 항목들(불렛). items 없으면 구 summary 폴백.
  Widget _briefBlock(Map<String, dynamic> b) {
    final ts = DateTime.tryParse(b['ts'] as String? ?? '');
    final parts = <String>[
      if ((b['sms_count'] as num? ?? 0) > 0) '문자 ${b['sms_count']}',
      if ((b['call_count'] as num? ?? 0) > 0) '부재중 ${b['call_count']}',
      if ((b['notif_count'] as num? ?? 0) > 0) '알림 ${b['notif_count']}',
    ];
    final items =
        (b['items'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
    final briefId = b['id'] as String;
    return Padding(
      padding: const EdgeInsets.only(bottom: OracleSpace.entry),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            (ts != null ? DateFormat('M월 d일 HH:mm').format(ts.toLocal()) : '') +
                (parts.isNotEmpty ? '  ·  ${parts.join(' · ')}' : ''),
            style: OracleType.timestamp,
          ),
          const SizedBox(height: 10),
          if (items.isEmpty)
            Text(
              b['summary'] as String? ?? '',
              style: OracleType.journal.copyWith(
                fontSize: 14.5,
                height: 24 / 14.5,
              ),
            )
          else
            for (var i = 0; i < items.length; i++) _item(briefId, i, items[i]),
        ],
      ),
    );
  }

  // 분류 항목 한 줄 — [카테고리] 발신인 · 요약 + 부정확 피드백
  Widget _item(String briefId, int idx, Map<String, dynamic> it) {
    final cat = it['category'] as String? ?? 'low';
    final flagged = it['feedback'] == 'inaccurate';
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 카테고리 칩
          Container(
            margin: const EdgeInsets.only(top: 1, right: 8),
            padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 1),
            decoration: BoxDecoration(
              border: Border.all(color: _catColor(cat).withValues(alpha: 0.4)),
              borderRadius: BorderRadius.circular(99),
            ),
            child: Text(
              _catLabel[cat] ?? cat,
              style: OracleType.label.copyWith(
                color: _catColor(cat),
                fontSize: 10.5,
              ),
            ),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  it['sender'] as String? ?? '',
                  style: OracleType.timestamp.copyWith(
                    color: OracleColors.gray,
                  ),
                ),
                Text(
                  it['summary'] as String? ?? '',
                  style: OracleType.journal.copyWith(
                    fontSize: 14,
                    height: 22 / 14,
                    decoration: flagged ? TextDecoration.lineThrough : null,
                    color: flagged ? OracleColors.faint : OracleColors.inkSoft,
                  ),
                ),
              ],
            ),
          ),
          // 부정확 피드백 토글
          InkWell(
            onTap: () => _toggleFeedback(briefId, idx, it),
            child: Padding(
              padding: const EdgeInsets.only(left: 6, top: 2),
              child: Text(
                flagged ? '✓ 부정확' : '부정확',
                style: OracleType.label.copyWith(
                  color: flagged ? OracleColors.vermilion : OracleColors.faint,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _toggleFeedback(
    String briefId,
    int idx,
    Map<String, dynamic> it,
  ) async {
    final next = it['feedback'] == 'inaccurate' ? null : 'inaccurate';
    setState(() => it['feedback'] = next); // 낙관적
    try {
      await widget.api.setBriefFeedback(briefId, idx, next);
    } catch (_) {
      setState(() => it['feedback'] = next == null ? 'inaccurate' : null);
    }
  }

  // 원본 신호 한 줄 — 종류(문자·부재중·알림)·발신인·시각·본문
  Widget _rawRow(Map<String, dynamic> s) {
    final ts = DateTime.tryParse(s['ts'] as String? ?? '');
    final kind = s['kind'] as String? ?? '';
    final kindLabel = kind == 'sms'
        ? '문자'
        : kind == 'notification'
        ? '알림'
        : '부재중';
    final otp = s['otp'] == true;
    final excluded = s['excluded'] == true; // 어드민 제외 규칙에 걸림
    final body = s['body'] as String? ?? '';
    return Opacity(
      opacity: excluded ? 0.5 : 1.0,
      child: Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(
                  kindLabel,
                  style: OracleType.label.copyWith(color: OracleColors.gray),
                ),
                if (excluded) ...[
                  const SizedBox(width: 6),
                  Text(
                    '제외됨',
                    style: OracleType.label.copyWith(
                      color: OracleColors.vermilion,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    s['sender'] as String? ?? '(알 수 없음)',
                    style: OracleType.timestamp,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                if (ts != null)
                  Text(
                    DateFormat('M/d HH:mm').format(ts.toLocal()),
                    style: OracleType.label,
                  ),
              ],
            ),
            // 본문 — 문자·알림 둘 다(부재중은 본문 없음). OTP는 흐리게.
            if (body.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 2, left: 0),
                child: Text(
                  body,
                  style: OracleType.marginalia.copyWith(
                    color: otp ? OracleColors.faint : OracleColors.marginalia,
                  ),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
          ],
        ),
      ),
    );
  }
}

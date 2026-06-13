import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../api.dart';
import '../../core/design.dart';
import '../signals/signals_screen.dart';

/// 홈 탭 — 오늘의 표지(front page).
///
/// 에디토리얼 문법: 마스트헤드(날짜) → 오늘의 한 줄(어제 일기 발췌) →
/// 오늘 지금까지(기록 수·인화지 썸네일) → 대신 읽어드림(신호 brief) →
/// 그날의 오늘(1주/1달 전). 전부 조회 전용 — 표지는 즉시 떠야 한다.
class HomeTab extends StatefulWidget {
  final OracleApi api;
  final VoidCallback onGoHistory;
  const HomeTab({super.key, required this.api, required this.onGoHistory});

  @override
  State<HomeTab> createState() => _HomeTabState();
}

class _HomeTabState extends State<HomeTab>
    with AutomaticKeepAliveClientMixin {
  Map<String, dynamic>? _cover;
  String? _error;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final c = await widget.api.fetchHomeCover();
      if (mounted) setState(() => _cover = c);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final now = DateTime.now();
    return RefreshIndicator(
      color: OracleColors.vermilion,
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(
            OracleSpace.screenH, 28, OracleSpace.screenH, 48),
        children: [
          _masthead(now),
          ..._healthLine(),
          const SizedBox(height: OracleSpace.section),
          ..._briefing(),
          ..._yesterdayLine(),
          ..._todaySoFar(),
          ..._latestBrief(),
          ..._onThisDay(),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: OracleSpace.section),
              child: Text('표지 읽기 실패 — 당겨서 새로고침',
                  style: OracleType.label),
            ),
        ],
      ),
    );
  }

  // ── 마스트헤드 — 디스플레이 날짜 ─────────────────────────────
  Widget _masthead(DateTime now) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Text('${now.day}', style: OracleType.display),
        const SizedBox(width: 12),
        Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(DateFormat('M월', 'ko').format(now),
                  style: OracleType.dateHeader),
              Text(DateFormat('EEEE', 'ko').format(now),
                  style: OracleType.timestamp),
            ],
          ),
        ),
      ],
    );
  }

  // ── 건강 한 줄 — 마스트헤드 아래 (수면·걸음) ────────────────
  List<Widget> _healthLine() {
    final h = _cover?['health'] as Map<String, dynamic>?;
    if (h == null) return const [];
    final parts = <String>[];
    final sleep = (h['sleep_min'] as num?)?.toInt();
    final steps = (h['steps'] as num?)?.toInt();
    if (sleep != null && sleep > 0) {
      parts.add('잘 잤어요 ${sleep ~/ 60}시간 ${sleep % 60}분');
    }
    if (steps != null && steps > 0) {
      parts.add('오늘 ${_comma(steps)}걸음');
    }
    if (parts.isEmpty) return const [];
    return [
      const SizedBox(height: 10),
      Text(parts.join('  ·  '),
          style: OracleType.timestamp.copyWith(color: OracleColors.gray)),
    ];
  }

  String _comma(int n) =>
      n.toString().replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+$)'), (m) => '${m[1]},');

  // ── 발행물 — 오늘의 조간/석간 (베르 본문) ───────────────────
  List<Widget> _briefing() {
    final b = _cover?['briefing'] as Map<String, dynamic>?;
    if (b == null) return const [];
    final title = b['kind'] == 'morning' ? '오늘의 조간' : '오늘의 석간';
    return [
      Container(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: OracleColors.mat,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: OracleColors.matBorder, width: 0.5),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _sectionLabel(title),
            const SizedBox(height: 12),
            Text(b['text'] as String? ?? '', style: OracleType.journal),
          ],
        ),
      ),
      const SizedBox(height: OracleSpace.section),
    ];
  }

  // ── 오늘의 한 줄 — 어제 일기 발췌 ───────────────────────────
  List<Widget> _yesterdayLine() {
    final y = _cover?['yesterday_line'] as Map<String, dynamic>?;
    if (y == null) return const [];
    return [
      _sectionLabel('어제로부터'),
      const SizedBox(height: 8),
      Text('“${y['text']}”',
          style: OracleType.journal.copyWith(fontSize: 16, height: 28 / 16)),
      const SizedBox(height: OracleSpace.section),
    ];
  }

  // ── 오늘 지금까지 ──────────────────────────────────────────
  List<Widget> _todaySoFar() {
    final t = _cover?['today'] as Map<String, dynamic>?;
    final count = (t?['count'] as num?)?.toInt() ?? 0;
    final thumbs = (t?['thumbs'] as List?)?.cast<String>() ?? const <String>[];
    final lastTs = t?['last_ts'] as String?;
    return [
      _sectionLabel('오늘 지금까지'),
      const SizedBox(height: 8),
      InkWell(
        onTap: widget.onGoHistory,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              count == 0
                  ? '아직 기록이 없어요 — 첫 장면을 담아보세요'
                  : '기록 $count건'
                      '${lastTs != null ? ' · 마지막 ${DateFormat('HH:mm').format(DateTime.parse(lastTs).toLocal())}' : ''}',
              style: OracleType.userBody,
            ),
            if (thumbs.isNotEmpty) ...[
              const SizedBox(height: OracleSpace.inBlock),
              Row(
                children: [
                  for (final p in thumbs)
                    Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: _print(p, 64),
                    ),
                ],
              ),
            ],
          ],
        ),
      ),
      const SizedBox(height: OracleSpace.section),
    ];
  }

  // ── 대신 읽어드림 — 최신 신호 brief ─────────────────────────
  List<Widget> _latestBrief() {
    final b = _cover?['latest_brief'] as Map<String, dynamic>?;
    if (b == null) {
      // brief가 아직 없어도 진입점은 남긴다 — 원본 신호 로그는 볼 수 있게
      return [
        InkWell(
          onTap: () => Navigator.push(context,
              MaterialPageRoute(builder: (_) => SignalsScreen(api: widget.api))),
          child: Row(
            children: [
              Expanded(child: _sectionLabel('대신 읽어드림')),
              const Icon(Icons.chevron_right,
                  size: 18, color: OracleColors.faint),
            ],
          ),
        ),
        const SizedBox(height: 6),
        Text('문자·부재중이 들어오면 30분마다 모아 읽어드려요',
            style: OracleType.marginalia.copyWith(color: OracleColors.gray)),
        const SizedBox(height: OracleSpace.section),
      ];
    }
    final ts = DateTime.tryParse(b['ts'] as String? ?? '');
    final parts = <String>[
      if ((b['sms_count'] as num? ?? 0) > 0) '문자 ${b['sms_count']}',
      if ((b['call_count'] as num? ?? 0) > 0) '부재중 ${b['call_count']}',
    ];
    return [
      InkWell(
        onTap: () => Navigator.push(
            context,
            MaterialPageRoute(
                builder: (_) => SignalsScreen(api: widget.api))),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: _sectionLabel(
                      '대신 읽어드림${ts != null ? ' · ${DateFormat('HH:mm').format(ts.toLocal())}' : ''}'
                      '${parts.isNotEmpty ? ' · ${parts.join(' · ')}' : ''}'),
                ),
                const Icon(Icons.chevron_right,
                    size: 18, color: OracleColors.faint),
              ],
            ),
            const SizedBox(height: 8),
            Text(b['summary'] as String? ?? '',
                style: OracleType.marginalia,
                maxLines: 6,
                overflow: TextOverflow.ellipsis),
          ],
        ),
      ),
      const SizedBox(height: OracleSpace.section),
    ];
  }

  // ── 그날의 오늘 ────────────────────────────────────────────
  List<Widget> _onThisDay() {
    final items =
        (_cover?['on_this_day'] as List?)?.cast<Map<String, dynamic>>() ??
            const [];
    if (items.isEmpty) return const [];
    return [
      _sectionLabel('그날의 오늘'),
      const SizedBox(height: 8),
      for (final it in items)
        Padding(
          padding: const EdgeInsets.only(bottom: OracleSpace.inBlock),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (it['thumb'] != null) ...[
                _print(it['thumb'] as String, 56),
                const SizedBox(width: 12),
              ],
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(it['label'] as String? ?? '',
                        style: OracleType.label),
                    const SizedBox(height: 2),
                    Text(it['line'] as String? ?? '',
                        style: OracleType.marginalia,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis),
                  ],
                ),
              ),
            ],
          ),
        ),
    ];
  }

  // ── 공용 조각 ──────────────────────────────────────────────
  Widget _sectionLabel(String text) => Row(
        children: [
          Container(width: 14, height: 1, color: OracleColors.vermilion),
          const SizedBox(width: 8),
          Text(text, style: OracleType.label),
        ],
      );

  /// 인화지 썸네일 — 흰 마진 + 헤어라인 (record_bubble 사진 문법의 축소판)
  Widget _print(String rel, double size) => Container(
        color: OracleColors.mat,
        padding: const EdgeInsets.all(3),
        foregroundDecoration: BoxDecoration(
          border: Border.all(color: OracleColors.matBorder, width: 0.5),
        ),
        child: Image.network(
          widget.api.photoUrl(rel),
          headers: widget.api.photoHeaders,
          width: size,
          height: size,
          fit: BoxFit.cover,
          errorBuilder: (_, _, _) =>
              Container(width: size, height: size, color: OracleColors.photo),
        ),
      );
}

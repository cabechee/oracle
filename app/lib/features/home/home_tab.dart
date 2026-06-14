import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../api.dart';
import '../../applog.dart';
import '../../core/design.dart';
import '../chat/record_bubble.dart' show bertAvatar;

/// 홈 탭 — 표지(front page). 마스트헤드 날짜를 탭하면 지난 날 표지를 재현한다.
///
/// 에디토리얼 문법: 마스트헤드(날짜) → 건강 한 줄 → 발행물(조간/석간) →
/// 어제로부터(일기 발췌) → 오늘 지금까지(기록·썸네일) → 그날의 오늘(1주/1달 전).
/// '대신 읽어드림'(신호 brief)은 데스크 탭으로 이관 — 표지는 '읽을 거리'에 집중.
/// 전부 조회 전용 — 표지는 즉시 떠야 한다.
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
  DateTime _date = DateTime.now(); // 표지 기준일 — 마스트헤드 탭으로 변경

  @override
  bool get wantKeepAlive => true;

  bool get _isToday {
    final n = DateTime.now();
    return _date.year == n.year && _date.month == n.month && _date.day == n.day;
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  String _ymd(DateTime d) =>
      '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  Future<void> _load() async {
    try {
      final c = await widget.api
          .fetchHomeCover(date: _isToday ? null : _ymd(_date));
      if (mounted) {
        setState(() {
          _cover = c;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  Future<void> _pickDate() async {
    final now = DateTime.now();
    AppLog.ui('표지 날짜 선택 열기');
    final picked = await showDatePicker(
      context: context,
      initialDate: _date,
      firstDate: DateTime(2026, 1, 1),
      lastDate: now,
      helpText: '표지 날짜',
    );
    if (picked == null || !mounted) return;
    setState(() {
      _date = picked;
      _cover = null;
    });
    AppLog.ui('표지 → ${_ymd(picked)}');
    await _load();
  }

  void _goToday() {
    setState(() {
      _date = DateTime.now();
      _cover = null;
    });
    _load();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return RefreshIndicator(
      color: OracleColors.vermilion,
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(
            OracleSpace.screenH, 28, OracleSpace.screenH, 48),
        children: [
          _masthead(_date),
          ..._healthLine(),
          const SizedBox(height: OracleSpace.section),
          ..._briefings(),
          ..._yesterdayLine(),
          ..._todaySoFar(),
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

  // ── 마스트헤드 — 디스플레이 날짜 (탭하면 달력) ──────────────────
  Widget _masthead(DateTime d) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        InkWell(
          onTap: _pickDate,
          borderRadius: BorderRadius.circular(6),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text('${d.day}', style: OracleType.display),
              const SizedBox(width: 12),
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(DateFormat('M월', 'ko').format(d),
                        style: OracleType.dateHeader),
                    Text(DateFormat('EEEE', 'ko').format(d),
                        style: OracleType.timestamp),
                  ],
                ),
              ),
            ],
          ),
        ),
        const Spacer(),
        // 오늘이 아니면 '오늘로' 복귀, 오늘이면 달력 힌트 아이콘
        if (!_isToday)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: TextButton.icon(
              onPressed: _goToday,
              icon: const Icon(Icons.today_outlined, size: 15),
              label: const Text('오늘로'),
              style: TextButton.styleFrom(
                foregroundColor: OracleColors.vermilion,
                textStyle: OracleType.label,
                padding: const EdgeInsets.symmetric(horizontal: 8),
                minimumSize: const Size(0, 36),
              ),
            ),
          )
        else
          const Padding(
            padding: EdgeInsets.only(bottom: 12),
            child: Icon(Icons.calendar_today_outlined,
                size: 15, color: OracleColors.faint),
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

  // ── 발행물 — 조간/석간 전부 (베르 본문). 과거 표지는 둘 다 보인다 ──
  List<Widget> _briefings() {
    var list =
        (_cover?['briefings'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
    // 구 응답 폴백 — briefings 배열 없으면 단건 briefing
    if (list.isEmpty) {
      final single = _cover?['briefing'] as Map<String, dynamic>?;
      if (single != null) list = [single];
    }
    if (list.isEmpty) return const [];
    final out = <Widget>[];
    for (final b in list) {
      out.add(Container(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: OracleColors.mat,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: OracleColors.matBorder, width: 0.5),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                bertAvatar(20),
                const SizedBox(width: 8),
                Text(_briefTitle(b['kind'] as String?),
                    style: OracleType.label),
              ],
            ),
            const SizedBox(height: 12),
            Text(b['text'] as String? ?? '', style: OracleType.journal),
          ],
        ),
      ));
      out.add(const SizedBox(height: OracleSpace.section));
    }
    return out;
  }

  String _briefTitle(String? kind) {
    final base = kind == 'morning'
        ? '조간'
        : kind == 'evening'
            ? '석간'
            : '발행물';
    return _isToday ? '오늘의 $base' : base;
  }

  // ── 어제로부터 — 전날 일기 발췌 ─────────────────────────────
  List<Widget> _yesterdayLine() {
    final y = _cover?['yesterday_line'] as Map<String, dynamic>?;
    if (y == null) return const [];
    return [
      _sectionLabel(_isToday ? '어제로부터' : '전날로부터'),
      const SizedBox(height: 8),
      Text('“${y['text']}”',
          style: OracleType.journal.copyWith(fontSize: 16, height: 28 / 16)),
      const SizedBox(height: OracleSpace.section),
    ];
  }

  // ── 오늘 지금까지 (과거면 그날의 기록) ──────────────────────
  List<Widget> _todaySoFar() {
    final t = _cover?['today'] as Map<String, dynamic>?;
    final count = (t?['count'] as num?)?.toInt() ?? 0;
    final thumbs = (t?['thumbs'] as List?)?.cast<String>() ?? const <String>[];
    final lastTs = t?['last_ts'] as String?;
    final emptyMsg = _isToday
        ? '아직 기록이 없어요 — 첫 장면을 담아보세요'
        : '이 날의 기록이 없어요';
    return [
      _sectionLabel(_isToday ? '오늘 지금까지' : '그날의 기록'),
      const SizedBox(height: 8),
      InkWell(
        onTap: _isToday ? widget.onGoHistory : null,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              count == 0
                  ? emptyMsg
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

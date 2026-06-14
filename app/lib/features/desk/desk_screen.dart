import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../api.dart';
import '../../applog.dart';
import '../../core/design.dart';
import '../signals/signals_screen.dart';

/// 데스크 — 온라인 오라클. '확인하면 사라지는' 처리 대시보드.
///
/// 오늘 탭이 '읽을 거리(표지)'라면 데스크는 '처리할 거리'다. 당장 처리(신호 액션)·
/// 오래 못 챙긴 사람을 확인하면 목록에서 빠지고, 대신 읽어드림·오늘 정리는 정보로 남는다.
/// 신문사 데스크처럼 — 올라온 것을 처리하면 비워지는 책상.
class DeskScreen extends StatefulWidget {
  final OracleApi api;
  final bool embedded; // 탭에 임베드 시 Scaffold/AppBar 생략
  const DeskScreen({super.key, required this.api, this.embedded = false});

  @override
  State<DeskScreen> createState() => _DeskScreenState();
}

class _DeskScreenState extends State<DeskScreen>
    with AutomaticKeepAliveClientMixin {
  Map<String, dynamic>? _data;
  String? _error;
  final Set<String> _dismissing = {}; // 낙관적 제거 중인 키

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final d = await widget.api.fetchDashboard();
      if (mounted) {
        setState(() {
          _data = d;
          _error = null;
          _dismissing.clear(); // 새로 받은 목록엔 이미 제외돼 옴
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  /// 항목 확인 — 즉시 숨기고(낙관적) 백엔드 기록. 실패 시 복원.
  Future<void> _dismiss(String key) async {
    setState(() => _dismissing.add(key));
    AppLog.ui('데스크 확인 → $key');
    try {
      await widget.api.dismissDashboard(key);
    } catch (_) {
      if (mounted) setState(() => _dismissing.remove(key));
    }
  }

  List<Map<String, dynamic>> _visible(String field) {
    final list =
        (_data?[field] as List?)?.cast<Map<String, dynamic>>() ?? const [];
    return list.where((it) => !_dismissing.contains(it['key'])).toList();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final actions = _visible('actions');
    final pending = _visible('pending_people');
    final brief = _data?['brief'] as Map<String, dynamic>?;
    final briefShown = brief != null && !_dismissing.contains(brief['key']);
    final today = _data?['today'] as Map<String, dynamic>?;
    final allClear = _data != null && actions.isEmpty && pending.isEmpty;

    final content = RefreshIndicator(
      color: OracleColors.vermilion,
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(
            OracleSpace.screenH, 20, OracleSpace.screenH, 48),
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
                      strokeWidth: 1, color: OracleColors.faint),
                ),
              ),
            )
          else ...[
            // 1) 당장 처리 — 확인하면 사라짐 (가장 위, 주홍 액센트)
            if (actions.isNotEmpty) ...[
              _sectionLabel('당장 처리', count: actions.length, accent: true),
              const SizedBox(height: 14),
              for (final a in actions) _actionRow(a),
              const SizedBox(height: OracleSpace.section),
            ],
            // 2) 대신 읽어드림 — 읽으면 사라짐, 전체보기 → 신호 로그
            ..._briefCard(briefShown ? brief : null),
            // 3) 오래 못 챙긴 사람 — 확인하면 사라짐
            if (pending.isNotEmpty) ...[
              _sectionLabel('오래 못 챙긴 사람', count: pending.length),
              const SizedBox(height: 12),
              for (final p in pending) _pendingRow(p),
              const SizedBox(height: OracleSpace.section),
            ],
            // 인박스 제로 — 처리할 게 없을 때
            if (allClear) _allClear(),
            // 4) 오늘 정리 — 내 활동을 데이터로
            ..._todayCard(today),
          ],
        ],
      ),
    );
    if (widget.embedded) return content;
    return Scaffold(
      appBar: AppBar(title: const Text('데스크')),
      body: content,
    );
  }

  // ── 당장 처리 한 줄 — 체크 동그라미 탭하면 확인(사라짐) ──────────
  Widget _actionRow(Map<String, dynamic> a) {
    final ts = DateTime.tryParse(a['ts'] as String? ?? '');
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            onTap: () => _dismiss(a['key'] as String),
            customBorder: const CircleBorder(),
            child: const Padding(
              padding: EdgeInsets.all(2),
              child: Icon(Icons.radio_button_unchecked,
                  size: 22, color: OracleColors.vermilion),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(a['sender'] as String? ?? '',
                          style: OracleType.timestamp
                              .copyWith(color: OracleColors.gray)),
                    ),
                    if (ts != null)
                      Text(DateFormat('M/d HH:mm').format(ts.toLocal()),
                          style: OracleType.label),
                  ],
                ),
                const SizedBox(height: 2),
                Text(a['summary'] as String? ?? '',
                    style: OracleType.journal.copyWith(
                        fontSize: 15,
                        height: 22 / 15,
                        color: OracleColors.inkSoft)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // ── 오래 못 챙긴 사람 한 줄 ─────────────────────────────────
  Widget _pendingRow(Map<String, dynamic> p) {
    final days = (p['days_silent'] as num?)?.toInt();
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(p['name'] as String? ?? '', style: OracleType.userBody),
                const SizedBox(height: 2),
                Text(days != null ? '$days일째 소식 없음' : '한동안 소식 없음',
                    style:
                        OracleType.marginalia.copyWith(color: OracleColors.gray)),
              ],
            ),
          ),
          TextButton(
            onPressed: () => _dismiss(p['key'] as String),
            style: TextButton.styleFrom(
                minimumSize: const Size(0, 36),
                padding: const EdgeInsets.symmetric(horizontal: 10)),
            child: Text('확인',
                style: OracleType.label.copyWith(color: OracleColors.gray)),
          ),
        ],
      ),
    );
  }

  // ── 대신 읽어드림 카드 — 최신 brief 요약 + 전체보기 ────────────
  List<Widget> _briefCard(Map<String, dynamic>? b) {
    void goFull() => Navigator.push(context,
        MaterialPageRoute(builder: (_) => SignalsScreen(api: widget.api)));
    if (b == null) {
      return [
        InkWell(
          onTap: goFull,
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
      if ((b['notif_count'] as num? ?? 0) > 0) '알림 ${b['notif_count']}',
    ];
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
            Row(
              children: [
                Expanded(
                  child: _sectionLabel(
                      '대신 읽어드림${ts != null ? ' · ${DateFormat('HH:mm').format(ts.toLocal())}' : ''}'
                      '${parts.isNotEmpty ? ' · ${parts.join(' · ')}' : ''}'),
                ),
                // 읽음 — 확인 처리하면 카드가 사라진다
                InkWell(
                  onTap: () => _dismiss(b['key'] as String),
                  child: Padding(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    child: Text('읽음',
                        style: OracleType.label
                            .copyWith(color: OracleColors.vermilion)),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            // 본문 탭 = 전체보기(신호 로그)
            InkWell(
              onTap: goFull,
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Text(b['summary'] as String? ?? '',
                        style: OracleType.marginalia,
                        maxLines: 8,
                        overflow: TextOverflow.ellipsis),
                  ),
                  const SizedBox(width: 8),
                  Text('전체보기',
                      style: OracleType.label
                          .copyWith(color: OracleColors.gray)),
                  const Icon(Icons.chevron_right,
                      size: 16, color: OracleColors.faint),
                ],
              ),
            ),
          ],
        ),
      ),
      const SizedBox(height: OracleSpace.section),
    ];
  }

  // ── 오늘 정리 — 활동 통계 ──────────────────────────────────
  List<Widget> _todayCard(Map<String, dynamic>? t) {
    if (t == null) return const [];
    int v(String k) => (t[k] as num?)?.toInt() ?? 0;
    return [
      _sectionLabel('오늘 정리'),
      const SizedBox(height: 14),
      Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          _stat('기록', v('records')),
          _stat('사진', v('photos')),
          _stat('이번 주', v('week_records')),
          _stat('신호', v('signals_today')),
        ],
      ),
    ];
  }

  Widget _stat(String label, int n) => Expanded(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('$n', style: OracleType.display.copyWith(fontSize: 26, height: 30 / 26)),
            const SizedBox(height: 2),
            Text(label, style: OracleType.label),
          ],
        ),
      );

  // ── 공용 조각 ──────────────────────────────────────────────
  Widget _sectionLabel(String text, {int? count, bool accent = false}) => Row(
        children: [
          Container(width: 14, height: 1, color: OracleColors.vermilion),
          const SizedBox(width: 8),
          Flexible(
            child: Text(text,
                style: OracleType.label.copyWith(
                    color: accent ? OracleColors.vermilion : OracleColors.faint),
                overflow: TextOverflow.ellipsis),
          ),
          if (count != null) ...[
            const SizedBox(width: 6),
            Text('$count',
                style: OracleType.label.copyWith(
                    color: accent ? OracleColors.vermilion : OracleColors.gray)),
          ],
        ],
      );

  Widget _allClear() => Padding(
        padding: const EdgeInsets.symmetric(vertical: 28),
        child: Column(
          children: [
            const Icon(Icons.check_circle_outline,
                size: 36, color: OracleColors.faint),
            const SizedBox(height: 10),
            Text('처리할 게 없어요 — 깔끔하네요',
                style: OracleType.marginalia.copyWith(color: OracleColors.gray)),
          ],
        ),
      );
}

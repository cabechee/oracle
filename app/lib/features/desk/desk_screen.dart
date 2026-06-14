import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../api.dart';
import '../../applog.dart';
import '../../core/design.dart';
import '../signals/signals_screen.dart';

/// 데스크 — 온라인 오라클. 처리할 것 + 오늘 받은 알림 종합.
///
/// 당장 처리(신호 액션·dismiss) · 리마인더(자체 할 일) · 오늘 받은 알림(발신자별
/// 누적 요약 — 안 날림) · 가계부(결제 스마트액션) · 오래 못 챙긴 사람 · 오늘 정리.
/// 알림은 30분마다 누적되어 '지금까지'를 보여준다(다음날이 아니라 실시간).
class DeskScreen extends StatefulWidget {
  final OracleApi api;
  final bool embedded;
  const DeskScreen({super.key, required this.api, this.embedded = false});

  @override
  State<DeskScreen> createState() => _DeskScreenState();
}

class _DeskScreenState extends State<DeskScreen>
    with AutomaticKeepAliveClientMixin {
  Map<String, dynamic>? _data;
  String? _error;
  final Set<String> _dismissing = {};
  final Set<String> _expanded = {};   // 펼친 digest 발신자 그룹
  bool _ledgerOpen = false;

  static const _catLabel = {
    'attention': '관심', 'acquaintance': '지인', 'low': '일반', 'spam': '스팸',
  };

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
          _dismissing.clear();
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

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

  void _toast(String m) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));
  }

  // ── 리마인더 ────────────────────────────────────────────────
  Future<void> _addReminder() async {
    final text = await _promptText();
    if (text == null || text.trim().isEmpty) return;
    try {
      await widget.api.addReminder(text.trim());
      await _load();
    } catch (_) {
      _toast('추가 실패');
    }
  }

  Future<void> _toggleReminder(Map<String, dynamic> r) async {
    final id = r['id'] as String;
    final done = !(r['done'] == true);
    setState(() => r['done'] = done);
    try {
      await widget.api.setReminderDone(id, done);
      if (done) await _load();
    } catch (_) {
      if (mounted) setState(() => r['done'] = !done);
    }
  }

  Future<void> _removeReminder(Map<String, dynamic> r) async {
    try {
      await widget.api.removeReminder(r['id'] as String);
      await _load();
    } catch (_) {}
  }

  /// 당장 처리 항목 → 리마인더로 승격 (처리는 리마인더에서).
  Future<void> _promoteToReminder(Map<String, dynamic> a) async {
    try {
      await widget.api.addReminder(
        '${a['sender']}: ${a['summary']}',
        source: 'signal',
        signalId: a['key'] as String,
      );
      await widget.api.dismissDashboard(a['key'] as String);
      setState(() => _dismissing.add(a['key'] as String));
      await _load();
      _toast('리마인더로 옮겼어요');
    } catch (_) {
      _toast('실패');
    }
  }

  Future<String?> _promptText() async {
    final ctrl = TextEditingController();
    return showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: OracleColors.paper,
        title: Text('리마인더', style: OracleType.dateHeader),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          style: OracleType.userBody,
          decoration: const InputDecoration(hintText: '할 일을 적어주세요'),
          onSubmitted: (v) => Navigator.pop(ctx, v),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: Text('취소',
                  style: OracleType.label.copyWith(color: OracleColors.gray))),
          TextButton(
              onPressed: () => Navigator.pop(ctx, ctrl.text),
              child: Text('추가',
                  style:
                      OracleType.label.copyWith(color: OracleColors.vermilion))),
        ],
      ),
    );
  }

  void _openSignals() => Navigator.push(context,
      MaterialPageRoute(builder: (_) => SignalsScreen(api: widget.api)));

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final actions = _visible('actions');
    final pending = _visible('pending_people');

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
            // 1) 당장 처리 — 확인하면 사라짐
            if (actions.isNotEmpty) ...[
              _sectionLabel('당장 처리', count: actions.length, accent: true),
              const SizedBox(height: 14),
              for (final a in actions) _actionRow(a),
              const SizedBox(height: OracleSpace.section),
            ],
            // 2) 리마인더 — 자체 할 일
            ..._reminderSection(),
            // 3) 오늘 받은 알림 — 발신자별 누적 요약 (대신 읽어드림)
            ..._digestSection(),
            // 4) 가계부 — 결제 스마트액션
            ..._ledgerSection(),
            // 5) 오래 못 챙긴 사람
            if (pending.isNotEmpty) ...[
              _sectionLabel('오래 못 챙긴 사람', count: pending.length),
              const SizedBox(height: 12),
              for (final p in pending) _pendingRow(p),
              const SizedBox(height: OracleSpace.section),
            ],
            // 6) 오늘 정리
            ..._todayCard(_data?['today'] as Map<String, dynamic>?),
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

  // ── 당장 처리 ───────────────────────────────────────────────
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
                // 리마인더로 보내기 (나중에 처리할 것)
                Align(
                  alignment: Alignment.centerLeft,
                  child: InkWell(
                    onTap: () => _promoteToReminder(a),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 3),
                      child: Text('리마인더로',
                          style: OracleType.label
                              .copyWith(color: OracleColors.gray)),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // ── 리마인더 ────────────────────────────────────────────────
  List<Widget> _reminderSection() {
    final rems =
        (_data?['reminders'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
    final active = rems.where((r) => r['done'] != true).length;
    return [
      Row(
        children: [
          Expanded(
              child: _sectionLabel('리마인더',
                  count: active > 0 ? active : null)),
          InkWell(
            onTap: _addReminder,
            child: Row(
              children: [
                const Icon(Icons.add, size: 15, color: OracleColors.vermilion),
                const SizedBox(width: 2),
                Text('추가',
                    style:
                        OracleType.label.copyWith(color: OracleColors.vermilion)),
              ],
            ),
          ),
        ],
      ),
      const SizedBox(height: 10),
      if (rems.isEmpty)
        Text('할 일을 적어두면 위젯에도 떠요 — 당장 처리에서 ‘리마인더로’ 보낼 수도 있어요',
            style: OracleType.marginalia.copyWith(color: OracleColors.gray))
      else
        for (final r in rems) _reminderRow(r),
      const SizedBox(height: OracleSpace.section),
    ];
  }

  Widget _reminderRow(Map<String, dynamic> r) {
    final done = r['done'] == true;
    return InkWell(
      onLongPress: () => _removeReminder(r),
      child: Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            InkWell(
              onTap: () => _toggleReminder(r),
              customBorder: const CircleBorder(),
              child: Padding(
                padding: const EdgeInsets.all(2),
                child: Icon(
                    done
                        ? Icons.check_circle
                        : Icons.radio_button_unchecked,
                    size: 20,
                    color: done ? OracleColors.gray : OracleColors.vermilion),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.only(top: 1),
                child: Text(r['text'] as String? ?? '',
                    style: OracleType.userBody.copyWith(
                      decoration: done ? TextDecoration.lineThrough : null,
                      color: done ? OracleColors.faint : OracleColors.ink,
                    )),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ── 오늘 받은 알림 (digest) ─────────────────────────────────
  List<Widget> _digestSection() {
    final digest = _data?['digest'] as Map<String, dynamic>?;
    final groups =
        (digest?['groups'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
    final totals = digest?['totals'] as Map<String, dynamic>? ?? const {};
    final signalCount = (digest?['signal_count'] as num?)?.toInt() ?? 0;
    if (groups.isEmpty) {
      return [
        InkWell(
          onTap: _openSignals,
          child: Row(children: [
            Expanded(child: _sectionLabel('오늘 받은 알림')),
            const Icon(Icons.chevron_right, size: 18, color: OracleColors.faint),
          ]),
        ),
        const SizedBox(height: 6),
        Text('문자·부재중·앱 알림이 들어오면 30분마다 모아 정리해드려요',
            style: OracleType.marginalia.copyWith(color: OracleColors.gray)),
        const SizedBox(height: OracleSpace.section),
      ];
    }
    return [
      InkWell(
        onTap: _openSignals,
        child: Row(children: [
          Expanded(child: _sectionLabel('오늘 받은 알림 · $signalCount건')),
          Text('전체보기',
              style: OracleType.label.copyWith(color: OracleColors.gray)),
          const Icon(Icons.chevron_right, size: 16, color: OracleColors.faint),
        ]),
      ),
      const SizedBox(height: 6),
      Text(_totalsLine(totals),
          style: OracleType.marginalia.copyWith(color: OracleColors.gray)),
      const SizedBox(height: 14),
      for (final g in groups) _digestGroup(g),
      const SizedBox(height: OracleSpace.section),
    ];
  }

  String _totalsLine(Map<String, dynamic> totals) {
    final parts = <String>[];
    for (final e in _catLabel.entries) {
      final n = (totals[e.key] as num?)?.toInt() ?? 0;
      if (n > 0) parts.add('${e.value} $n');
    }
    return parts.isEmpty ? '' : parts.join('  ·  ');
  }

  Widget _digestGroup(Map<String, dynamic> g) {
    final sender = g['sender'] as String? ?? '';
    final cat = g['category'] as String? ?? 'low';
    final count = (g['count'] as num?)?.toInt() ?? 0;
    final lines = (g['lines'] as List?)?.cast<String>() ?? const [];
    final open = _expanded.contains(sender);
    final shown = open ? lines : lines.take(1).toList();
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            onTap: () => setState(() =>
                open ? _expanded.remove(sender) : _expanded.add(sender)),
            child: Row(
              children: [
                _catChip(cat),
                const SizedBox(width: 8),
                Expanded(
                    child: Text(sender,
                        style: OracleType.userBody,
                        overflow: TextOverflow.ellipsis)),
                Text('$count건',
                    style:
                        OracleType.label.copyWith(color: OracleColors.gray)),
                if (lines.length > 1)
                  Icon(open ? Icons.expand_less : Icons.expand_more,
                      size: 16, color: OracleColors.faint),
              ],
            ),
          ),
          const SizedBox(height: 2),
          for (final ln in shown)
            Padding(
              padding: const EdgeInsets.only(left: 4, top: 2),
              child: Text('· $ln',
                  style: OracleType.marginalia,
                  maxLines: open ? null : 1,
                  overflow:
                      open ? TextOverflow.visible : TextOverflow.ellipsis),
            ),
          if (!open && lines.length > 1)
            Padding(
              padding: const EdgeInsets.only(left: 4, top: 2),
              child: Text('+${lines.length - 1}건 더',
                  style: OracleType.label.copyWith(color: OracleColors.faint)),
            ),
        ],
      ),
    );
  }

  Widget _catChip(String cat) {
    final label = _catLabel[cat] ?? cat;
    final color = (cat == 'spam' || cat == 'low')
        ? OracleColors.gray
        : (cat == 'attention' ? OracleColors.vermilion : OracleColors.ink);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 1),
      decoration: BoxDecoration(
        border: Border.all(color: color.withValues(alpha: 0.4)),
        borderRadius: BorderRadius.circular(99),
      ),
      child: Text(label,
          style: OracleType.label.copyWith(color: color, fontSize: 10.5)),
    );
  }

  // ── 가계부 ──────────────────────────────────────────────────
  List<Widget> _ledgerSection() {
    final l = _data?['ledger'] as Map<String, dynamic>?;
    final count = (l?['count'] as num?)?.toInt() ?? 0;
    if (count == 0) return const [];
    final total = (l?['total'] as num?)?.toInt() ?? 0;
    final items =
        (l?['items'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
    return [
      InkWell(
        onTap: () => setState(() => _ledgerOpen = !_ledgerOpen),
        child: Row(children: [
          Expanded(child: _sectionLabel('오늘 가계부 · ${_won(total)}')),
          Text('$count건',
              style: OracleType.label.copyWith(color: OracleColors.gray)),
          Icon(_ledgerOpen ? Icons.expand_less : Icons.expand_more,
              size: 16, color: OracleColors.faint),
        ]),
      ),
      if (_ledgerOpen) ...[
        const SizedBox(height: 10),
        for (final it in items) _ledgerRow(it),
      ],
      const SizedBox(height: OracleSpace.section),
    ];
  }

  Widget _ledgerRow(Map<String, dynamic> it) {
    final amount = (it['amount'] as num?)?.toInt() ?? 0;
    final card = it['card'] as String? ?? '';
    final installment = it['installment'] == true;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 96,
            child: Text(_won(amount),
                style: OracleType.userBody
                    .copyWith(fontFeatures: const [])),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
                '$card${installment ? ' · 할부' : ''}',
                style: OracleType.marginalia.copyWith(color: OracleColors.gray)),
          ),
        ],
      ),
    );
  }

  String _won(int n) {
    final s = n.toString().replaceAllMapped(
        RegExp(r'(\d)(?=(\d{3})+$)'), (m) => '${m[1]},');
    return '$s원';
  }

  // ── 오래 못 챙긴 사람 ───────────────────────────────────────
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

  // ── 오늘 정리 ───────────────────────────────────────────────
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
            Text('$n',
                style: OracleType.display.copyWith(fontSize: 26, height: 30 / 26)),
            const SizedBox(height: 2),
            Text(label, style: OracleType.label),
          ],
        ),
      );

  // ── 공용 ────────────────────────────────────────────────────
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
}

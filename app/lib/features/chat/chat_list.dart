import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../api.dart';
import '../../core/design.dart';
import '../../core/record_store.dart';
import '../../models.dart';
import 'chat_controller.dart';
import 'chat_message_bubble.dart';
import 'pending_bubble.dart';
import 'record_bubble.dart';

/// 히스토리 타임라인 — 왼쪽 스파인(시간축)에 기록·대화가 매달리는 에디토리얼 문법.
/// 다이제스트는 홈 탭에만 두고 여기선 기록·대화만. store 구독, 로직은 [chat].
class ChatList extends StatelessWidget {
  final RecordStore store;
  final ChatController chat;
  final OracleApi api;
  final Future<void> Function()? onBackfill; // 지나간 사진 업로드 (웹만)

  const ChatList({
    super.key,
    required this.store,
    required this.chat,
    required this.api,
    this.onBackfill,
  });

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: store,
      builder: (context, _) {
        final entries = _mergedEntries();
        final rows = _displayRows(entries);   // 날짜 바뀌는 지점에 구분선 삽입
        final pendingChat = store.pendingChatText;
        // reverse 리스트: index 0 = 화면 맨 아래.
        // [대화 전송 중][캡처 현상 중...][record·대화·날짜구분선 merge...]
        final head = pendingChat != null ? 1 : 0;
        final total = rows.length + store.pendings.length + head;
        return Column(
          children: [
            Expanded(
              child: Stack(
                children: [
                  // 스파인 — 타임라인 전체를 관통하는 시간축
                  const Positioned(
                    left: OracleSpace.rail,
                    top: 0,
                    bottom: 0,
                    width: 0.5,
                    child: ColoredBox(color: OracleColors.hairlineSoft),
                  ),
                  ListView.builder(
                    controller: chat.scroll,
                    reverse: true,
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    itemCount: total,
                    itemBuilder: (ctx, i) {
                      var idx = i;
                      if (pendingChat != null) {
                        if (idx == 0) {
                          return _SpineEntry(
                            time: '· ·',
                            child: PendingChatBubble(text: pendingChat),
                          );
                        }
                        idx -= 1;
                      }
                      if (idx < store.pendings.length) {
                        final p = store.pendings[idx];
                        return _SpineEntry(
                          time: '· ·',
                          child: GestureDetector(
                            onTap: () => _cancelPending(context, p),
                            child: PendingBubble(
                              comment: p.comment,
                              photos: p.photos,
                              hasAudio: p.audioPath != null,
                              hasVideo: p.videoPath != null,
                            ),
                          ),
                        );
                      }
                      final row = rows[idx - store.pendings.length];
                      if (row is _DateDivider) {
                        return _DateDividerRow(date: row.date);
                      }
                      if (row is ChatMessage) {
                        return _SpineEntry(
                          time: DateFormat('HH:mm').format(row.ts.toLocal()),
                          child: ChatMessageBubble(message: row, api: api),
                        );
                      }
                      // idx가 아니라 record 자체를 캡처 — 시트/탭 처리 중 목록이
                      // 밀려도(pending 도착·refresh) 항상 이 record에 반영된다.
                      final rec = row as Record;
                      return _SpineEntry(
                        time: DateFormat('HH:mm').format(rec.ts.toLocal()),
                        child: GestureDetector(
                          onLongPress: () => _recordMenu(context, rec),
                          child: RecordBubble(
                            record: rec,
                            api: api,
                            onReact: (section, value) =>
                                chat.react(rec, section, value),
                          ),
                        ),
                      );
                    },
                  ),
                ],
              ),
            ),
            _ChatInputBar(
              busy: store.pendingChatText != null,
              mentions: store.chatMentions,
              onRemoveMention: store.removeMention,
              onSend: chat.sendChat,
              onUpload: onBackfill,
            ),
          ],
        );
      },
    );
  }

  /// records + 대화 메시지를 ts 내림차순으로 merge (둘 다 최신순 정렬돼 있음).
  List<Object> _mergedEntries() {
    final out = <Object>[];
    var ri = 0, mi = 0;
    final recs = store.records;
    final msgs = store.messages;
    while (ri < recs.length || mi < msgs.length) {
      if (mi >= msgs.length ||
          (ri < recs.length && !recs[ri].ts.isBefore(msgs[mi].ts))) {
        out.add(recs[ri++]);
      } else {
        out.add(msgs[mi++]);
      }
    }
    return out;
  }

  /// 항목 사이 날짜가 바뀌면 그 날의 구분선을 끼운다. entries는 최신→과거 순,
  /// reverse 리스트라 구분선은 '그 날 묶음 위(과거쪽)'에 오도록 묶음의 마지막 뒤에 넣는다.
  List<Object> _displayRows(List<Object> entries) {
    final rows = <Object>[];
    for (var i = 0; i < entries.length; i++) {
      rows.add(entries[i]);
      final last = i == entries.length - 1;
      if (last || _dayKey(entries[i + 1]) != _dayKey(entries[i])) {
        rows.add(_DateDivider(_tsOf(entries[i]).toLocal()));
      }
    }
    return rows;
  }

  DateTime _tsOf(Object e) => e is ChatMessage ? e.ts : (e as Record).ts;
  String _dayKey(Object e) {
    final t = _tsOf(e).toLocal();
    return '${t.year}-${t.month}-${t.day}';
  }

  Future<void> _cancelPending(BuildContext context, PendingCapture p) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: OracleColors.paper,
        title: Text(
          '현상을 멈출까요?',
          style: OracleType.journal.copyWith(fontSize: 15),
        ),
        content: Text(
          '큐에서 사라집니다. 백엔드가 이미 처리 중이면 결과는 도착할 수 있어요.',
          style: OracleType.marginalia,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: Text(
              '아니요',
              style: OracleType.userBody.copyWith(color: OracleColors.gray),
            ),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text(
              '멈춤',
              style: OracleType.userBody.copyWith(
                color: OracleColors.vermilion,
              ),
            ),
          ),
        ],
      ),
    );
    if (ok == true) {
      // 쿠키가 이미 응답해 백엔드 record가 생겼으면 그것도 숨긴다(soft delete).
      if (p.recordId != null) {
        try {
          await api.hideRecord(p.recordId!);
        } catch (_) {}
      }
      store.removePending(p.id);
    }
  }

  // ── 길게누름 메뉴 (언급 / 수정) ──────────────────────────
  Future<void> _recordMenu(BuildContext context, Record rec) async {
    final choice = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: OracleColors.paper,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              title: Text('이 기록 언급하기', style: OracleType.userBody),
              subtitle: Text('베르가 이 기록 얘기로 답해요', style: OracleType.marginalia),
              onTap: () => Navigator.pop(context, 'mention'),
            ),
            ListTile(
              title: Text('재처리 (분석 다시)', style: OracleType.userBody),
              subtitle: Text('내용이 이상하면 같은 사진·코멘트로 다시 분석',
                  style: OracleType.marginalia),
              onTap: () => Navigator.pop(context, 'reprocess'),
            ),
            ListTile(
              title: Text('수정하기', style: OracleType.userBody),
              onTap: () => Navigator.pop(context, 'edit'),
            ),
            ListTile(
              title: Text('삭제 (숨김)',
                  style: OracleType.userBody
                      .copyWith(color: OracleColors.vermilion)),
              subtitle: Text('흐름에서 제거 — 어드민엔 남아요',
                  style: OracleType.marginalia),
              onTap: () => Navigator.pop(context, 'hide'),
            ),
          ],
        ),
      ),
    );
    if (choice == 'mention') {
      chat.mention(rec);
    } else if (choice == 'reprocess' && context.mounted) {
      _reprocessMenu(context, rec);
    } else if (choice == 'edit' && context.mounted) {
      _editRecord(context, rec);
    } else if (choice == 'hide') {
      chat.hideRecord(rec);
    }
  }

  // ── 재처리 — 부분 선택 (전체/분석/코멘트/디스커버리/쿠키) ──────
  Future<void> _reprocessMenu(BuildContext context, Record rec) async {
    final hasPhoto = rec.imagePaths.isNotEmpty;
    final part = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: OracleColors.paper,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (final o in [
              ('all', '전체 다시'),
              if (hasPhoto) ('analysis', '분석만'),
              ('comment', '코멘트만'),
              if (hasPhoto) ('discovery', '디스커버리만'),
              ('quick', '쿠키 한마디만'),
            ])
              ListTile(
                title: Text(o.$2, style: OracleType.userBody),
                onTap: () => Navigator.pop(context, o.$1),
              ),
          ],
        ),
      ),
    );
    if (part != null) chat.reprocess(rec, part: part);
  }

  // ── record 편집 (잘못 보낸 거 정정) ──────────────────────
  Future<void> _editRecord(BuildContext context, Record rec) async {
    final ctrl = TextEditingController(text: rec.userComment);
    final newText = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      backgroundColor: OracleColors.paper,
      builder: (ctx) {
        return Padding(
          padding: EdgeInsets.fromLTRB(
            OracleSpace.screenH,
            20,
            OracleSpace.screenH,
            MediaQuery.of(ctx).viewInsets.bottom + 20,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('기록 정정', style: OracleType.journal.copyWith(fontSize: 15)),
              const SizedBox(height: 14),
              TextField(
                controller: ctrl,
                autofocus: true,
                minLines: 2,
                maxLines: 5,
                style: OracleType.userBody,
                decoration: const InputDecoration(
                  enabledBorder: UnderlineInputBorder(
                    borderSide: BorderSide(
                      color: OracleColors.hairline,
                      width: 0.5,
                    ),
                  ),
                  focusedBorder: UnderlineInputBorder(
                    borderSide: BorderSide(color: OracleColors.ink, width: 0.5),
                  ),
                ),
              ),
              const SizedBox(height: 10),
              Text(
                '정본 평문은 변경되지 않습니다 — 화면(Mongo)만 갱신.',
                style: OracleType.label,
              ),
              const SizedBox(height: 14),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: () => Navigator.pop(ctx, null),
                    child: Text(
                      '취소',
                      style: OracleType.userBody.copyWith(
                        color: OracleColors.gray,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  TextButton(
                    onPressed: () => Navigator.pop(ctx, ctrl.text),
                    child: Text(
                      '저장',
                      style: OracleType.userBody.copyWith(
                        color: OracleColors.vermilion,
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        );
      },
    );
    if (newText != null) await chat.updateComment(rec, newText);
  }
}

/// 날짜 경계 마커 — _displayRows가 넣는 가벼운 표식.
class _DateDivider {
  final DateTime date;
  const _DateDivider(this.date);
}

/// 날짜 구분선 — 흐름에서 날짜가 바뀌는 경계. "6월 18일 · 수" 가운데 라벨 + 헤어라인.
class _DateDividerRow extends StatelessWidget {
  final DateTime date;
  const _DateDividerRow({required this.date});

  static const _wk = ['월', '화', '수', '목', '금', '토', '일'];

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    final isToday =
        date.year == now.year && date.month == now.month && date.day == now.day;
    final y = now.subtract(const Duration(days: 1));
    final isYest =
        date.year == y.year && date.month == y.month && date.day == y.day;
    final base = '${date.month}월 ${date.day}일 · ${_wk[date.weekday - 1]}';
    final label = isToday ? '오늘 — $base' : (isYest ? '어제 — $base' : base);
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          OracleSpace.screenH, 12, OracleSpace.screenH, 20),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          const Expanded(
            child: SizedBox(
                height: 0.5,
                child: ColoredBox(color: OracleColors.hairlineSoft)),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10),
            child: Text(label,
                style: OracleType.label.copyWith(color: OracleColors.gray)),
          ),
          const Expanded(
            child: SizedBox(
                height: 0.5,
                child: ColoredBox(color: OracleColors.hairlineSoft)),
          ),
        ],
      ),
    );
  }
}

/// 스파인 엔트리 — 레일(시간+틱) + 본문 컬럼.
class _SpineEntry extends StatelessWidget {
  final String time;
  final Widget child;
  const _SpineEntry({required this.time, required this.child});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(
        bottom: OracleSpace.entry,
        right: OracleSpace.screenH,
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: OracleSpace.rail,
            child: Stack(
              children: [
                Padding(
                  padding: const EdgeInsets.only(right: 12, top: 1),
                  child: Align(
                    alignment: Alignment.topRight,
                    child: Text(time, style: OracleType.timestamp),
                  ),
                ),
                // 틱 — 스파인 위에 걸치는 6pt 가로선
                const Positioned(
                  right: -3,
                  top: 8,
                  child: SizedBox(
                    width: 6,
                    height: 0.5,
                    child: ColoredBox(color: OracleColors.ink),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: OracleSpace.gutter),
          Expanded(child: child),
        ],
      ),
    );
  }
}

/// 대화 입력 — 헤어라인 위 무장식 한 줄. 멘션이 있으면 위에 칩 줄.
class _ChatInputBar extends StatefulWidget {
  final bool busy;
  final List<Record> mentions;
  final void Function(String) onRemoveMention;
  final Future<void> Function(String) onSend;
  final Future<void> Function()? onUpload; // 지나간 사진 업로드 (웹만, null이면 버튼 없음)
  const _ChatInputBar({
    required this.busy,
    required this.mentions,
    required this.onRemoveMention,
    required this.onSend,
    this.onUpload,
  });

  @override
  State<_ChatInputBar> createState() => _ChatInputBarState();
}

class _ChatInputBarState extends State<_ChatInputBar> {
  final _ctrl = TextEditingController();

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  void _send() {
    final t = _ctrl.text.trim();
    if (t.isEmpty || widget.busy) return;
    _ctrl.clear();
    widget.onSend(t);
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        border: Border(
          top: BorderSide(color: OracleColors.hairline, width: 0.5),
        ),
      ),
      padding: const EdgeInsets.fromLTRB(
        OracleSpace.screenH,
        4,
        OracleSpace.screenH,
        8,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (widget.mentions.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 6, top: 2),
              child: Wrap(
                spacing: 6,
                runSpacing: 4,
                children: [for (final m in widget.mentions) _mentionChip(m)],
              ),
            ),
          Row(
            children: [
              if (widget.onUpload != null) ...[
                InkWell(
                  onTap: () => widget.onUpload!(),
                  child: const Padding(
                    padding: EdgeInsets.all(6),
                    child: Icon(Icons.add_photo_alternate_outlined,
                        size: 22, color: OracleColors.gray),
                  ),
                ),
                const SizedBox(width: 4),
              ],
              Expanded(
                child: TextField(
                  controller: _ctrl,
                  style: OracleType.userBody,
                  decoration: InputDecoration(
                    hintText: '이야기하기',
                    hintStyle: OracleType.userBody.copyWith(
                      color: OracleColors.faint,
                    ),
                    border: InputBorder.none,
                    isDense: true,
                    contentPadding: const EdgeInsets.symmetric(vertical: 12),
                  ),
                  minLines: 1,
                  maxLines: 3,
                  onSubmitted: (_) => _send(),
                ),
              ),
              const SizedBox(width: 12),
              widget.busy
                  ? const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(
                        strokeWidth: 1,
                        color: OracleColors.faint,
                      ),
                    )
                  : InkWell(
                      onTap: _send,
                      child: Padding(
                        padding: const EdgeInsets.all(6),
                        child: Text(
                          '\u2192',
                          style: OracleType.dateHeader.copyWith(
                            fontSize: 17,
                            color: OracleColors.ink,
                          ),
                        ),
                      ),
                    ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _mentionChip(Record m) {
    final label = m.userComment.trim().isNotEmpty
        ? m.userComment.trim()
        : (m.imagePaths.isNotEmpty ? '사진' : '기록');
    final short = label.length > 14 ? '${label.substring(0, 14)}…' : label;
    return Container(
      padding: const EdgeInsets.fromLTRB(9, 3, 5, 3),
      decoration: BoxDecoration(
        border: Border.all(color: OracleColors.vermilion),
        borderRadius: BorderRadius.circular(99),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            short,
            style: OracleType.label.copyWith(
              color: OracleColors.vermilion,
              fontSize: 11.5,
            ),
          ),
          const SizedBox(width: 3),
          GestureDetector(
            onTap: () => widget.onRemoveMention(m.id),
            child: const Icon(
              Icons.close,
              size: 13,
              color: OracleColors.vermilion,
            ),
          ),
        ],
      ),
    );
  }
}

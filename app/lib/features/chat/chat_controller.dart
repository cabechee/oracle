import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../api.dart';
import '../../applog.dart';
import '../../core/record_store.dart';
import '../../models.dart';

/// 채팅/히스토리 도메인 — record 로딩·페이지네이션·refresh·리액션·편집 + 대화 모드.
///
/// 자체 관측 상태는 없음(데이터는 [store]). scroll 소유 + api 호출 → store 변경.
class ChatController {
  ChatController({
    required this.api,
    required this.store,
    required this.onToast,
  }) {
    scroll.addListener(_onScroll);
  }

  final OracleApi api;
  final RecordStore store;
  final void Function(String) onToast;

  final ScrollController scroll = ScrollController();

  bool _disposed = false;
  Timer? _procTimer;

  void dispose() {
    _disposed = true;
    _procTimer?.cancel();
    scroll.dispose();
  }

  void _onScroll() {
    if (scroll.position.pixels >= scroll.position.maxScrollExtent - 200) {
      load();
    }
  }

  /// refresh가 진행 중 페이지 응답을 무효화하기 위한 세대 카운터 + 인플라이트 핸들.
  int _generation = 0;
  Future<void>? _inflight;

  Future<void> load({bool initial = false}) {
    if (store.loading || (!initial && !store.hasMore)) return Future.value();
    return _inflight = _doLoad();
  }

  Future<void> _doLoad() async {
    final gen = _generation;
    store.setLoading(true);
    try {
      AppLog.ui('페이지 로드 — offset ${store.records.length}');
      final more = await api.listRecent(
        limit: 30,
        offset: store.records.length,
      );
      if (gen != _generation) return; // refresh가 리셋함 — 옛 offset 기준 응답 폐기
      store.appendRecords(more);
      store.hasMore = more.length >= 30;
      _watchProcessing();
    } catch (e) {
      onToast('읽기 실패: $e');
    } finally {
      store.setLoading(false);
    }
  }

  /// 최신부터 다시 로드 (당겨서 새로고침 · 앱 복귀). 다이제스트 갱신은 홈이 담당.
  /// 진행 중인 페이지 로드가 있으면 끝나길 기다렸다 리셋 — 빈 화면/꼬인 페이지 방지.
  Future<void> refresh() async {
    _generation++;
    try {
      await _inflight;
    } catch (_) {}
    store.resetForReload();
    await Future.wait([load(initial: true), loadMessages()]);
  }

  /// 대화 메시지 로드 (타임라인 merge용) — 실패해도 record 타임라인은 정상.
  Future<void> loadMessages() async {
    try {
      final ms = await api.listChatMessages();
      store.setMessages(ms);
    } catch (_) {}
  }

  // ── 비동기 ingest 잔류 감시 ────────────────────────────────
  // 앱 재시작 등으로 캡처 컨트롤러의 폴링이 끊겨도, 목록에 status=processing
  // record가 보이면 여기서 5s 간격으로 완성본을 당겨와 갱신한다.
  void _watchProcessing() {
    if (_procTimer != null) return;
    if (!store.records.any((r) => r.isProcessing)) return;
    _procTimer = Timer.periodic(const Duration(seconds: 5), (_) async {
      if (_disposed) return;
      final procs = store.records.where((r) => r.isProcessing).toList();
      if (procs.isEmpty) {
        _procTimer?.cancel();
        _procTimer = null;
        return;
      }
      for (final p in procs) {
        try {
          final fresh = await api.getRecord(p.id);
          if (!fresh.isProcessing) {
            store.updateById(p.id, (_) => fresh);
          }
        } catch (_) {}
      }
    });
  }

  // ── 대화 모드 ──────────────────────────────────────────────
  /// 흐름에서 길게 눌러 과거 기록을 언급 — 입력바에 칩으로 붙는다.
  void mention(Record r) {
    AppLog.ui('기록 언급 추가 — ${r.id}');
    store.addMention(r);
    onToast('언급에 추가 — 보내면 이 기록 얘기로 답해요');
  }

  Future<void> sendChat(String text) async {
    final t = text.trim();
    if (t.isEmpty || store.pendingChatText != null) return;
    final mentionIds = store.chatMentions.map((r) => r.id).toList();
    store.setPendingChat(t);
    AppLog.ui('대화 전송 — ${t.length}자, 멘션 ${mentionIds.length}');
    try {
      final ms = await api.sendChat(t, mentionIds: mentionIds);
      store.addMessages(ms);
      store.clearMentions();
    } catch (e) {
      onToast('대화 실패: $e');
    } finally {
      store.setPendingChat(null);
    }
  }

  /// 섹션별 리액션 — 같은 값 다시 누르면 해제(토글).
  Future<void> react(Record rec, String section, String value) async {
    final next = rec.reactions[section] == value ? '' : value;
    AppLog.ui('반응 — $section ${next.isEmpty ? "해제" : next}');
    try {
      await api.setReaction(rec.id, next, section: section);
      store.updateById(rec.id, (r) {
        final m = Map<String, String>.from(r.reactions);
        if (next.isEmpty) {
          m.remove(section);
        } else {
          m[section] = next;
        }
        return r.copyWith(reactions: m);
      });
    } catch (e) {
      onToast('반응 실패: $e');
    }
  }

  Future<void> updateComment(Record rec, String newText) async {
    AppLog.ui('코멘트 수정 — ${rec.id}');
    try {
      await api.updateComment(rec.id, newText);
      store.updateById(rec.id, (r) => r.copyWith(userComment: newText));
    } catch (e) {
      onToast('수정 실패: $e');
    }
  }

  /// 숨김 — 실수 업로드 등. 흐름에서 빼고 백엔드 soft delete(어드민엔 남음).
  Future<void> hideRecord(Record rec) async {
    AppLog.ui('기록 숨김 — ${rec.id}');
    store.removeRecord(rec.id);
    try {
      await api.hideRecord(rec.id);
    } catch (e) {
      onToast('숨김 실패: $e');
    }
  }

  /// 재처리 — 내용이 이상할 때 같은 사진·코멘트로 다시 돌린다.
  /// part = all|quick|analysis|comment|discovery (부분만).
  Future<void> reprocess(Record rec, {String part = 'all'}) async {
    AppLog.ui('재처리 — $part (${rec.id})');
    onToast('재처리 중 — 잠시만요');
    try {
      final fresh = await api.reprocess(rec.id, part: part);
      store.updateById(rec.id, (_) => fresh);
      onToast('재처리 완료');
    } catch (e) {
      onToast('재처리 실패: $e');
    }
  }

  /// 흐름의 동반자 발화 재처리 — 코멘트 반영해 그 자리에서 다시 쓴다.
  Future<void> reprocessCompanion(ChatMessage msg, String comment) async {
    AppLog.ui('발화 재처리 — ${msg.id}');
    onToast('다시 쓰는 중 — 잠시만요');
    try {
      final text = await api.reprocessCompanion(msg.id, comment);
      if (text.isEmpty) {
        onToast('재처리 실패 — 빈 응답');
        return;
      }
      store.updateMessageText(msg.id, text);
      onToast('다시 썼어요');
    } catch (e) {
      onToast('재처리 실패: $e');
    }
  }
}

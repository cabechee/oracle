import 'package:flutter/widgets.dart';

import '../../api.dart';
import '../../core/record_store.dart';

/// 채팅/히스토리 도메인 — record 로딩·페이지네이션·refresh·리액션·편집.
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

  void dispose() {
    scroll.dispose();
  }

  void _onScroll() {
    if (scroll.position.pixels >= scroll.position.maxScrollExtent - 200) {
      load();
    }
  }

  Future<void> load({bool initial = false}) async {
    if (store.loading || (!initial && !store.hasMore)) return;
    store.setLoading(true);
    try {
      final more = await api.listRecent(limit: 30, offset: store.records.length);
      store.appendRecords(more);
      store.hasMore = more.length >= 30;
    } catch (e) {
      onToast('읽기 실패: $e');
    } finally {
      store.setLoading(false);
    }
  }

  /// 최신부터 다시 로드 (당겨서 새로고침 · 앱 복귀). 다이제스트 갱신은 홈이 담당.
  Future<void> refresh() async {
    store.resetForReload();
    await load(initial: true);
  }

  Future<void> react(int idx, String emoji) async {
    if (idx < 0 || idx >= store.records.length) return;
    try {
      await api.setReaction(store.records[idx].id, emoji);
      store.replaceAt(idx, store.records[idx].copyWith(reaction: emoji));
    } catch (e) {
      onToast('반응 실패: $e');
    }
  }

  Future<void> updateComment(int idx, String newText) async {
    if (idx < 0 || idx >= store.records.length) return;
    try {
      await api.updateComment(store.records[idx].id, newText);
      store.replaceAt(idx, store.records[idx].copyWith(userComment: newText));
    } catch (e) {
      onToast('수정 실패: $e');
    }
  }
}

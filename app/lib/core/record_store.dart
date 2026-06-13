import 'dart:io';

import 'package:flutter/foundation.dart';

import '../models.dart';

/// 진행 중인 ingest 단위. 동시에 여러 개 가능 (fire-and-forget).
class PendingCapture {
  final String id;
  final String? comment;
  final List<File> photos; // 여러 장 캡처 — 한 record로 묶임
  final String? audioPath;
  final String? videoPath;
  String? recordId; // ingest stub 받은 뒤 연결 — 취소 시 백엔드 record 숨김용
  PendingCapture({
    required this.id,
    this.comment,
    this.photos = const [],
    this.audioPath,
    this.videoPath,
    this.recordId,
  });
}

/// records + pendings 단일 진실원(SSOT).
///
/// capture(입력) 모듈과 chat(출력) 모듈은 서로 직접 모르고 이 스토어로만 만난다.
/// 모든 변경은 notifyListeners() → ListenableBuilder가 해당 위젯만 리빌드.
class RecordStore extends ChangeNotifier {
  final List<Record> records = [];
  final List<PendingCapture> pendings = [];

  /// 대화 모드 메시지 — record와 ts 기준으로 타임라인에 merge 렌더.
  final List<ChatMessage> messages = [];

  /// 전송 중인 대화 입력 (한 번에 하나 — 입력바 비활성 가드 겸용).
  String? pendingChatText;

  /// 입력바에 붙은 멘션 — 흐름에서 길게 눌러 언급한 과거 record. 전송 시 함께 보냄.
  final List<Record> chatMentions = [];

  /// 페이지네이션 상태 (UI 직접 표시 X — load 가드용).
  bool loading = false;
  bool hasMore = true;

  void addPending(PendingCapture p) {
    pendings.insert(0, p);
    notifyListeners();
  }

  void removePending(String id) {
    pendings.removeWhere((x) => x.id == id);
    notifyListeners();
  }

  /// record 숨김(취소·삭제) — 흐름에서 제거 (백엔드 soft delete와 짝).
  void removeRecord(String id) {
    records.removeWhere((r) => r.id == id);
    notifyListeners();
  }

  /// pending 제거 + 결과 record를 최상단에 삽입 (ingest 성공).
  /// refresh가 먼저 같은 record를 받아왔으면 삽입 대신 교체 (중복 방지).
  void resolvePending(String pendingId, Record record) {
    pendings.removeWhere((x) => x.id == pendingId);
    final i = records.indexWhere((r) => r.id == record.id);
    if (i >= 0) {
      records[i] = record;
    } else {
      records.insert(0, record);
    }
    notifyListeners();
  }

  /// 페이지 append — 이미 있는 id는 건너뜀 (resolvePending과의 레이스로 인한 중복 방지).
  void appendRecords(List<Record> more) {
    final seen = {for (final r in records) r.id};
    records.addAll(more.where((r) => !seen.contains(r.id)));
    notifyListeners();
  }

  /// id로 record 변경 — 목록이 밀려도(삽입·refresh) 항상 맞는 record를 갱신.
  void updateById(String id, Record Function(Record) change) {
    final i = records.indexWhere((x) => x.id == id);
    if (i >= 0) {
      records[i] = change(records[i]);
      notifyListeners();
    }
  }

  /// 대화 메시지 전체 교체 (refresh 시 서버 최신순 목록으로).
  void setMessages(List<ChatMessage> ms) {
    messages
      ..clear()
      ..addAll(ms);
    notifyListeners();
  }

  /// 대화 턴 추가 (전송 완료 시 user+assistant 쌍).
  /// ms는 [user, assistant] 시간순(asc)인데 messages는 최신 먼저(desc)로 유지해야
  /// _mergedEntries 머지가 맞는다 — reversed로 삽입(안 그러면 응답이 내 말 위로 올라감).
  void addMessages(List<ChatMessage> ms) {
    final seen = {for (final m in messages) m.id};
    final fresh = ms.where((m) => !seen.contains(m.id)).toList();
    messages.insertAll(0, fresh.reversed);
    notifyListeners();
  }

  void setPendingChat(String? text) {
    pendingChatText = text;
    notifyListeners();
  }

  void addMention(Record r) {
    if (chatMentions.any((m) => m.id == r.id)) return;
    chatMentions.add(r);
    notifyListeners();
  }

  void removeMention(String id) {
    chatMentions.removeWhere((m) => m.id == id);
    notifyListeners();
  }

  void clearMentions() {
    chatMentions.clear();
    notifyListeners();
  }

  void setLoading(bool v) {
    loading = v;
    notifyListeners();
  }

  /// 최신부터 다시 로드하기 전 초기화.
  void resetForReload() {
    records.clear();
    hasMore = true;
    notifyListeners();
  }
}

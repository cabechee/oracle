import 'dart:io';

import 'package:flutter/foundation.dart';

import '../models.dart';

/// 진행 중인 ingest 단위. 동시에 여러 개 가능 (fire-and-forget).
class PendingCapture {
  final String id;
  final String? comment;
  final File? photo;
  final String? audioPath;
  final String? videoPath;
  PendingCapture({
    required this.id,
    this.comment,
    this.photo,
    this.audioPath,
    this.videoPath,
  });
}

/// records + pendings 단일 진실원(SSOT).
///
/// capture(입력) 모듈과 chat(출력) 모듈은 서로 직접 모르고 이 스토어로만 만난다.
/// 모든 변경은 notifyListeners() → ListenableBuilder가 해당 위젯만 리빌드.
class RecordStore extends ChangeNotifier {
  final List<Record> records = [];
  final List<PendingCapture> pendings = [];

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

  /// pending 제거 + 결과 record를 최상단에 삽입 (ingest 성공).
  void resolvePending(String pendingId, Record record) {
    pendings.removeWhere((x) => x.id == pendingId);
    records.insert(0, record);
    notifyListeners();
  }

  void appendRecords(List<Record> more) {
    records.addAll(more);
    notifyListeners();
  }

  void replaceAt(int idx, Record r) {
    if (idx >= 0 && idx < records.length) {
      records[idx] = r;
      notifyListeners();
    }
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

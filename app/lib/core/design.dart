import 'package:flutter/material.dart';

/// Oracle 디자인 토큰 — "오프화이트 에디토리얼" 시스템.
///
/// 근거 체계(2026-06-11 확정):
/// - 한글 본문 행간 155% 축 (네이버 모바일 연구·KRDS), 일기 본문은 인쇄급 185%
/// - 라틴·숫자·디스플레이는 Apple HIG 자간 곡선 (클수록 조이고 작을수록 벌림)
/// - 모든 행간은 4pt 격자(수직 리듬), 여백은 8pt 격자 + 내부≤외부 위계
/// - 화자 구분은 서체로만: 유저=Pretendard, 동반자=고운바탕(방주), 메타=Literata
abstract final class OracleColors {
  static const paper = Color(0xFFFAF9F6);      // 배경 — 디자인계 오프화이트
  static const mat = Color(0xFFFFFFFF);        // 사진 인화 마진
  static const matBorder = Color(0xFFEEEBE4);
  static const ink = Color(0xFF161411);        // 본문 잉크
  static const inkSoft = Color(0xFF211E19);    // 일기 본문
  static const marginalia = Color(0xFF76705F); // 방주(동반자) 회잉크
  static const gray = Color(0xFF9A948A);       // 보조 텍스트
  static const faint = Color(0xFFC9C4BA);      // 비활성·힌트
  static const hairline = Color(0xFFE5E2DA);   // 구분선
  static const hairlineSoft = Color(0xFFECE9E2); // 스파인
  static const vermilion = Color(0xFFBC4B33);  // 액센트 — 원고지 주홍, 화면당 한 곳
  static const photo = Color(0xFF44403A);      // 사진 placeholder
}

abstract final class OracleType {
  static const sans = 'Pretendard';
  static const serif = 'GowunBatang';
  static const meta = 'Literata';

  /// 유저 본문 15/24 (160% — 한글 모바일 적정), 자간 -0.2
  static const userBody = TextStyle(
    fontFamily: sans,
    fontSize: 15,
    height: 24 / 15,
    letterSpacing: -0.2,
    color: OracleColors.ink,
  );

  /// 방주 — 동반자의 여백 메모. 고운바탕 13.5/22 (본문보다 한 단 작게)
  static const marginalia = TextStyle(
    fontFamily: serif,
    fontSize: 13.5,
    height: 22 / 13.5,
    color: OracleColors.marginalia,
  );

  /// 일기·다이제스트 본문 15/28 (187% — 독서 맥락, 인쇄급)
  static const journal = TextStyle(
    fontFamily: serif,
    fontSize: 15,
    height: 28 / 15,
    color: OracleColors.inkSoft,
  );

  /// 타임스탬프·캡션 — Literata 12/16, Apple 자간 곡선 (+0.12, opsz 8)
  static const timestamp = TextStyle(
    fontFamily: meta,
    fontSize: 12,
    height: 16 / 12,
    letterSpacing: 0.12,
    color: OracleColors.gray,
    fontVariations: [FontVariation('opsz', 8), FontVariation('wght', 400)],
  );

  /// 라벨 11/16 (+0.25 — 자간 곡선의 연장, 한글이라 최소만)
  static const label = TextStyle(
    fontFamily: sans,
    fontSize: 11,
    height: 16 / 11,
    letterSpacing: 0.25,
    color: OracleColors.faint,
  );

  /// 디스플레이 숫자 — Literata Light 40/44, Apple 자간 곡선 -1.2, opsz 72
  static const display = TextStyle(
    fontFamily: meta,
    fontSize: 40,
    height: 44 / 40,
    letterSpacing: -1.2,
    color: OracleColors.ink,
    fontVariations: [FontVariation('opsz', 72), FontVariation('wght', 300)],
  );

  /// 날짜 헤더 — Literata 15/20
  static const dateHeader = TextStyle(
    fontFamily: meta,
    fontSize: 15,
    height: 20 / 15,
    color: OracleColors.ink,
    fontVariations: [FontVariation('opsz', 12), FontVariation('wght', 300)],
  );
}

abstract final class OracleSpace {
  static const screenH = 24.0;   // 화면 좌우
  static const rail = 56.0;      // 스파인 레일 폭
  static const gutter = 16.0;    // 레일-본문 거터 = 방주 들여쓰기
  static const inPhoto = 8.0;    // 사진→캡션
  static const inBlock = 12.0;   // 본문→방주, 방주→리액션
  static const entry = 40.0;     // 엔트리 사이 (= 본문 행간 20×2)
  static const section = 32.0;   // 다이제스트 모듈 사이
}

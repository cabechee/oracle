/// 수집(신호·위치)은 별도 네이티브 수집기 앱(studio.camembertcheese.oracle.collector)이 전담한다.
/// Flutter 앱은 능동 인터페이스(채팅·카메라·타임라인·큐레이션·장소 등록 UI)만 — 수집 안 함.
///
/// 되돌리려면 true (수집기 미설치 폰에서 Flutter가 직접 수집하던 옛 동작). const 아님 — 분기
/// dead_code 린트 회피 + 런타임 토글 여지.
bool flutterCollects = false;

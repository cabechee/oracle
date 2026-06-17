# 두 기기 역할 분리 아키텍처 (2026-06-17~)

안드로이드/아이폰 두 폰을 같이 들고 다니는 전제. iOS 샌드박싱으로 수동 수집(푸시
알림·문자·통화)이 불가능하므로, **수집(Android)** 과 **인터페이스(공통)** 를 분리한다.

```
                    ┌──────────────────────────────┐
                    │   백엔드 (chocolat, FastAPI)   │  ← 단일 진실원
                    │   Mongo · vault · LLM(Nest)   │
                    └──────────────────────────────┘
        push ▲                ▲ push/read              ▲ read
             │                │                        │
   ┌─────────────────┐  ┌──────────────────────┐  ┌─────────┐
   │ Oracle 수집기    │  │ Flutter "Oracle" 앱    │  │   웹     │
   │ (Android 네이티브)│  │ (Android · iOS · web)  │  │(Flutter)│
   │ = passive        │  │ = active interface     │  └─────────┘
   │ 노티·문자·통화    │  │ 채팅·카메라·타임라인·   │
   │ ·GPS(v2) → push  │  │ 데스크·장소·동반자 UI    │
   └─────────────────┘  └──────────────────────┘
```

## 왜 이렇게
- **iOS 한계**: NotificationListener 없음·SMS/통화 접근 차단·백그라운드 상시실행 제약.
  → 수동 수집은 Android만 가능. iPhone은 카메라/사진/건강/위치 정도.
- **수집기를 네이티브 별도 앱으로**: Flutter 백그라운드 isolate는 OEM 배터리 최적화에
  취약. 네이티브 포그라운드 서비스가 더 안정적. Flutter 앱 업데이트와도 독립.
- **Flutter는 능동 인터페이스에 집중**: 한 코드베이스로 Android·iOS·web 공유. 수집
  모듈만 `Platform.isAndroid`로 분기(iOS·web은 수집 off).

## 현재 상태 (2026-06-17)
- **수집기**(`collector/`): v1 = 노티·문자·통화 → `/signals/sync`(source 태깅). 빌드 검증
  완료(컴파일·APK 생성). 디바이스 실행은 미검증. 상세 = `collector/README.md`.
- **백엔드**: `/signals/sync`에 `source`(provenance) 수용·기록. 배포됨.
- **Flutter 앱**: 수동 수집(`signals_sync`·위치 포그라운드)을 `Platform.isAndroid`로 가드
  → iOS는 능동 인터페이스만. iOS 프로젝트 스캐폴드(`ios/`)+권한 문구(Info.plist) 추가.

## 남은 일
1. **iOS 빌드/서명**: Apple 개발자 계정($99/년) 등록 후 Xcode 빌드(7일 만료 회피).
   `flutter build ipa` 또는 Xcode 직접. *코드/프로젝트는 준비됨, 빌드는 계정 필요.*
2. **수집기 v2**: GPS 체류 감지·WiFi/BT 장소 인식을 Flutter `location_task_handler`에서
   네이티브로 이전. `location` FGS 타입으로 Android 15 dataSync 제한 회피.
3. **수집 단일화**: 수집기 검증 후 Flutter 앱의 Android 수집 비활성(중복 제거).
4. **시간 동기화/충돌 규칙**: 두 기기 이벤트를 한 타임라인에 합칠 때 더 정확한/최근 fix
   우선. `source`로 어느 기기에서 온 기록인지 구분.

# Oracle 수집기 (Android 네이티브)

아이폰이 못 하는 **수동 수집**(문자·통화·앱 알림, 추후 GPS)을 전담하는 별도 Android 앱.
Flutter 엔진에 의존하지 않는 순수 네이티브 포그라운드 서비스 — 삼성 등 공격적 배터리
최적화에도 안정적으로 상시 동작하게 하려는 설계. 모은 데이터는 기존 백엔드
`/signals/sync`로 push(폰 Flutter 앱과 같은 엔드포인트 + `source` 태깅).

## 역할 분리 (전체 그림)
- **수집기(이 앱, Android)** = passive collector. 백그라운드로 알아서 긁어모음.
- **Flutter "Oracle" 앱(Android·iOS·web)** = active interface. 채팅·카메라·타임라인·큐레이션.
- **백엔드(chocolat)** = 단일 진실원. 양쪽이 push/read.

## 구성
- `MainActivity` — 최소 제어 UI(백엔드 주소·권한·시작/중지·즉시 전송 테스트·상태).
- `CollectorService` — 포그라운드 서비스. 주기(기본 30분)로 `syncOnce` 실행.
- `NotificationCollector` — `NotificationListenerService`. 앱 알림을 버퍼에 적재(상시).
- `Collectors` — 미읽음 SMS · 부재중 통화 쿼리.
- `Backend` — `/signals/sync`로 POST(HttpURLConnection + org.json, 외부 의존성 0).
- `Prefs` — 설정·알림 버퍼. `BootReceiver` — 부팅 시 자동 시작.

## 빌드
```sh
cd collector
JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home \
  ./gradlew :app:assembleDebug
# → app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## 폰 설정 (설치 후)
1. 앱 열고 **백엔드 주소** 확인/저장(기본 `http://chocolat.tail575fea.ts.net:8001`).
2. **권한 요청**(문자·통화·알림) 허용.
3. **알림 접근 설정 열기** → Oracle 수집기 ON (앱 알림 수집에 필요).
4. **배터리 최적화 제외** 허용(상시 동작).
5. **수집 시작**. "지금 한 번 보내기"로 즉시 검증.

## 알아둘 점
- `source` = 기기별 자동 id(`android-collector-xxxx`) — 신호 provenance로 백엔드에 기록.
- ⚠️ Android 15+는 `dataSync` 포그라운드 서비스에 일일 누적 실행 제한이 있음.
  GPS 수집(v2) 추가 시 `location` 타입을 병행하면 제한을 피할 수 있음.
- 현재 폰 Flutter 앱도 같은 수집을 하고 있음(Android). 백엔드가 dedupe하므로 중복은
  무해하나, 수집기 검증 후 Flutter 쪽 수집을 끄는 게 깔끔(아래 "남은 일").

## 남은 일
- v2: GPS 수집(체류 감지·WiFi/BT 장소)을 Flutter `location_task_handler`에서 네이티브로 이전.
- 검증 후 Flutter 앱의 `signals_sync`·위치 포그라운드 비활성(수집기 단일화).
- 릴리스 서명 키(현재 디버그 키).

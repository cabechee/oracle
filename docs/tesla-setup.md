# Tesla Fleet API 연동 — 설정 체크리스트

차 상태머신(출차/주차)을 BT/GPS 추측 대신 **실제 차량 위치·운행 데이터**로 보강하기 위한 연동.
읽기 전용(vehicle_data)으로 시작. 원격 명령은 후속(차량 명령 프로토콜 + 개인키 서명).

## 구성요소

| 무엇 | 어디 | 상태 |
|---|---|---|
| EC 키 쌍(P-256) | 개인키 `tesla-private-key.pem`(repo 루트, **gitignore**) · 공개키 `deploy/oraclecar-pages/.well-known/appspecific/com.tesla.3p.public-key.pem`(공개, 커밋 OK) | ✅ 생성됨 |
| 공개키 호스팅 | ✅ 배포됨 → `https://oraclecar.pages.dev` (06-20, 공개키 라이브 검증·폼 통과) | ✅ |
| 백엔드 모듈 | `backend/tesla.py` (graceful, 읽기 전용) | ✅ |
| 일회 인증 | `scripts/tesla_auth.py` (authorization_code) | ✅ |
| 파트너 등록 | `scripts/tesla_register.py` (도메인+공개키) | ✅ |
| 설정(env) | `backend/config.py` `TESLA_*` | ✅ |

## 순서

### 1. developer.tesla.com 앱 폼
- OAuth 부여 유형: **인증 코드 및 사물 통신**
- 허용 출처 URL: `https://oraclecar.pages.dev`
- 허용 리디렉션 URI: `http://localhost:8080/callback`
- 허용 반환 URL: 비움
- 다음 단계 scope: `vehicle_device_data` · `vehicle_location` (명령 원하면 `vehicle_cmds` 추가)
- 완료 후 **client_id · client_secret** 발급 → `.env`에:
  ```
  TESLA_CLIENT_ID=...
  TESLA_CLIENT_SECRET=...
  ```

### 2. Cloudflare Pages로 공개키 호스팅 — ✅ 완료(06-20)
```bash
# wrangler login 후
npx wrangler pages deploy deploy/oraclecar-pages --project-name oraclecar --branch main
```
→ 기본 도메인 **`oraclecar.pages.dev`** 즉시 라이브(공개키 라이브 검증 완료, 테슬라 폼 통과).
별도 서버·DNS 불필요 — CF 엣지가 24/7 무료 서빙. (자체 도메인 원하면 대시보드 Custom domains에서 추가 — 선택.)
검증: `curl https://oraclecar.pages.dev/.well-known/appspecific/com.tesla.3p.public-key.pem`

**보안**: 이 URL은 공개돼도 안전 — **공개키만** 노출(원래 공개용, 테슬라가 fetch). 개인키·client_secret·토큰은
전부 repo 밖/gitignore라 여기 없음. 공개키론 차량 접근·서명 위조 불가.

### 3. 파트너 등록 (공개키 호스팅 후 1회)
```bash
cd backend && .venv/bin/python ../scripts/tesla_register.py
```

### 4. 사용자 OAuth (1회)
```bash
cd backend && .venv/bin/python ../scripts/tesla_auth.py
# 브라우저 동의 → tesla_token.json 생성
# chocolat이면 tesla_token.json 을 chocolat:~/projects/oracle/ 로 복사
```

### 5. 동작 확인
```python
import tesla
tesla.status()        # {authed, vehicles:[...]}
tesla.location()      # {lat, lng, shift, driving, ...}
```

## 지역 베이스 (중요)
한국=아태권은 **NA 엔드포인트**(`fleet-api.prd.na.vn.cloud.tesla.com`, 기본값).
EU/중국이면 `.env`에서 `TESLA_API_BASE` 교체.

## 다음(차 상태머신 보강)
인증 동작 후, `agent/companion.py`의 `car_departure`/`car_parking`에서 `tesla.location()`을 호출해
- 출차 시: 실제 목적지·운행 상태로 "어디 가?"를 더 정확히 / 안전망 대체
- 주차 시: 차의 실제 GPS로 주차 위치 정밀화

⚠️ `vehicle_data`를 자주 부르면 차를 깨워 배터리 소모 — **이벤트 시점에만** 호출. (BT/GPS가 1차, 테슬라는 확인·보강용.)

## 보안
- 개인키·`tesla_token.json` 은 **gitignore**(public repo 유출 방지). 공개키만 커밋.
- client_secret 은 `.env`(gitignore)에만.

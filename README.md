# 🪪 우주 출생 증명서 (Space Birth Certificate)

생년월일을 입력하면 NASA·JPL·GFZ의 공개 데이터로 "우주가 기록한 나의 탄생" 증명서를 만들어 주는 앱입니다.
API 키는 필요 없습니다.

## 실행 방법

1. `run.bat`을 더블클릭합니다. 터미널에서 `python server.py`로 실행해도 됩니다.
2. 브라우저가 `http://127.0.0.1:8765/`로 자동으로 열립니다.
3. 이름(선택)과 생년월일을 넣고 **증명서 발급**을 누릅니다.
4. 종료하려면 서버 창에서 `Ctrl+C`를 누르거나 창을 닫습니다.

> `index.html`을 더블클릭해서 바로 열면 동작하지 않습니다.
> NASA·GFZ API가 브라우저의 직접 호출(CORS)을 허용하지 않기 때문에, `server.py`가 요청을 대신 전달해야 합니다.

준비물: Python 3.8 이상. 표준 라이브러리만 쓰므로 `pip install`은 필요 없습니다.

## 증명서 구성

| 섹션 | 내용 | 데이터 |
|---|---|---|
| ☄️ 나의 수호 소행성 | 태어난 날 지구에 가장 가까이 온 소행성의 거리, 속도, 크기, 궤도 분류, 다음 방문일 + 궤도 그림, 실제 NASA 사진(있을 때만) 또는 크기 비교 그림, JPL 3D 궤도 뷰어 링크 | NASA/JPL SBDB Close-Approach API, SBDB API, NASA Image and Video Library |
| 🪐 나의 빛이 닿은 행성 | 태어난 순간 출발한 빛이 지금 도착하는 외계행성, 지금까지 지나온 행성 수, 다음 도착 예정 행성 | NASA Exoplanet Archive TAP (`pscomppars`) |
| ☀️ 우주 날씨 기록 | 태어난 날과 올해 생일의 Kp 지수(3시간 간격), 지자기 폭풍 등급, 흑점 수, F10.7, Ap. 생일이 아직 안 지났으면 지난 생일과 D-day 표시 | GFZ Potsdam Kp index web service (CC BY 4.0) |

## 파일

- `index.html`: 화면 (HTML, CSS, JS 한 파일)
- `server.py`: 로컬 서버이자 API 중계 (`/api/gfz`, `/api/cad`, `/api/cad_next`, `/api/sbdb`, `/api/images`, `/api/exoplanets`)
- `run.bat`: Windows 실행 스크립트
- `exoplanets_cache.json`: 첫 실행 때 자동 생성되는 외계행성 목록 캐시 (60 pc 이내, 30일마다 갱신)

## 참고와 문제 해결

- **조회 범위**: 생년월일은 1932-01-01 이후만 입력할 수 있습니다. GFZ Kp 데이터가 1932년부터 있기 때문입니다.
- **날짜 기준**: 각 API는 UTC 날짜를 기준으로 하루를 조회합니다. 소행성 최근접 시각은 한국 시각으로 바꿔 표시합니다.
- **포트 변경**: `set PORT=9000` 후 `python server.py`
- **연결 점검**: `python server.py --check`를 실행하면 API별 연결 상태와 사용 중인 TLS 모드를 보여줍니다.
- **인증서 오류(`CERTIFICATE_VERIFY_FAILED`)**: 회사망의 SSL 검사 때문에 Python이 서버 인증서를 신뢰하지 못하는 경우입니다. 검증을 끄지 않고 다음 순서로 처리합니다.
  1. `truststore` 패키지가 설치되어 있으면 Windows 인증서 저장소로 검증합니다. (`python -m pip install truststore`, 선택 사항)
  2. 이 폴더에 `ca-bundle.pem`(회사 루트 인증서)이 있으면 추가로 신뢰합니다.
  3. 그래도 실패하면 Windows 내장 `curl.exe`로 자동으로 다시 받습니다. `curl.exe`는 Windows 인증서 저장소를 사용합니다. 서버 창에 `curl 경로로 전환` 안내가 표시됩니다.
- **프록시 환경**: `HTTPS_PROXY` 환경 변수를 설정합니다.
- **이미지 저장**: 버튼을 누를 때 html2canvas를 CDN(jsdelivr)에서 불러옵니다. 실패하면 `인쇄 / PDF`를 사용하세요.

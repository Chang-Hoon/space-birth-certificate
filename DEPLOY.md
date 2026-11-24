# 🚀 GitHub Pages 배포 안내

구성은 다음과 같습니다.

```
[브라우저] ── GitHub Pages (index.html, config.js)
     │  fetch("https://<워커주소>/api/...")
     ▼
Cloudflare Worker (worker.js) ── GFZ / JPL / Exoplanet Archive / NASA Images
```

GitHub Pages는 정적 파일만 올려 주므로, `server.py`가 하던 API 중계는 Cloudflare Worker가 맡습니다.
작업 순서는 **① Worker 배포 → ② config.js 수정 → ③ GitHub Pages 배포**입니다.

---

## ① Cloudflare Worker 배포

먼저 Cloudflare 계정을 만듭니다(무료). 배포 방법은 둘 중 편한 것을 고르세요.

### 방법 1: 웹 대시보드 (설치 없음, 추천)

1. Cloudflare 대시보드에서 **Workers & Pages → Create → Worker**를 선택합니다.
   - 이름은 `space-birth-certificate`로 하고 기본 "Hello World"로 만듭니다.
2. **Edit code**를 누르고, 기본 코드를 모두 지운 뒤 `worker.js` 내용을 통째로 붙여 넣습니다.
3. **Deploy**를 누릅니다.
4. Worker의 **Settings → Variables and Secrets**에서 변수를 추가합니다.
   - 이름: `ALLOWED_ORIGINS`
   - 값: `https://<GitHub아이디>.github.io`
   - 저장소 이름 같은 경로는 붙이지 않습니다. 끝에 `/`도 넣지 않습니다.
5. (권장) **Settings → Observability**에서 로그를 꺼 둡니다. 생년월일이 요청 로그에 남지 않게 하기 위해서입니다.
6. Worker 주소를 기록해 둡니다. 형식은 `https://space-birth-certificate.<내서브도메인>.workers.dev`입니다.

### 방법 2: Wrangler CLI

```bash
npm install -g wrangler
wrangler login                 # 브라우저에서 Cloudflare 로그인
# wrangler.toml 의 ALLOWED_ORIGINS 를 내 GitHub Pages 주소로 수정한 뒤
wrangler deploy                # 끝나면 workers.dev 주소가 출력됨
```

`wrangler.toml`에는 로그 끄기(`[observability] enabled = false`)가 이미 들어 있습니다.

> 회사망에서는 SSL 검사 때문에 `wrangler` 설치나 로그인이 실패할 수 있습니다. 그럴 땐 방법 1을 쓰거나 집 PC에서 진행하세요.

### 동작 확인

브라우저 주소창에 아래 주소를 직접 열어 JSON이 보이면 성공입니다.

```
https://<워커주소>/api/gfz?date=2025-03-14
```

---

## ② config.js 수정

`config.js`의 값을 ①에서 기록한 Worker 주소로 바꿉니다.

```js
window.SBC_API_BASE = "https://space-birth-certificate.<내서브도메인>.workers.dev";
```

로컬 실행(`run.bat`)은 이 값과 상관없이 계속 로컬 서버를 사용하므로, 바꿔도 로컬에는 영향이 없습니다.

---

## ③ GitHub Pages 배포

1. GitHub에서 새 저장소를 만듭니다. 예: `space-birth-certificate`
   - 무료 계정에서는 **Public** 저장소여야 Pages를 쓸 수 있습니다.
2. 이 폴더의 파일을 올립니다.
   - 최소 필요 파일은 `index.html`과 `config.js`입니다.
   - 나머지 파일(server.py, worker.js 등)도 같이 올려도 됩니다.
   - `.gitignore`에 따라 캐시 파일은 올라가지 않습니다.
   ```bash
   cd "D:\Z\Space Biorth Certificate"
   git init
   git add .
   git commit -m "Space Birth Certificate"
   git branch -M main
   git remote add origin https://github.com/<아이디>/space-birth-certificate.git
   git push -u origin main
   ```
3. 저장소의 **Settings → Pages**로 이동합니다.
   - Source: **Deploy from a branch**
   - Branch: `main`, 폴더: `/ (root)`
   - **Save**를 누릅니다.
4. 1~2분 뒤 `https://<아이디>.github.io/space-birth-certificate/`에 접속해 증명서를 발급해 봅니다.

---

## 문제 해결

| 증상 | 원인 / 해결 |
|---|---|
| "API 주소가 설정되지 않았습니다" | `config.js`의 `SBC_API_BASE`가 비어 있습니다. 값을 넣고 다시 push 하세요. |
| "API 서버(Cloudflare Worker)에 연결할 수 없습니다" | Worker 주소 오타이거나 `ALLOWED_ORIGINS`가 Pages 주소와 다릅니다. Origin은 `https://아이디.github.io` 형식이며, 경로나 끝의 `/` 없이 정확히 일치해야 합니다. |
| 403 "허용되지 않은 사이트에서의 요청" | 위와 같이 `ALLOWED_ORIGINS`를 확인하세요. 수정 후 Worker를 다시 배포해야 합니다. |
| Error 1027 | Cloudflare 무료 플랜의 하루 요청 한도(100,000회)를 넘었습니다. UTC 자정(한국 시각 오전 9시)에 초기화됩니다. |
| config.js를 고쳤는데 반영이 안 됨 | GitHub Pages 캐시 때문입니다. 몇 분 기다리거나 브라우저에서 강력 새로고침(Ctrl+F5)을 하세요. |
| 외계행성 섹션이 처음에 느림 | 목록(수백 KB)을 처음 받는 중입니다. 이후에는 Cloudflare 캐시에서 빠르게 나옵니다. |

## 개인정보

- 생년월일과 이름은 브라우저에서 Worker로 조회 요청에만 쓰입니다. Worker는 이를 저장하지 않습니다.
- 이름은 화면 표시에만 쓰이고 Worker로 전송되지 않습니다.
- Worker 로그를 꺼 두면 요청 내용이 기록되지 않습니다.
- 마지막 입력값은 사용자 본인 브라우저(localStorage)에만 저장됩니다.

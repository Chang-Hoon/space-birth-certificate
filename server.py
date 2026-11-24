#!/usr/bin/env python3
"""
우주 출생 증명서 (Space Birth Certificate) - 로컬 서버

- index.html 을 제공하고, 브라우저 CORS 제한을 피하기 위해 아래 공개 API를 대신 호출합니다.
  * GFZ Potsdam Kp/Ap/SN/F10.7 지수   https://kp.gfz.de/app/json/
  * NASA/JPL SBDB Close-Approach API   https://ssd-api.jpl.nasa.gov/cad.api
  * NASA/JPL SBDB API                  https://ssd-api.jpl.nasa.gov/sbdb.api
  * NASA Exoplanet Archive TAP         https://exoplanetarchive.ipac.caltech.edu/TAP/sync
- API 키가 필요 없습니다. Python 3.8+ 표준 라이브러리만 사용합니다.

실행:  python server.py        (브라우저가 자동으로 열립니다)
옵션:  python server.py --no-browser
       set PORT=9000  (포트 변경)
"""
import datetime as dt
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8765"))
HOST = "127.0.0.1"
UA = "SpaceBirthCertificate/1.0 (personal toy project; python-urllib)"

GFZ_URL = "https://kp.gfz.de/app/json/"
CAD_URL = "https://ssd-api.jpl.nasa.gov/cad.api"
SBDB_URL = "https://ssd-api.jpl.nasa.gov/sbdb.api"
TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"

EXO_CACHE_FILE = os.path.join(BASE_DIR, "exoplanets_cache.json")
EXO_CACHE_DAYS = 30
EXO_QUERY = (
    "select pl_name,hostname,sy_dist,disc_year,discoverymethod,"
    "pl_rade,pl_bmasse,pl_orbper,pl_eqt from pscomppars "
    "where sy_dist<60 order by sy_dist"
)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_cache = {}
_lock = threading.Lock()


class UpstreamError(Exception):
    pass


# ---------------------------------------------------------------- TLS
# 회사망의 SSL 검사(사내 루트 인증서)나 중간 인증서를 보내지 않는 서버 때문에
# Python 기본 인증서 목록으로는 검증에 실패할 수 있습니다. 검증은 끄지 않고 다음 순서로 대응합니다.
#   1) truststore 패키지가 설치되어 있으면 Windows 인증서 저장소로 검증 (pip install truststore)
#   2) 이 폴더에 ca-bundle.pem 이 있으면 추가 신뢰 인증서로 사용
#   3) 그래도 인증서 검증에 실패하면 Windows 내장 curl.exe(Windows 인증서 저장소 사용)로 재시도
CA_BUNDLE_FILE = os.path.join(BASE_DIR, "ca-bundle.pem")
CURL_EXE = shutil.which("curl.exe") or shutil.which("curl")
_curl_hosts = set()  # Python 검증에 실패해 curl로 받는 호스트


def _make_ssl_context():
    try:
        import truststore  # type: ignore
        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        mode = "truststore (OS 인증서 저장소)"
    except Exception:  # noqa: BLE001
        ctx = ssl.create_default_context()
        mode = "Python 기본 인증서"
    if os.path.exists(CA_BUNDLE_FILE):
        try:
            ctx.load_verify_locations(cafile=CA_BUNDLE_FILE)
            mode += " + ca-bundle.pem"
        except (ssl.SSLError, OSError) as e:
            print(f"[경고] ca-bundle.pem 을 읽지 못했습니다: {e}")
    return ctx, mode


SSL_CTX, SSL_MODE = _make_ssl_context()


def _is_cert_error(err):
    reason = getattr(err, "reason", err)
    return isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(reason)


def _curl_get(url, timeout):
    host = urllib.parse.urlsplit(url).netloc
    if not CURL_EXE:
        raise UpstreamError(f"{host} 인증서 검증 실패, 대체 경로(curl)도 없습니다. README의 '인증서 오류' 항목을 참고하세요.")
    base = [CURL_EXE, "-sS", "--fail", "-L", "-m", str(timeout), "-A", UA, "-H", "Accept: application/json"]
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    attempts = [base + ["--ssl-revoke-best-effort", url], base + [url]] if sys.platform == "win32" else [base + [url]]
    last = ""
    for cmd in attempts:
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=timeout + 10, creationflags=flags)
        except subprocess.TimeoutExpired as e:
            raise UpstreamError(f"{host} 응답 시간 초과 (curl)") from e
        if p.returncode == 0:
            return p.stdout.decode("utf-8")
        last = p.stderr.decode("utf-8", "replace").strip()
        if p.returncode != 2:  # 2 = 알 수 없는 옵션(오래된 curl) → 옵션 없이 재시도
            break
    raise UpstreamError(f"{host} 연결 실패 (curl): {last}")


def _http_get(url, timeout):
    host = urllib.parse.urlsplit(url).netloc
    if host in _curl_hosts:
        return _curl_get(url, timeout)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise UpstreamError(f"{host} 응답 오류 HTTP {e.code}") from e
    except (urllib.error.URLError, ssl.SSLError) as e:
        if _is_cert_error(e):
            raw = _curl_get(url, timeout)  # 실패하면 UpstreamError
            _curl_hosts.add(host)
            print(f"  [안내] {host}: Python 인증서 검증 실패 → Windows curl 경로로 전환")
            return raw
        raise UpstreamError(f"{host} 연결 실패: {getattr(e, 'reason', e)}") from e
    except TimeoutError as e:
        raise UpstreamError(f"{host} 응답 시간 초과") from e


def fetch_json(url, ttl=3600, timeout=40):
    """URL에서 JSON을 받아오고 메모리에 ttl초 동안 캐시합니다."""
    now = time.time()
    with _lock:
        hit = _cache.get(url)
        if hit and now - hit[0] < ttl:
            return hit[1]
    raw = _http_get(url, timeout)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise UpstreamError(f"{urllib.parse.urlsplit(url).netloc} 가 JSON이 아닌 응답을 보냈습니다") from e
    with _lock:
        _cache[url] = (now, data)
    return data


def check_date(value):
    if not value or not DATE_RE.match(value):
        raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다")
    dt.date.fromisoformat(value)  # 존재하지 않는 날짜면 ValueError
    return value


# ---------------------------------------------------------------- GFZ
def gfz_day(date):
    """하루치 Kp(3시간 간격 8개), Ap, 흑점 수(SN), F10.7(Fobs)."""
    start, end = f"{date}T00:00:00Z", f"{date}T23:59:59Z"
    out = {"date": date, "Kp": [], "Kp_time": [], "Kp_status": [], "Ap": [], "SN": [], "Fobs": []}
    errors = {}
    for index in ("Kp", "Ap", "SN", "Fobs"):
        url = GFZ_URL + "?" + urllib.parse.urlencode({"start": start, "end": end, "index": index})
        try:
            d = fetch_json(url, ttl=6 * 3600)
        except UpstreamError as e:
            errors[index] = str(e)
            continue
        out[index] = d.get(index, []) or []
        if index == "Kp":
            out["Kp_time"] = d.get("datetime", []) or []
            out["Kp_status"] = d.get("status", []) or []
    if errors:
        out["errors"] = errors
    if len(errors) == 4:
        raise UpstreamError("GFZ 데이터를 하나도 받지 못했습니다: " + "; ".join(sorted(set(errors.values()))))
    return out


# ---------------------------------------------------------------- JPL CAD / SBDB
def cad_birth(date):
    """생일 하루 동안 지구에 가장 가까이 온 천체 목록. 없으면 거리 조건을 넓혀 재시도."""
    for dist_max in ("0.05", "0.2", "0.5"):
        qs = urllib.parse.urlencode({
            "date-min": date,
            "date-max": f"{date}T23:59:59",
            "dist-max": dist_max,
            "sort": "dist",
            "diameter": "true",
            "fullname": "true",
        })
        d = fetch_json(f"{CAD_URL}?{qs}", ttl=30 * 86400)
        if int(d.get("count", 0)) > 0:
            return {"distMax": float(dist_max), "fields": d["fields"], "data": d["data"]}
    return {"distMax": 0.5, "fields": [], "data": []}


def cad_next(des, from_date):
    qs = urllib.parse.urlencode({
        "des": des,
        "date-min": from_date,
        "date-max": "2200-01-01",
        "dist-max": "0.2",
        "limit": "1",
    })
    d = fetch_json(f"{CAD_URL}?{qs}", ttl=86400)
    if int(d.get("count", 0)) == 0:
        return {"found": False}
    row = dict(zip(d["fields"], d["data"][0]))
    return {"found": True, "cd": row.get("cd"), "dist": row.get("dist")}


def sbdb_object(des):
    d = fetch_json(f"{SBDB_URL}?{urllib.parse.urlencode({'sstr': des})}", ttl=30 * 86400)
    obj = d.get("object") or {}
    orbit = d.get("orbit") or {}
    elements = {}
    for el in orbit.get("elements") or []:
        try:
            elements[el.get("name")] = float(el.get("value"))
        except (TypeError, ValueError):
            pass
    try:
        epoch = float(orbit.get("epoch"))
    except (TypeError, ValueError):
        epoch = None
    return {
        "fullname": obj.get("fullname"),
        "neo": obj.get("neo"),
        "pha": obj.get("pha"),
        "kind": obj.get("kind"),
        "orbit_class": (obj.get("orbit_class") or {}),
        "orbit": {"epoch": epoch, **elements},  # a, e, i, om, w, ma, n, q, ad, per ...
    }


# ---------------------------------------------------------------- NASA Image and Video Library
IMAGES_URL = "https://images-api.nasa.gov/search"
ASTEROID_HINT_RE = re.compile(
    r"\b(asteroids?|near shoemaker|near spacecraft|osiris-rex|osiris-apex|hayabusa2?|dart|dawn|lucy|psyche|"
    r"goldstone|arecibo|neowise|planetary radar)\b", re.IGNORECASE)


def nasa_images(term):
    """소행성 이름/임시 번호로 NASA 이미지를 찾되, 그 천체가 확실히 언급된 소행성 관련 이미지만 남깁니다."""
    qs = urllib.parse.urlencode({"q": term, "media_type": "image"})
    d = fetch_json(f"{IMAGES_URL}?{qs}", ttl=7 * 86400)
    word = re.compile(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])", re.IGNORECASE)
    phrase = re.compile(r"\basteroids?\s+(?:\d+\s+)?" + re.escape(term) + r"(?![\w-])|(?<![\w-])"
                        + re.escape(term) + r"\s+asteroid\b", re.IGNORECASE)
    picked, seen = [], set()
    for it in (d.get("collection") or {}).get("items") or []:
        data = (it.get("data") or [{}])[0]
        title = data.get("title") or ""
        keywords = [k for k in (data.get("keywords") or []) if isinstance(k, str)]
        desc = data.get("description") or ""
        named = word.search(title) or any(word.search(k) for k in keywords)
        if not named:
            continue
        # 소행성 관련 표시가 제목·키워드에 있거나, 설명에 "asteroid <이름>" 형태로 언급돼야 함
        if not (ASTEROID_HINT_RE.search(" | ".join([title, *keywords])) or phrase.search(desc)):
            continue
        thumb = next((l.get("href") for l in (it.get("links") or []) if l.get("render") == "image"), None)
        if not thumb or title in seen:
            continue
        seen.add(title)
        picked.append({
            "title": title,
            "nasa_id": data.get("nasa_id"),
            "thumb": thumb,
            "date": (data.get("date_created") or "")[:10],
            "center": data.get("center"),
            "in_title": bool(word.search(title)),
        })
    picked.sort(key=lambda p: p["date"], reverse=True)      # 최신순
    picked.sort(key=lambda p: not p["in_title"])            # 제목에 이름이 있는 것 우선 (안정 정렬)
    return {"term": term, "total": len(picked), "items": picked[:4]}


# ---------------------------------------------------------------- Exoplanets
def exoplanets():
    """60 pc(약 196광년) 이내 외계행성 목록. 디스크에 30일 캐시."""
    if os.path.exists(EXO_CACHE_FILE):
        age_days = (time.time() - os.path.getmtime(EXO_CACHE_FILE)) / 86400
        if age_days < EXO_CACHE_DAYS:
            with open(EXO_CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
    url = TAP_URL + "?" + urllib.parse.urlencode({"query": EXO_QUERY, "format": "json"})
    try:
        data = fetch_json(url, ttl=86400, timeout=90)
    except UpstreamError:
        if os.path.exists(EXO_CACHE_FILE):  # 오래된 캐시라도 사용
            with open(EXO_CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
        raise
    payload = {"fetched": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "planets": data}
    try:
        with open(EXO_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except OSError:
        pass
    return payload


# ---------------------------------------------------------------- HTTP
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def log_message(self, fmt, *args):  # 조용히
        if "/api/" in (self.path or ""):
            sys.stderr.write("  %s\n" % (fmt % args))

    def send_json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parts = urllib.parse.urlsplit(self.path)
        if not parts.path.startswith("/api/"):
            if parts.path in ("/server.py", "/run.bat"):
                self.send_error(404)
                return
            return super().do_GET()
        q = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}
        try:
            if parts.path == "/api/gfz":
                result = gfz_day(check_date(q.get("date")))
            elif parts.path == "/api/cad":
                result = cad_birth(check_date(q.get("date")))
            elif parts.path == "/api/cad_next":
                des = (q.get("des") or "").strip()
                if not des or len(des) > 40:
                    raise ValueError("des 값이 필요합니다")
                result = cad_next(des, check_date(q.get("from")))
            elif parts.path == "/api/sbdb":
                des = (q.get("des") or "").strip()
                if not des or len(des) > 40:
                    raise ValueError("des 값이 필요합니다")
                result = sbdb_object(des)
            elif parts.path == "/api/images":
                term = (q.get("term") or "").strip()
                if not term or len(term) > 40:
                    raise ValueError("term 값이 필요합니다")
                result = nasa_images(term)
            elif parts.path == "/api/exoplanets":
                result = exoplanets()
            else:
                self.send_json(404, {"error": "알 수 없는 API 경로"})
                return
        except ValueError as e:
            self.send_json(400, {"error": str(e)})
            return
        except UpstreamError as e:
            self.send_json(502, {"error": str(e)})
            return
        except Exception as e:  # noqa: BLE001
            self.send_json(500, {"error": f"서버 내부 오류: {e}"})
            return
        self.send_json(200, result)


def check_connections():
    """python server.py --check : 각 API 연결 상태 점검."""
    tests = {
        "GFZ Kp": GFZ_URL + "?start=2025-03-14T00:00:00Z&end=2025-03-14T23:59:59Z&index=Kp",
        "JPL CAD": CAD_URL + "?date-min=2025-03-14&date-max=2025-03-14T23:59:59&dist-max=0.05",
        "JPL SBDB": SBDB_URL + "?sstr=Eros",
        "Exoplanet TAP": TAP_URL + "?query=select+count(*)+as+n+from+pscomppars&format=json",
        "NASA Images": IMAGES_URL + "?q=Eros&media_type=image",
    }
    print(f"TLS 모드: {SSL_MODE} / curl: {CURL_EXE or '없음'}")
    ok = True
    for name, url in tests.items():
        try:
            fetch_json(url, ttl=0)
            via = " (curl 경로)" if urllib.parse.urlsplit(url).netloc in _curl_hosts else ""
            print(f"  [OK]   {name}{via}")
        except UpstreamError as e:
            ok = False
            print(f"  [실패] {name}: {e}")
    return ok


def main():
    if "--check" in sys.argv:
        sys.exit(0 if check_connections() else 1)
    open_browser = "--no-browser" not in sys.argv
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as e:
        print(f"[오류] 포트 {PORT}를 열 수 없습니다 ({e}). 이미 실행 중이거나 다른 프로그램이 사용 중입니다.")
        print("       다른 포트로 실행하려면:  set PORT=9000  후 다시 실행")
        sys.exit(1)
    url = f"http://{HOST}:{PORT}/"
    print("=" * 56)
    print("  우주 출생 증명서 서버 실행 중")
    print(f"  주소: {url}")
    print("  종료: 이 창에서 Ctrl+C")
    print(f"  TLS: {SSL_MODE} (실패 시 curl: {'사용 가능' if CURL_EXE else '없음'})")
    print("=" * 56)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

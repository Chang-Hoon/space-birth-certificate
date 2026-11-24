/**
 * 우주 출생 증명서 - Cloudflare Worker (API 중계)
 *
 * GitHub Pages에 올린 index.html 이 호출하는 /api/* 를 처리합니다.
 * server.py 의 /api 라우트와 같은 응답 형식을 돌려줍니다.
 *
 *   /api/gfz?date=YYYY-MM-DD           GFZ Kp(8개)·Ap·흑점 수(SN)·F10.7(Fobs)
 *   /api/cad?date=YYYY-MM-DD           그날 지구에 가장 가까이 온 천체 (0.05 → 0.2 → 0.5 au)
 *   /api/cad_next?des=...&from=DATE    다음 근접 일자
 *   /api/sbdb?des=...                  궤도 분류·위험 여부·궤도 요소
 *   /api/images?term=...               NASA 이미지 보관소 (소행성 관련 이미지만)
 *   /api/exoplanets                    60 pc 이내 외계행성 목록
 *
 * 환경 변수 (wrangler.toml [vars]):
 *   ALLOWED_ORIGINS  쉼표로 구분한 허용 Origin. 예: "https://myid.github.io"
 *                    (http://127.0.0.1:8765 / http://localhost:8765 는 테스트용으로 항상 허용)
 *
 * 개인정보: 요청 내용(생년월일)을 저장하거나 로그로 남기지 않습니다.
 */

const UA = "SpaceBirthCertificate/1.0 (personal toy project; Cloudflare Worker)";
const GFZ_URL = "https://kp.gfz.de/app/json/";
const CAD_URL = "https://ssd-api.jpl.nasa.gov/cad.api";
const SBDB_URL = "https://ssd-api.jpl.nasa.gov/sbdb.api";
const TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync";
const IMAGES_URL = "https://images-api.nasa.gov/search";
const EXO_QUERY =
  "select pl_name,hostname,sy_dist,disc_year,discoverymethod," +
  "pl_rade,pl_bmasse,pl_orbper,pl_eqt from pscomppars where sy_dist<60 order by sy_dist";
const LOCAL_ORIGINS = ["http://127.0.0.1:8765", "http://localhost:8765"];
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const DAY = 86400;

class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

// ------------------------------------------------------------------ helpers
// 같은 Worker 인스턴스 안에서만 유지되는 간단한 메모리 캐시 (보조용)
const memo = new Map();
const MEMO_MAX = 300;

async function upstreamText(url, ttl, timeoutMs = 30000) {
  const hit = memo.get(url);
  if (hit && Date.now() - hit.t < ttl * 1000) return hit.v;
  const host = new URL(url).host;
  let res;
  try {
    res = await fetch(url, {
      headers: { "User-Agent": UA, "Accept": "application/json" },
      cf: { cacheTtl: ttl, cacheEverything: true },
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (e) {
    throw new HttpError(502, `${host} 연결 실패: ${e && e.name === "TimeoutError" ? "응답 시간 초과" : (e && e.message) || e}`);
  }
  if (!res.ok) throw new HttpError(502, `${host} 응답 오류 HTTP ${res.status}`);
  const text = await res.text();
  if (memo.size >= MEMO_MAX) memo.delete(memo.keys().next().value);
  memo.set(url, { t: Date.now(), v: text });
  return text;
}

async function upstreamJson(url, ttl, timeoutMs) {
  const text = await upstreamText(url, ttl, timeoutMs);
  try { return JSON.parse(text); }
  catch { throw new HttpError(502, `${new URL(url).host} 가 JSON이 아닌 응답을 보냈습니다`); }
}

function qs(params) { return new URLSearchParams(params).toString(); }

function checkDate(v) {
  if (!v || !DATE_RE.test(v)) throw new HttpError(400, "날짜는 YYYY-MM-DD 형식이어야 합니다");
  const [y, m, d] = v.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d));
  if (t.getUTCFullYear() !== y || t.getUTCMonth() !== m - 1 || t.getUTCDate() !== d) {
    throw new HttpError(400, "존재하지 않는 날짜입니다");
  }
  return v;
}

function checkText(v, name) {
  v = (v || "").trim();
  if (!v || v.length > 40) throw new HttpError(400, `${name} 값이 필요합니다`);
  return v;
}

const escapeRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// ------------------------------------------------------------------ routes
async function gfzDay(date) {
  const start = `${date}T00:00:00Z`, end = `${date}T23:59:59Z`;
  const out = { date, Kp: [], Kp_time: [], Kp_status: [], Ap: [], SN: [], Fobs: [] };
  const errors = {};
  await Promise.all(["Kp", "Ap", "SN", "Fobs"].map(async index => {
    try {
      const d = await upstreamJson(`${GFZ_URL}?${qs({ start, end, index })}`, 6 * 3600);
      out[index] = d[index] || [];
      if (index === "Kp") { out.Kp_time = d.datetime || []; out.Kp_status = d.status || []; }
    } catch (e) { errors[index] = e.message; }
  }));
  const n = Object.keys(errors).length;
  if (n) out.errors = errors;
  if (n === 4) throw new HttpError(502, "GFZ 데이터를 하나도 받지 못했습니다: " + [...new Set(Object.values(errors))].join("; "));
  return out;
}

async function cadBirth(date) {
  for (const distMax of ["0.05", "0.2", "0.5"]) {
    const d = await upstreamJson(`${CAD_URL}?${qs({
      "date-min": date, "date-max": `${date}T23:59:59`, "dist-max": distMax,
      sort: "dist", diameter: "true", fullname: "true",
    })}`, 30 * DAY);
    if (Number(d.count || 0) > 0) return { distMax: Number(distMax), fields: d.fields, data: d.data };
  }
  return { distMax: 0.5, fields: [], data: [] };
}

async function cadNext(des, from) {
  const d = await upstreamJson(`${CAD_URL}?${qs({
    des, "date-min": from, "date-max": "2200-01-01", "dist-max": "0.2", limit: "1",
  })}`, DAY);
  if (Number(d.count || 0) === 0) return { found: false };
  const row = Object.fromEntries(d.fields.map((f, i) => [f, d.data[0][i]]));
  return { found: true, cd: row.cd, dist: row.dist };
}

async function sbdbObject(des) {
  const d = await upstreamJson(`${SBDB_URL}?${qs({ sstr: des })}`, 30 * DAY);
  const obj = d.object || {}, orbit = d.orbit || {};
  const elements = {};
  for (const el of orbit.elements || []) {
    const v = parseFloat(el.value);
    if (Number.isFinite(v)) elements[el.name] = v;
  }
  const epoch = parseFloat(orbit.epoch);
  return {
    fullname: obj.fullname ?? null,
    neo: obj.neo ?? null,
    pha: obj.pha ?? null,
    kind: obj.kind ?? null,
    orbit_class: obj.orbit_class || {},
    orbit: { epoch: Number.isFinite(epoch) ? epoch : null, ...elements },
  };
}

const ASTEROID_HINT_RE = /\b(asteroids?|near shoemaker|near spacecraft|osiris-rex|osiris-apex|hayabusa2?|dart|dawn|lucy|psyche|goldstone|arecibo|neowise|planetary radar)\b/i;

async function nasaImages(term) {
  const d = await upstreamJson(`${IMAGES_URL}?${qs({ q: term, media_type: "image" })}`, 7 * DAY);
  const t = escapeRe(term);
  const word = new RegExp(`(?<![\\w-])${t}(?![\\w-])`, "i");
  const phrase = new RegExp(`\\basteroids?\\s+(?:\\d+\\s+)?${t}(?![\\w-])|(?<![\\w-])${t}\\s+asteroid\\b`, "i");
  const picked = [], seen = new Set();
  for (const it of (d.collection && d.collection.items) || []) {
    const data = (it.data && it.data[0]) || {};
    const title = data.title || "";
    const keywords = (data.keywords || []).filter(k => typeof k === "string");
    const desc = data.description || "";
    if (!(word.test(title) || keywords.some(k => word.test(k)))) continue;
    // 소행성 관련 표시가 제목·키워드에 있거나, 설명에 "asteroid <이름>" 형태로 언급돼야 함
    if (!(ASTEROID_HINT_RE.test([title, ...keywords].join(" | ")) || phrase.test(desc))) continue;
    const thumb = (it.links || []).find(l => l.render === "image");
    if (!thumb || seen.has(title)) continue;
    seen.add(title);
    picked.push({
      title, nasa_id: data.nasa_id, thumb: thumb.href,
      date: (data.date_created || "").slice(0, 10), center: data.center || null,
      in_title: word.test(title),
    });
  }
  picked.sort((a, b) => (a.in_title === b.in_title ? (a.date < b.date ? 1 : a.date > b.date ? -1 : 0) : a.in_title ? -1 : 1));
  return { term, total: picked.length, items: picked.slice(0, 4) };
}

async function exoplanetsRaw() {
  // 목록이 커서(수백 KB) JSON을 다시 파싱하지 않고 그대로 감싸서 돌려줍니다 (CPU 시간 절약).
  const text = await upstreamText(`${TAP_URL}?${qs({ query: EXO_QUERY, format: "json" })}`, DAY, 90000);
  if (!text.trim().startsWith("[")) throw new HttpError(502, "Exoplanet Archive 가 예상과 다른 응답을 보냈습니다");
  return `{"fetched":"${new Date().toISOString().slice(0, 19)}+00:00","planets":${text}}`;
}

// ------------------------------------------------------------------ HTTP
function allowedOrigin(request, env) {
  const origin = request.headers.get("Origin");
  if (!origin) return null;
  const list = (env.ALLOWED_ORIGINS || "").split(",").map(s => s.trim().replace(/\/$/, "")).filter(Boolean);
  return [...list, ...LOCAL_ORIGINS].includes(origin) ? origin : null;
}

function corsHeaders(origin) {
  return origin ? {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  } : { "Vary": "Origin" };
}

function reply(status, body, origin, maxAge = 0) {
  return new Response(typeof body === "string" ? body : JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": status === 200 && maxAge ? `public, max-age=${maxAge}` : "no-store",
      ...corsHeaders(origin),
    },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = allowedOrigin(request, env);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: origin ? 204 : 403, headers: corsHeaders(origin) });
    }
    if (request.method !== "GET") return reply(405, { error: "GET 만 지원합니다" }, origin);
    if (url.pathname === "/" || url.pathname === "/api" || url.pathname === "/api/") {
      return reply(200, { service: "우주 출생 증명서 API", ok: true }, origin);
    }
    // 브라우저에서 허용되지 않은 사이트가 호출하면 거절 (Origin 이 없는 직접 호출은 점검용으로 허용)
    if (request.headers.get("Origin") && !origin) {
      return reply(403, { error: "허용되지 않은 사이트에서의 요청입니다 (ALLOWED_ORIGINS 확인)" }, null);
    }

    const p = url.searchParams;
    try {
      switch (url.pathname) {
        case "/api/gfz":       return reply(200, await gfzDay(checkDate(p.get("date"))), origin, 3600);
        case "/api/cad":       return reply(200, await cadBirth(checkDate(p.get("date"))), origin, 7 * DAY);
        case "/api/cad_next":  return reply(200, await cadNext(checkText(p.get("des"), "des"), checkDate(p.get("from"))), origin, 3600);
        case "/api/sbdb":      return reply(200, await sbdbObject(checkText(p.get("des"), "des")), origin, 7 * DAY);
        case "/api/images":    return reply(200, await nasaImages(checkText(p.get("term"), "term")), origin, DAY);
        case "/api/exoplanets":return reply(200, await exoplanetsRaw(), origin, DAY);
        default:               return reply(404, { error: "알 수 없는 API 경로" }, origin);
      }
    } catch (e) {
      const status = e instanceof HttpError ? e.status : 500;
      return reply(status, { error: status === 500 ? `서버 내부 오류: ${e.message}` : e.message }, origin);
    }
  },
};

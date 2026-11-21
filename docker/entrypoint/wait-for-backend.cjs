// 세 앱(frontend·operator·classroom) 런타임 이미지의 진입점(#869).
//
//   node wait-for-backend.cjs <standalone server.js 경로>
//
// backend 가 HTTP 응답을 줄 때까지 기다린 다음 같은 프로세스에서 server.js 를 연다.
// 호스트 재부팅 때 도커 데몬은 depends_on 을 지키지 않고 전부 한꺼번에 올리는데,
// backend 콜드 스타트(컨테이너 시작 뒤 약 36초)가 BFF 재시도 예산(15.75초)보다 길어
// 그 틈에 들어온 요청이 500 을 냈다. 앱이 backend 를 기다리면 그 요청은 아예 받지 않는다
// (프록시는 연결 거부로 다시 시도한다).
//
// 상한: CODEMIT_BACKEND_WAIT_SECONDS(기본 120, 0 이면 기다리지 않는다). 상한을 넘으면
// 기다리기를 멈추고 그대로 띄운다 — backend 가 죽어 있어도 앱은 뜨고(500 대신 BFF 의 재시도·오류
// 화면), 끝없이 매달리지 않는다. 배포 중 교체는 backend 가 이미 듣고 있어 첫 시도에 끝난다.
// 응답 코드는 보지 않는다 — 503(워커 신호 없음)도 gunicorn 이 듣는다는 뜻이다.
"use strict";

const http = require("node:http");
const path = require("node:path");

const POLL_MS = 500;
const ATTEMPT_TIMEOUT_MS = 2000;

function probe(url) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: ATTEMPT_TIMEOUT_MS }, (res) => {
      res.resume();
      resolve(true);
    });
    req.on("timeout", () => req.destroy());
    req.on("error", () => resolve(false));
  });
}

async function waitForBackend(baseUrl, limitMs, log) {
  const url = new URL("/api/health?scope=ready", baseUrl).toString();
  const started = Date.now();
  let announced = false;
  while (true) {
    if (await probe(url)) {
      if (announced) log(`backend 응답 — ${((Date.now() - started) / 1000).toFixed(1)}초 기다렸다`);
      return true;
    }
    if (Date.now() - started >= limitMs) {
      log(`backend 가 ${limitMs / 1000}초 안에 응답하지 않는다 — 기다리기를 멈추고 앱을 띄운다`);
      return false;
    }
    if (!announced) {
      log(`backend 를 기다린다 (${url})`);
      announced = true;
    }
    await new Promise((r) => setTimeout(r, POLL_MS));
  }
}

async function main() {
  const target = process.argv[2];
  if (!target) {
    console.error("사용법: node wait-for-backend.cjs <server.js>");
    process.exit(2);
  }
  const base = process.env.CODEMIT_API_BASE_URL;
  const seconds = Number(process.env.CODEMIT_BACKEND_WAIT_SECONDS ?? "120");
  if (base && Number.isFinite(seconds) && seconds > 0) {
    await waitForBackend(base, seconds * 1000, (m) => console.log(`[entrypoint] ${m}`));
  }
  require(path.resolve(target));
}

if (require.main === module) {
  main();
} else {
  module.exports = { waitForBackend };
}

// 한 주소의 경로들을 크기·테마마다 찍는다 — `shoot-before-after.sh` 가 부른다(#976).
// 사용: node scripts/shoot.mjs <baseURL> <출력폴더> <이름> <경로,경로> <너비,너비> <light,dark> <앱폴더>
// 로그인이 필요한 화면(#985): SHOOT_LOGIN_BACKEND(백엔드 주소)와 SHOOT_LOGIN_TOKEN(`<uid>:<이메일>` — dev 의
// fake 소셜 로그인 토큰)을 주면 그 계정의 세션 쿠키를 앱 오리진에 심고 찍는다. 계정을 여럿 찍으려면
// SHOOT_LOGINS="이름=<토큰>,이름=<토큰>" — 이름이 파일명에 붙는다.
// SHOOT_WAIT=<CSS 선택자> 는 클라이언트가 데이터를 받아 그릴 때까지 그 요소를 기다린다.
// Playwright 는 저장소 것(<앱폴더>/../frontend 의 @playwright/test)을 쓴다.
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const [base, outDir, name, paths, widths, themes, root] = process.argv.slice(2);
const { chromium } = createRequire(path.join(root, "frontend", "package.json"))("@playwright/test");
mkdirSync(outDir, { recursive: true });
// stop-all 이 이 나무를 걷을 수 있게 자기 pid 를 남긴다.
if (process.env.SHOOT_PIDFILE) writeFileSync(process.env.SHOOT_PIDFILE, String(process.pid));

const loginBackend = process.env.SHOOT_LOGIN_BACKEND;
const logins = process.env.SHOOT_LOGINS
  ? process.env.SHOOT_LOGINS.split(",").map((pair) => pair.split(/=(.*)/s).slice(0, 2))
  : process.env.SHOOT_LOGIN_TOKEN
    ? [["", process.env.SHOOT_LOGIN_TOKEN]]
    : [["", ""]];
async function sessionCookies(loginToken) {
  const response = await fetch(new URL("/api/auth/social/kakao/login", loginBackend), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ access_token: loginToken }),
  });
  if (!response.ok) throw new Error(`로그인 실패 ${response.status}`);
  const { access, refresh } = await response.json();
  return [
    { name: "codemit_access", value: access, url: base, httpOnly: true, sameSite: "Lax" },
    { name: "codemit_refresh", value: refresh, url: base, httpOnly: true, sameSite: "Lax" },
  ];
}

const browser = await chromium.launch();
try {
  for (const [login, loginToken] of logins) {
   const tag = login ? `-${login}` : "";
   for (const theme of themes.split(",")) {
    for (const width of widths.split(",").map(Number)) {
      const context = await browser.newContext({
        viewport: { width, height: width > 600 ? 900 : 844 },
        colorScheme: theme,
      });
      if (loginBackend && loginToken) await context.addCookies(await sessionCookies(loginToken));
      const page = await context.newPage();
      for (const p of paths.split(",")) {
        await page.goto(new URL(p, base).toString(), { waitUntil: "load", timeout: 60000 });
        if (process.env.SHOOT_WAIT) await page.waitForSelector(process.env.SHOOT_WAIT, { timeout: 30000 });
        await page.evaluate(() => document.fonts.ready);
        const slug = p === "/" ? "root" : p.replace(/^\//, "").replace(/[^\w-]+/g, "_");
        const file = path.join(outDir, `${name}-${slug}${tag}-${width}-${theme}.png`);
        await page.screenshot({ path: file, fullPage: true });
        console.log(file);
      }
      await context.close();
    }
   }
  }
} finally {
  await browser.close();
}

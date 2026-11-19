// 한 주소의 경로들을 크기·테마마다 찍는다 — `shoot-before-after.sh` 가 부른다(#976).
// 사용: node scripts/shoot.mjs <baseURL> <출력폴더> <이름> <경로,경로> <너비,너비> <light,dark> <앱폴더>
// Playwright 는 저장소 것(<앱폴더>/../frontend 의 @playwright/test)을 쓴다.
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const [base, outDir, name, paths, widths, themes, root] = process.argv.slice(2);
const { chromium } = createRequire(path.join(root, "frontend", "package.json"))("@playwright/test");
mkdirSync(outDir, { recursive: true });
// stop-all 이 이 나무를 걷을 수 있게 자기 pid 를 남긴다.
if (process.env.SHOOT_PIDFILE) writeFileSync(process.env.SHOOT_PIDFILE, String(process.pid));

const browser = await chromium.launch();
try {
  for (const theme of themes.split(",")) {
    for (const width of widths.split(",").map(Number)) {
      const context = await browser.newContext({
        viewport: { width, height: width > 600 ? 900 : 844 },
        colorScheme: theme,
      });
      const page = await context.newPage();
      for (const p of paths.split(",")) {
        await page.goto(new URL(p, base).toString(), { waitUntil: "load", timeout: 60000 });
        await page.evaluate(() => document.fonts.ready);
        const slug = p === "/" ? "root" : p.replace(/^\//, "").replace(/[^\w-]+/g, "_");
        const file = path.join(outDir, `${name}-${slug}-${width}-${theme}.png`);
        await page.screenshot({ path: file, fullPage: true });
        console.log(file);
      }
      await context.close();
    }
  }
} finally {
  await browser.close();
}

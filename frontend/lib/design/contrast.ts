// WCAG 2.x 대비 계산 — 순수 함수(#397). `tokens.css` 의 `light-dark(라이트, 다크)`
// 값을 파싱해 두 테마 각각의 실제 대비를 잰다. 컴포넌트를 그리지 않고 색만 본다
// — 이 저장소의 순수 함수 시임(ADR-0026)이 react·next 임포트를 이 러너에서
// 거부하기 때문이기도 하고, 좋은 테스트는 바깥 동작(산출물의 값)만 보기 때문이다.

export interface Rgb {
  r: number;
  g: number;
  b: number;
}

export function hexToRgb(hex: string): Rgb {
  const m = /^#([0-9a-fA-F]{6})$/.exec(hex);
  if (!m) throw new Error(`유효한 6자리 hex 색이 아니다: ${hex}`);
  const n = parseInt(m[1], 16);
  return { r: (n >> 16) & 0xff, g: (n >> 8) & 0xff, b: n & 0xff };
}

function channelLuminance(value255: number): number {
  const s = value255 / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

/** WCAG 상대 휘도 (0~1). */
export function relativeLuminance({ r, g, b }: Rgb): number {
  return 0.2126 * channelLuminance(r) + 0.7152 * channelLuminance(g) + 0.0722 * channelLuminance(b);
}

/** WCAG 대비비 — 1:1(구별 안 됨) ~ 21:1(검정/흰). */
export function contrastRatio(a: Rgb, b: Rgb): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const lighter = Math.max(la, lb);
  const darker = Math.min(la, lb);
  return (lighter + 0.05) / (darker + 0.05);
}

/** `text-ink/60` 처럼 알파를 준 글자가 뜬 면 위에서 실제로 내는 색 — 단순 알파 합성. */
export function blendOver(fg: Rgb, bg: Rgb, alpha: number): Rgb {
  return {
    r: fg.r * alpha + bg.r * (1 - alpha),
    g: fg.g * alpha + bg.g * (1 - alpha),
    b: fg.b * alpha + bg.b * (1 - alpha),
  };
}

export const TOKEN_COLOR_NAMES = ["ink", "paper", "surface", "rule", "attention", "verified"] as const;
export type TokenColorName = (typeof TOKEN_COLOR_NAMES)[number];
export type TokenPalette = Record<TokenColorName, { light: Rgb; dark: Rgb }>;

/** `tokens.css` 텍스트에서 여섯 색의 `light-dark(...)` 값을 뽑는다. */
export function parseTokenPalette(css: string): TokenPalette {
  const out = {} as TokenPalette;
  for (const name of TOKEN_COLOR_NAMES) {
    const re = new RegExp(
      `--color-${name}:\\s*light-dark\\(\\s*(#[0-9a-fA-F]{6})\\s*,\\s*(#[0-9a-fA-F]{6})\\s*\\)`,
    );
    const m = re.exec(css);
    if (!m) throw new Error(`--color-${name} 의 light-dark(...) 값을 tokens.css 에서 찾지 못했다`);
    out[name] = { light: hexToRgb(m[1]), dark: hexToRgb(m[2]) };
  }
  return out;
}

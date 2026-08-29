// Tailwind v4 는 PostCSS 플러그인 하나로 들어온다. 별도 tailwind.config.* 는 없다 —
// 토큰은 app/tokens.css 의 @theme 블록에 CSS 변수로 산다(티켓 FE-02, #27).
const config = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};

export default config;

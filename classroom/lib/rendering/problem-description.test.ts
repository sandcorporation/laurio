// 문제 설명 렌더러의 순수 함수 시임(#313, ADR-0041·ADR-0047) — 공격 문자열은 e2e 로
// 여러 개 돌릴 수 없으니 여기서 돈다. 걸러진 트리를 HTML 문자열로 옮겨 단언한다 —
// 화면은 이 트리를 React 요소로 옮기므로 문자열에 없는 것은 화면에도 없다.
import { toHtml } from "hast-util-to-html";
import { describe, expect, it } from "vitest";

import { parseProblemDescription } from "./problem-description";

const html = (markdown: string) => toHtml(parseProblemDescription(markdown));

describe("허용 목록을 통과하는 서식", () => {
  it("제목은 한 단계씩 내려 h2 부터 쓴다 — 화면의 h1 은 문제 제목 하나다", () => {
    const out = html("# 하나\n\n## 둘\n\n###### 여섯");
    expect(out).toContain("<h2>하나</h2>");
    expect(out).toContain("<h3>둘</h3>");
    expect(out).toContain("<h6>여섯</h6>");
    expect(out).not.toContain("<h1");
  });

  it("굵기·기울임·인라인 코드·취소선을 그린다", () => {
    const out = html("**굵게** *기울여* `코드` ~~취소~~");
    expect(out).toContain("<strong>굵게</strong>");
    expect(out).toContain("<em>기울여</em>");
    expect(out).toContain("<code>코드</code>");
    expect(out).toContain("<del>취소</del>");
  });

  it("순서 없는·있는·중첩 목록을 그린다", () => {
    const out = html("- 하나\n  - 중첩\n\n1. 첫째\n2. 둘째");
    expect(out).toMatch(/<ul>[\s\S]*<li>하나[\s\S]*<ul>[\s\S]*<li>중첩<\/li>/);
    expect(out).toMatch(/<ol>[\s\S]*<li>첫째<\/li>/);
  });

  it("체크박스 목록은 누를 수 없는 체크박스로 그린다", () => {
    const out = html("- [ ] 할 일\n- [x] 끝낸 일");
    expect(out).toContain('type="checkbox"');
    expect(out).toContain("disabled");
    expect(out).toMatch(/checked[\s\S]*끝낸 일/);
  });

  it("표를 그린다", () => {
    const out = html("| 입력 | 출력 |\n|:---|---:|\n| 1 | 2 |");
    expect(out).toContain("<table>");
    expect(out).toContain("<th align=\"left\">입력</th>");
    expect(out).toContain("<td align=\"right\">2</td>");
  });

  it("코드블록이 언어와 원문 그대로의 코드를 보존한다 — 안의 HTML 은 글자다", () => {
    const out = html("```js\nconsole.log('<b>안 굵음</b>')\n```");
    expect(out).toContain('<code class="language-js">');
    expect(out).toContain("&#x3C;b>안 굵음&#x3C;/b>");
    expect(out).not.toContain("<b>");
  });

  it("인용과 수평선을 그린다", () => {
    const out = html("> 인용문\n\n---");
    expect(out).toContain("<blockquote>");
    expect(out).toContain("<hr>");
  });

  it("http/https 링크와 이미지를 통과시킨다", () => {
    const out = html("[문서](https://codemit.example/doc) ![그림](http://codemit.example/a.png)");
    expect(out).toContain('<a href="https://codemit.example/doc">문서</a>');
    expect(out).toContain('<img src="http://codemit.example/a.png" alt="그림">');
  });

  it("기존 순수 텍스트 설명이 줄바꿈을 유지한 채 그대로 읽힌다", () => {
    const out = html("첫 줄\n둘째 줄\n\n다음 문단");
    expect(out).toMatch(/<p>첫 줄<br>\s*둘째 줄<\/p>/);
    expect(out).toContain("<p>다음 문단</p>");
  });

  it("빈 설명은 빈 트리를 낸다", () => {
    expect(parseProblemDescription("")).toEqual({ type: "root", children: [] });
    expect(parseProblemDescription("   \n ")).toEqual({ type: "root", children: [] });
  });
});

describe("공격 문자열이 어느 것도 통과하지 않는다", () => {
  it("script 태그가 트리 어디에도 남지 않는다", () => {
    const out = html("설명 앞\n\n<script>alert(document.cookie)</script>\n\n설명 뒤");
    expect(out).not.toContain("script");
    expect(out).not.toContain("alert");
    expect(out).toContain("설명 앞");
    expect(out).toContain("설명 뒤");
  });

  it("인라인 이벤트 핸들러 속성이 있는 raw 태그가 통과하지 않는다", () => {
    const out = html('본문 중간에 <img src=x onerror="alert(1)"> 섞여 있다');
    expect(out).not.toContain("onerror");
    expect(out).not.toContain("<img");
  });

  it("javascript: 링크는 링크가 아니라 평문으로 낮아진다", () => {
    const out = html("[누르지마](javascript:alert(document.cookie))");
    expect(out).not.toContain("<a");
    expect(out).not.toContain("javascript:");
    expect(out).toContain("누르지마");
  });

  it("data: 이미지는 어느 노드로도 나타나지 않는다", () => {
    const out = html("![덫](data:image/png;base64,AAAA)");
    expect(out).not.toContain("data:");
    expect(out).not.toContain("<img");
  });

  it("javascript: 스킴을 대문자·공백으로 우회해도 막힌다", () => {
    const out = html("[클릭](  JaVaScRiPt:alert(1))");
    expect(out).not.toMatch(/href=/i);
  });

  it("중첩되고 깨진 마크업을 넣어도 트리가 만들어지고 실행 가능한 조각이 남지 않는다", () => {
    const out = html("<div><script>alert(1)</script><img src=x onerror=alert(2)>\n\n**안 닫힌 굵기\n\n<svg onload=alert(3)>");
    expect(out).not.toContain("script");
    expect(out).not.toContain("onerror");
    expect(out).not.toContain("onload");
    expect(out).not.toContain("<svg");
  });

  it("스타일 태그로 실려 오는 서식도 통과하지 않는다 — 뒤따르는 문단은 그대로 읽힌다", () => {
    const out = html("<style>body{display:none}</style>\n\n일반 텍스트");
    expect(out).not.toContain("style");
    expect(out).toContain("일반 텍스트");
  });

  it("체크박스를 누를 수 있게 만드는 속성이 원문에서 들어오지 않는다", () => {
    const out = html('<input type="text" onfocus="alert(1)" autofocus>\n\n- [ ] 항목');
    expect(out).not.toContain('type="text"');
    expect(out).not.toContain("onfocus");
    expect(out).not.toContain("autofocus");
  });
});

"use client";

// 문제 설명을 쓰는 ToastUI 에디터(#324, ADR-0041). 마크다운 모드와 보이는
// 대로(WYSIWYG) 모드를 사용자가 오갈 수 있다 — 라이브러리 기본 UI의 우측 상단
// 탭이 그 자리다. **저장되는 값은 언제나 마크다운 원문이다** — WYSIWYG 로
// 쓰더라도 `onChange`에는 `editor.getMarkdown()`만 실려 나간다. HTML을 저장하면
// `ADR-0041`이 성립하는 전제(「HTML을 저장하지 않는다 + 렌더가 허용 목록
// 방식이다」)가 무너진다.
//
// **이 안의 미리보기는 ToastUI 것이다 — 참여자에게 보여줄 때 쓰는
// `ProblemDescription`(허용 목록 렌더러, lib/rendering/problem-description.ts)과
// 다른 길이다.** 글 쓰는 본인만 보는 자리라 여기서는 허용된다(#324 body) — 표
// 등 우리 렌더러가 그리지 않는 서식을 ToastUI는 그릴 수 있어 둘이 어긋날 수
// 있다는 뜻이기도 하다. 참여자가 실제로 볼 화면 그대로는 문제 만들기/편집의
// 「미리보기」 탭(#325)이 우리 렌더러로 보여준다.
//
// 에디터 생성은 브라우저에서만 한다(동적 import) — `@toast-ui/editor`는 DOM을
// 직접 다루는 라이브러리라 이 컴포넌트가 서버에서 먼저 렌더될 때(Next의
// "use client" 컴포넌트도 최초 HTML은 서버가 만든다) import 시점에 죽을 수
// 있다. `useEffect` 안에서만 불러오면 그 경로 자체가 없다.
//
// **다크는 Toast UI 자신의 `.toastui-editor-dark` 클래스가 켠다**(#399) —
// 우리 토큰(`--color-*`)과 달리 CSS 변수로 자동으로 안 바뀐다(툴바 아이콘
// 스프라이트를 다른 줄로 바꾸는 등 클래스가 있어야만 하는 규칙이 섞여 있다).
// 그래서 `resolveEffectiveTheme`(#397 과 같은 순서)로 지금 다크인지 판정해
// 컨테이너에 그 클래스를 직접 붙였다 뗀다 — 문서 루트 표시가 바뀌거나
// (`theme-bus`) 운영체제 설정이 바뀌면(`matchMedia`) 다시 판정한다. 색 자체는
// 여전히 `toastui-editor-overrides.css`의 토큰 변수가 정한다 — 이 클래스는
// Toast UI 라이브러리 안쪽(아이콘 스프라이트 등)만 건드린다.
import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import type ToastEditor from "@toast-ui/editor";

import { resolveEffectiveTheme } from "@/lib/theme/preference";
import { subscribeToThemeChange } from "@/lib/theme/theme-bus";

import "@toast-ui/editor/dist/toastui-editor.css";
import "@toast-ui/editor/dist/theme/toastui-editor-dark.css";
import "./toastui-editor-overrides.css";

export function MarkdownEditor({
  id,
  label,
  value,
  onChange,
  placeholder,
  testId,
  hint,
}: {
  id: string;
  //: 화면에 보이는 필드 이름(예: "설명") — 에디터 내부 요소에 접근성 이름으로
  //: 붙는다. ToastUI가 모드마다 다른 DOM(textarea/contenteditable)을 새로
  //: 만들어 `<label htmlFor>` 로 직접 연결할 고정된 대상이 없다.
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  testId: string;
  hint?: ReactNode;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<ToastEditor | null>(null);
  // 에디터가 마지막으로 알고 있는 값 — 바깥에서 온 `value` 변경(초기 로딩 뒤
  // 채워지는 문제 편집 화면 등)과 에디터 자신의 `change` 이벤트를 구별해,
  // 타이핑 중에 커서를 흩뜨리는 불필요한 `setMarkdown` 호출을 막는다.
  const lastKnownValueRef = useRef(value);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    let cancelled = false;
    let editor: ToastEditor | null = null;

    Promise.all([import("@toast-ui/editor"), import("@toast-ui/editor/dist/i18n/ko-kr")]).then(
      ([{ default: Editor }]) => {
        if (cancelled || !containerRef.current) return;
        editor = new Editor({
          el: containerRef.current,
          height: "360px",
          initialEditType: "markdown",
          previewStyle: "vertical",
          initialValue: lastKnownValueRef.current,
          placeholder,
          usageStatistics: false,
          language: "ko-KR",
          events: {
            change: () => {
              if (!editor) return;
              const markdown = editor.getMarkdown();
              lastKnownValueRef.current = markdown;
              onChangeRef.current(markdown);
            },
          },
        });
        editorRef.current = editor;

        // `getEditorElements()`가 주는 mdEditor/wwEditor는 각 모드의 바깥
        // 감싸개다 — 실제로 포커스를 받는 것은 그 안의 `.ProseMirror`
        // 편집영역이라 거기에 접근성 이름을 직접 붙인다.
        const slots = editor.getEditorElements();
        for (const wrapper of [slots.mdEditor, slots.wwEditor]) {
          const editable = wrapper?.querySelector<HTMLElement>(".ProseMirror") ?? wrapper;
          editable?.setAttribute("aria-label", label);
        }
      },
    );

    return () => {
      cancelled = true;
      try {
        // ToastUI 자신의 툴바가 리사이즈를 200ms 스로틀로 재배치한다
        // (`Toolbar.prototype.addEvent`, 라이브러리 소스) — 언마운트로 이
        // 컨테이너가 문서에서 빠지는 순간도 리사이즈라 그 트레일링
        // 호출이 늦게 흐른다. `destroy()`가 이미 끝난 뒤(우리 쪽 정리는
        // React 커밋 중 동기로 돈다) 그 지연 호출이 내부 컴포넌트에
        // `setState`를 걸어 이미 없는 DOM 노드를 지우려다 NotFoundError를
        // 던지는 것을 실제로 봤다(#326, 가져오기 → 편집 화면 전환에서
        // 재현·dev 오버레이에만 뜨는 비차단 경고). 라이브러리 안쪽의
        // ResizeObserver 콜백이라 우리 쪽에서 취소할 손잡이가 없다 — 이
        // 컴포넌트는 통째로 버려지는 중이라 그 실패 자체는 무해하니
        // 콘솔의 uncaught 예외로만 남지 않게 삼근다.
        editor?.destroy();
      } catch {
        // 위 설명대로 — 이미 버려지는 트리라 여기서 할 일이 없다.
      }
      editorRef.current = null;
    };
    // 마운트 한 번에 에디터 하나 — `label`·`placeholder`가 나중에 바뀌는
    // 호출부는 지금 없다. `value`는 아래 별도 effect가 다룬다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // 에디터가 아직 만들어지는 중이어도(동적 import가 안 끝났어도) 여기서
    // ref는 늘 최신 값으로 갱신한다 — 그래야 위 마운트 effect가 나중에
    // `lastKnownValueRef.current`를 initialValue로 읽을 때 이 값을 본다.
    // 편집 화면은 처음엔 `value=""`로 마운트됐다가(로딩 중) 비동기로 문제를
    // 불러온 뒤에야 진짜 설명이 채워지므로, 두 비동기(에디터 생성 / 데이터
    // 로딩) 중 어느 쪽이 먼저 끝나도 최종적으로 올바른 값이 반영돼야 한다.
    const changed = value !== lastKnownValueRef.current;
    lastKnownValueRef.current = value;
    const editor = editorRef.current;
    if (!editor || !changed) return;
    editor.setMarkdown(value, false);
  }, [value]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const applyDarkClass = () => {
      const explicit = document.documentElement.getAttribute("data-theme");
      const isDark = resolveEffectiveTheme(explicit, media.matches) === "dark";
      container.classList.toggle("toastui-editor-dark", isDark);
    };

    applyDarkClass();
    media.addEventListener("change", applyDarkClass);
    const unsubscribe = subscribeToThemeChange(applyDarkClass);
    return () => {
      media.removeEventListener("change", applyDarkClass);
      unsubscribe();
    };
  }, []);

  return (
    <div className="flex flex-col gap-1.5">
      <div
        id={id}
        ref={containerRef}
        data-testid={testId}
        className="codemit-toastui-editor"
      />
      {hint}
    </div>
  );
}

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
import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import type ToastEditor from "@toast-ui/editor";

import "@toast-ui/editor/dist/toastui-editor.css";
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

    import("@toast-ui/editor").then(({ default: Editor }) => {
      if (cancelled || !containerRef.current) return;
      editor = new Editor({
        el: containerRef.current,
        height: "360px",
        initialEditType: "markdown",
        previewStyle: "vertical",
        initialValue: lastKnownValueRef.current,
        placeholder,
        usageStatistics: false,
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

      const slots = editor.getEditorElements();
      slots.mdEditor?.setAttribute("aria-label", label);
      slots.wwEditor?.setAttribute("aria-label", label);
    });

    return () => {
      cancelled = true;
      editor?.destroy();
      editorRef.current = null;
    };
    // 마운트 한 번에 에디터 하나 — `label`·`placeholder`가 나중에 바뀌는
    // 호출부는 지금 없다. `value`는 아래 별도 effect가 다룬다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || value === lastKnownValueRef.current) return;
    lastKnownValueRef.current = value;
    editor.setMarkdown(value, false);
  }, [value]);

  return (
    <div className="flex flex-col gap-1.5">
      <div
        id={id}
        ref={containerRef}
        data-testid={testId}
        className="laurio-toastui-editor"
      />
      {hint}
    </div>
  );
}

// `@toast-ui/editor@3.2.2`(#324)는 타입을 `types/index.d.ts`에 담아 두고도
// `package.json`의 `exports` 맵 "." 항목에 `types` 조건을 넣지 않았다 — Node의
// exports 맵이 있으면 TypeScript(`moduleResolution: "bundler"`)는 그 안에 없는
// 조건으로는 루트 `types` 필드로도 폴백하지 않는다(업로드 시점의 실제
// `node_modules/@toast-ui/editor/package.json`으로 확인, 우리 설정 문제가
// 아니라 그 패키지의 포장 결함). 그 결과 `import Editor from "@toast-ui/editor"`
// 가 `any`로 무너져 `tsc --noEmit`을 통과는 하되 이 모듈을 쓰는 자리(빌드타임
// 오타 검사, `strict` 모드의 이점)가 전부 죽는다.
//
// 그래서 여기서 이 패키지의 타입을 직접 선언한다 — `MarkdownEditor.tsx`가 실제로
// 쓰는 자리만큼만. 라이브러리 전체 표면을 옮겨 적지 않는다.
declare module "@toast-ui/editor" {
  export type ToastUiEditorType = "markdown" | "wysiwyg";

  export interface ToastUiEditorSlots {
    mdEditor: HTMLElement;
    mdPreview: HTMLElement;
    wwEditor: HTMLElement;
  }

  export interface ToastUiEditorEventMap {
    change?: (editorType: ToastUiEditorType) => void;
  }

  export interface ToastUiEditorOptions {
    el: HTMLElement;
    height?: string;
    minHeight?: string;
    initialValue?: string;
    previewStyle?: "tab" | "vertical";
    initialEditType?: ToastUiEditorType;
    placeholder?: string;
    usageStatistics?: boolean;
    language?: string;
    /** 기본값 true — 만들어지자마자 편집 영역으로 포커스를 옮긴다. */
    autofocus?: boolean;
    events?: ToastUiEditorEventMap;
  }

  export default class Editor {
    constructor(options: ToastUiEditorOptions);
    getMarkdown(): string;
    setMarkdown(markdown: string, cursorToEnd?: boolean): void;
    getEditorElements(): ToastUiEditorSlots;
    destroy(): void;
  }
}

// 한국어 UI 로케일(#324) — import 하면 `Editor.setLanguage`를 부르는
// 부작용만 있고 값을 내보내지 않는다.
declare module "@toast-ui/editor/dist/i18n/ko-kr";

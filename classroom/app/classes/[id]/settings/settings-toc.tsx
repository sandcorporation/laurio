"use client";

// 클래스 설정의 왼쪽 목차(#636, 시안 v2) — 180px, 넓은 화면에서는 따라다니고(sticky) 좁은 화면에서는
// 한 줄로 눕는다. 지금 보고 있는 구획에 왼쪽 막대가 선다. 구획의 `id` 가 앵커이고 알림·배너가
// `#scoring-key` 처럼 그 id 로 곧장 온다.
import { useEffect, useState } from "react";

export type SettingsSection = { id: string; label: string };

export function SettingsToc({ sections }: { sections: SettingsSection[] }) {
  const [active, setActive] = useState(sections[0]?.id ?? "");

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const visible = new Set<string>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) visible.add(entry.target.id);
          else visible.delete(entry.target.id);
        }
        // 화면에 걸친 구획 가운데 목차에서 가장 앞선 것이 지금 구획이다.
        const current = sections.find((section) => visible.has(section.id));
        if (current) setActive(current.id);
      },
      { rootMargin: "-10% 0px -60% 0px" },
    );
    for (const section of sections) {
      const element = document.getElementById(section.id);
      if (element) observer.observe(element);
    }
    return () => observer.disconnect();
  }, [sections]);

  return (
    <nav
      aria-label="설정 목차"
      data-testid="settings-toc"
      className="flex shrink-0 gap-1 overflow-x-auto lg:sticky lg:top-6 lg:w-[180px] lg:flex-col lg:gap-0.5 lg:self-start lg:overflow-visible"
    >
      {sections.map((section) => {
        const current = section.id === active;
        return (
          <a
            key={section.id}
            href={`#${section.id}`}
            data-testid={`settings-toc-${section.id}`}
            aria-current={current ? "true" : undefined}
            onClick={() => setActive(section.id)}
            className={`whitespace-nowrap border-b-2 px-3 py-1.5 text-[13px] lg:border-b-0 lg:border-l-2 lg:py-[7px] ${
              current ? "border-ink font-medium text-ink" : "border-transparent text-ink/60 hover:text-ink"
            }`}
          >
            {section.label}
          </a>
        );
      })}
    </nav>
  );
}

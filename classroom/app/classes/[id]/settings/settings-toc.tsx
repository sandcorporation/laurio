"use client";

// 클래스 설정의 왼쪽 목차(#636, 시안 v2) — 180px, 넓은 화면에서는 따라다니고(sticky) 좁은 화면에서는
// 한 줄로 눕는다. 지금 보고 있는 구획에 왼쪽 막대가 선다. 구획의 `id` 가 앵커이고 알림·배너가
// `#scoring-key` 처럼 그 id 로 곧장 온다.
import { useEffect, useState } from "react";

// 지금 구획은 화면 위쪽 띠(높이의 10%~40%)에 걸친 구획 가운데 목차에서 가장 앞선 것이다. 다만 스크롤이
// 끝에 닿으면 맨 아래 짧은 구획들은 그 띠까지 올라오지 못한다(#664) — 그때는 주소의 구획(#class-archive
// 로 도착했거나 목차를 눌렀다)이 화면 안에 다 들어와 있으면 그것을, 아니면 마지막 구획을 고른다.
function currentSection(sections: SettingsSection[]): string | undefined {
  const height = window.innerHeight;
  const placed = sections
    .map((section) => ({ id: section.id, rect: document.getElementById(section.id)?.getBoundingClientRect() }))
    .filter((entry): entry is { id: string; rect: DOMRect } => entry.rect !== undefined);
  if (placed.length === 0) return undefined;
  const root = document.documentElement;
  const atEnd = window.scrollY > 0 && window.scrollY + height >= root.scrollHeight - 2;
  if (atEnd) {
    const target = placed.find((entry) => entry.id === window.location.hash.slice(1));
    if (target && target.rect.top >= 0 && target.rect.bottom <= height) return target.id;
    return placed[placed.length - 1].id;
  }
  return placed.find((entry) => entry.rect.bottom > height * 0.1 && entry.rect.top < height * 0.4)?.id;
}

export type SettingsSection = { id: string; label: string };

export function SettingsToc({ sections }: { sections: SettingsSection[] }) {
  const [active, setActive] = useState(sections[0]?.id ?? "");

  useEffect(() => {
    let frame = 0;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const next = currentSection(sections);
        if (next) setActive(next);
      });
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    window.addEventListener("hashchange", update);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
      window.removeEventListener("hashchange", update);
    };
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

"use client";

// 운영 설정 조회(#922) — 값과 이력을 따로 읽는다(한쪽이 실패해도 다른 쪽은 보인다, 정책 화면과 같다).
import { useCallback, useEffect, useState } from "react";

import { fetchRuntimeSettingChanges, fetchRuntimeSettings } from "./actions";
import type { RuntimeSetting, RuntimeSettingChange } from "./types";

export type Loadable<T> = { status: "loading" } | { status: "error" } | { status: "loaded"; data: T };

export function useRuntimeSettings(enabled: boolean): {
  settings: Loadable<RuntimeSetting[]>;
  changes: Loadable<RuntimeSettingChange[]>;
  reload: () => void;
} {
  const [settings, setSettings] = useState<Loadable<RuntimeSetting[]>>({ status: "loading" });
  const [changes, setChanges] = useState<Loadable<RuntimeSettingChange[]>>({ status: "loading" });
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void fetchRuntimeSettings().then((result) => {
      if (cancelled) return;
      setSettings(result.ok ? { status: "loaded", data: result.data.settings } : { status: "error" });
    });
    void fetchRuntimeSettingChanges().then((result) => {
      if (cancelled) return;
      setChanges(result.ok ? { status: "loaded", data: result.data } : { status: "error" });
    });
    return () => {
      cancelled = true;
    };
  }, [enabled, version]);

  return { settings, changes, reload };
}

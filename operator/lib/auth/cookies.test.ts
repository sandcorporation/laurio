// 운영자 앱의 배포 대상 판정 — 공개 앱·강의실의 lib/auth/cookies.test.ts 와 같은 약속이다.
import { afterEach, beforeEach, describe, expect, test } from "vitest";

import { invalidDeploymentTarget, isDeployedEnvironment } from "./cookies";

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  process.env = { ...ORIGINAL_ENV };
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
});

describe("배포 대상 — production 하나만 배포로 본다(staging 은 #836 에서 없앴다)", () => {
  test("production 만 배포 환경이다", () => {
    process.env.CODEMIT_DEPLOYMENT_TARGET = "production";
    expect(isDeployedEnvironment()).toBe(true);

    for (const target of ["development", "staging", ""]) {
      process.env.CODEMIT_DEPLOYMENT_TARGET = target;
      expect(isDeployedEnvironment()).toBe(false);
    }
  });

  test("비어 있거나 development·production 이면 부팅 가드가 받아들인다", () => {
    expect(invalidDeploymentTarget(undefined)).toBeNull();
    expect(invalidDeploymentTarget("")).toBeNull();
    expect(invalidDeploymentTarget("development")).toBeNull();
    expect(invalidDeploymentTarget("production")).toBeNull();
  });

  test("없앤 staging 과 오타는 부팅 가드가 거부한다 — development 로 조용히 흐르지 않는다", () => {
    for (const target of ["staging", "Staging", "prod", "Production", " production"]) {
      expect(invalidDeploymentTarget(target)).toContain(`CODEMIT_DEPLOYMENT_TARGET=${target}`);
    }
  });
});

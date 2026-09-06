import { describe, expect, it } from "vitest";

import { SOCIAL_PROVIDERS, isSocialProvider } from "./social-providers";

describe("isSocialProvider", () => {
  it("accepts exactly the three providers the backend implements", () => {
    for (const provider of SOCIAL_PROVIDERS) {
      expect(isSocialProvider(provider)).toBe(true);
    }
  });

  it("rejects anything else, including near-misses", () => {
    for (const value of ["facebook", "Kakao", "kakao ", "", "kakao/authorize"]) {
      expect(isSocialProvider(value)).toBe(false);
    }
  });
});

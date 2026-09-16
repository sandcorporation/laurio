import { describe, expect, it } from "vitest";

import { MAX_IMAGE_BYTES, formatFileSize, validateImageFile } from "./image-constraints";

function fakeFile(type: string, size: number): File {
  return { type, size } as File;
}

describe("formatFileSize (#424 AC — 크기가 함께 뜬다)", () => {
  it("1KB 미만은 바이트 단위다", () => {
    expect(formatFileSize(512)).toBe("512B");
  });

  it("킬로바이트 단위로 반올림한다", () => {
    expect(formatFileSize(214 * 1024)).toBe("214KB");
  });

  it("메가바이트는 소수 첫째 자리까지 보인다", () => {
    expect(formatFileSize(5 * 1024 * 1024)).toBe("5.0MB");
  });
});

describe("validateImageFile (#424 AC — 형식·크기가 맞지 않으면 이유를 보인다)", () => {
  it("허용된 형식·크기는 통과한다", () => {
    expect(validateImageFile(fakeFile("image/png", 1024))).toBeNull();
  });

  it("허용되지 않은 형식은 이유를 낸다", () => {
    expect(validateImageFile(fakeFile("image/gif", 1024))).toMatch(/png·jpeg·webp/);
  });

  it("상한을 넘는 크기는 이유를 낸다", () => {
    expect(validateImageFile(fakeFile("image/png", MAX_IMAGE_BYTES + 1))).toMatch(/까지 올릴 수 있습니다/);
  });

  it("상한과 정확히 같은 크기는 통과한다", () => {
    expect(validateImageFile(fakeFile("image/png", MAX_IMAGE_BYTES))).toBeNull();
  });
});

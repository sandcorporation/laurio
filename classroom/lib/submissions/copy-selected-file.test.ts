// 고른 뒤 원본이 바뀌어도 보낸 것은 선택 당시 내용이고, 읽기 실패는 다시 고르라고 말한다 (#953).
import { describe, expect, test, vi } from "vitest";

import { copySelectedFile, FileReadError } from "./upload-failure";

describe("copySelectedFile", () => {
  test("이름·type 을 지키고 내용을 복사한다", async () => {
    const copy = await copySelectedFile(new File(["print(1)"], "a.py", { type: "text/x-python" }));
    expect(copy.name).toBe("a.py");
    expect(copy.type).toBe("text/x-python");
    expect(await copy.text()).toBe("print(1)");
  });

  test("원본을 읽지 못하면 다시 고르라고 하고 file_changed 로 남긴다", async () => {
    const file = new File(["x"], "a.py");
    vi.spyOn(file, "arrayBuffer").mockRejectedValue(new DOMException("changed", "NotReadableError"));
    const error = await copySelectedFile(file).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(FileReadError);
    expect((error as FileReadError).message).toContain("파일을 다시 선택해주세요");
    expect((error as FileReadError).failure.tags.upload_failure).toBe("file_changed");
  });
});

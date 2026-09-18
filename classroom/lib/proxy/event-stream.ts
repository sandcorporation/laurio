// 실시간 신호 SSE(ADR-0046)를 브라우저로 중계할 때, 위쪽이 스트림 중간에
// 끊기는 것을 오류가 아니라 스트림의 끝으로 다룬다(2026-09-18, GlitchTip 55).
//
// 배포가 이벤트 서비스를 바꿔 끼우면 열려 있던 스트림이 전부 소켓째 끊기고,
// undici 가 본문을 `TypeError: terminated`(원인 `other side closed`)로 깨뜨린다.
// 그 본문을 그대로 넘기면 Next 가 `failed to pipe response` 로 받아 오류로
// 보고한다 — prod 에서 배포마다 열린 스트림 수만큼 쌓였다. 끊김 자체는 예정된
// 일이다: 브라우저의 EventSource 는 스트림이 끝나면 다시 붙고, 그 사이 화면은
// 폴링으로 물러나 있다(ADR-0046 「신호는 진실의 출처가 아니다」). 이벤트
// 서비스 자신의 오류는 백엔드 프로젝트가 따로 받는다.
//
// 브라우저가 먼저 떠나는 쪽은 그대로 위쪽까지 취소를 넘긴다 — 끝나지 않는
// 요청이 이벤트 서비스에 쌓이지 않게 하는 것이 `forward.ts` 의 신호 전달과
// 같은 목적이다.

export function endQuietlyOnUpstreamError(
  upstream: ReadableStream<Uint8Array>,
): ReadableStream<Uint8Array> {
  const reader = upstream.getReader();
  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const { done, value } = await reader.read();
        if (done) controller.close();
        else controller.enqueue(value);
      } catch {
        controller.close();
      }
    },
    cancel(reason) {
      return reader.cancel(reason);
    },
  });
}

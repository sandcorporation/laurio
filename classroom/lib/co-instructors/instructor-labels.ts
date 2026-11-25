// 강사 줄 단추의 화면 낭독기 이름(#1441 10번). 이름 끝이 「이」로 끝나는 사람(예: 공동이)이면
// 「공동이 소유권 넘기기」가 주어로 들린다 — 대상은 「에게」, 내보내기는 역할을 앞에 붙여 목적어로 읽히게 한다.
// 「에게」는 받침에 따라 갈리지 않아 이름을 어떻게 끝내도 한 꼴이다.

export function transferButtonLabel(name: string): string {
  return `${name}에게 소유권 넘기기`;
}

export function removeButtonLabel(name: string): string {
  return `공동 강사 ${name} 내보내기`;
}

export function cancelTransferButtonLabel(name: string): string {
  return `${name}에게 보낸 소유권 이전 요청 취소`;
}

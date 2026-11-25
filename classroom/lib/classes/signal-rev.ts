// 클래스 상세가 강사 쪽 변경 신호(`instructors-changed`)로 클래스를 다시 읽는 판단 (#1484 ④, #1496 ③④). 번호는 백엔드가
// 변경마다 하나 올려 신호 본문과 클래스 응답에 같은 값으로 싣는다 — 시간 창이 아니라 「이미 읽은 번호인가」로 같은 변경의
// 재조회를 하나로 모은다. 겹쳐 배포 중의 옛 서버는 번호를 싣지 않는다 — 번호 없는 신호는 「한 번 더 읽을 것」으로만 세고,
// 번호 없는 응답은 그 요청을 보낼 때까지 본 신호를 읽은 것으로 친다. 서버가 채울 수 없는 번호를 만들지 않는다.
// 재조회의 끝은 성공·실패 모두 받는다 — 실패가 「읽는 중」을 붙잡아 두면 다음 신호를 놓친다.

export { changeRev as signalRev } from "../events/same-change";

export class ClassSignalReload {
  /** 신호에서 본 가장 큰 번호. */
  private seenRev = 0;
  /** 읽은 클래스 응답이 담은 번호. */
  private loadedRev = 0;
  /** 번호 없는 신호가 와서 한 번 더 읽어야 한다. */
  private unnumbered = false;
  private inFlight = false;
  /** 지금 읽는 요청을 보낼 때까지 본 번호 — 번호 없는 응답은 여기까지를 읽은 것으로 친다. */
  private revAtRequest = 0;
  /** 읽기를 부른 신호의 수 — 명령이 도는 사이 그런 신호가 왔는지 가른다. */
  private demands = 0;

  /** 신호 하나를 받았다 — 지금 읽기를 시작해야 하면 참. */
  signal(rev: number | null): boolean {
    if (rev === null) {
      this.unnumbered = true;
      this.demands += 1;
    } else if (rev > this.seenRev) {
      this.seenRev = rev;
      if (rev > this.loadedRev) this.demands += 1;
    }
    return this.due();
  }

  /** 읽는 중이 아니고, 읽을 것이 남았는가. */
  due(): boolean {
    return !this.inFlight && (this.unnumbered || this.seenRev > this.loadedRev);
  }

  get reading(): boolean {
    return this.inFlight;
  }

  /** 읽기를 보낸다(어느 길이든). */
  started(): void {
    this.inFlight = true;
    this.unnumbered = false;
    this.revAtRequest = this.seenRev;
  }

  /** 응답이 왔다 — 응답의 번호(없으면 null). 그 사이 더 읽을 것이 왔으면 참(한 번 더 읽는다). */
  succeeded(responseRev: number | null): boolean {
    this.inFlight = false;
    this.loadedRev = Math.max(this.loadedRev, responseRev ?? this.revAtRequest);
    return this.due();
  }

  /** 읽기가 실패했다 — 읽는 중을 푼다. 곧바로 다시 두드리지 않는다: 다음 신호·재연결·폴링이 다시 읽는다. */
  failed(): void {
    this.inFlight = false;
  }

  /** 내 명령이 시작될 때의 표식 — 끝날 때 `signalSince` 에 넘긴다. */
  commandMark(): number {
    return this.demands;
  }

  /** 명령이 도는 사이 읽기를 부른 신호가 왔는가 — 왔으면 그 신호 길이 읽는다(읽는 중이거나 곧 읽는다). */
  signalSince(mark: number): boolean {
    return this.demands > mark;
  }
}

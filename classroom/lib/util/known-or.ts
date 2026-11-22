// 백엔드가 닫힌 열거에 값을 더하면, 배포 창에 열려 있던 옛 화면은 모르는 값을 받는다(#1335).
// 응답 값으로 지도를 읽을 때는 이 함수로 읽어 모르는 값이 중립 모양으로 그려지게 한다.
export function knownOr<K extends string, V>(map: Readonly<Record<K, V>>, key: string, fallback: V): V {
  return Object.prototype.hasOwnProperty.call(map, key) ? map[key as K] : fallback;
}

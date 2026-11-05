// 시연 영상 링크(#910)를 보인다 — 서버·클라이언트 어느 쪽에서도 쓸 수 있는 순수 컴포넌트다.
//
// 유튜브는 뽑은 id 로 만든 nocookie 임베드, 그 밖의 주소는 새 창 링크다. iframe src 에
// 받은 URL 은 들어가지 않는다(`lib/submissions/video-link.ts`).
import { isSafeVideoLink, youtubeEmbedUrl, youtubeVideoId } from "@/lib/submissions/video-link";

export function VideoLinkView({
  url,
  label,
  startSeconds = 0,
  testId,
  className = "w-64",
}: {
  url: string;
  label: string;
  startSeconds?: number;
  testId: string;
  className?: string;
}) {
  const id = youtubeVideoId(url);
  const embed = id !== null ? youtubeEmbedUrl(id, startSeconds) : null;
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-ink/60">{label}</span>
      {embed !== null ? (
        <iframe
          // 시작 위치가 바뀌면 새로 불러와 그 시각부터 다시 재생한다.
          key={embed}
          src={embed}
          title={label}
          loading="lazy"
          allow="encrypted-media; picture-in-picture"
          allowFullScreen
          referrerPolicy="strict-origin-when-cross-origin"
          className={`aspect-video border border-rule ${className}`}
          data-testid={testId}
          data-embed="youtube"
        />
      ) : isSafeVideoLink(url) ? (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs underline"
          data-testid={testId}
          data-embed="link"
        >
          영상 열기
        </a>
      ) : null}
    </div>
  );
}

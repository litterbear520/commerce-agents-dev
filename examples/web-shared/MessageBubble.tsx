export function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="user-bubble max-w-[72%] px-3.5 py-2 text-[14.5px] leading-normal">{text}</div>
    </div>
  );
}

export function AssistantText({ text, streaming }: { text: string; streaming?: boolean }) {
  if (!text && !streaming) return null;
  // 正文先按纯文本渲染；Markdown 组件是 Step 25 的内容。
  return (
    <div className={`leading-relaxed text-(--ink) ${streaming ? "streaming-caret" : ""}`}>
      {text}
    </div>
  );
}

export function ErrorBubble({ text }: { text: string }) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-(--danger)/40 bg-(--danger-soft) px-3 py-2 text-[13px] leading-relaxed text-(--danger)"
    >
      {text}
    </div>
  );
}

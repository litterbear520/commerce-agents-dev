"use client";

import type { ReactNode } from "react";
import { AssistantText, ErrorBubble, UserBubble } from "./MessageBubble";
import type { AssistantChatItem, ChatItem, UISegment } from "./protocol";
import { Suggestions } from "./Suggestions";

export interface TranscriptProps {
  items: ChatItem[];
  busy: boolean;
  send: (text: string) => void;
  renderBlock: (segment: UISegment, item: AssistantChatItem) => ReactNode;
  gap?: string;
}

/** 回复还在生成时下面显示什么：第一个字出来之前是一段微光。 */
export function ActivityLine({ item }: { item: AssistantChatItem }) {
  if (item.segments.length) return null;
  return (
    <div role="status" aria-label="正在处理" className="flex flex-col gap-2">
      <div className="ac-skeleton h-4 w-3/5 rounded" />
      <div className="ac-skeleton h-4 w-2/5 rounded" />
    </div>
  );
}

export function Transcript({ items, busy, send, renderBlock, gap = "gap-3" }: TranscriptProps) {
  return items.map((item, index) =>
    item.kind === "user" ? (
      <UserBubble key={index} text={item.text} />
    ) : (
      <div key={index} data-turn={item.turn} className={`flex flex-col ${gap}`}>
        {item.segments.map((segment, i) => {
          if (segment.type === "text") {
            const last = item.pending && i === item.segments.length - 1;
            return <AssistantText key={i} text={segment.text} streaming={last} />;
          }
          if (segment.type === "error") return <ErrorBubble key={i} text={segment.text} />;
          return (
            <div key={segment.slotKey} data-component={segment.block.component}>
              {renderBlock(segment, item)}
            </div>
          );
        })}
        {item.pending ? <ActivityLine item={item} /> : null}
        {!item.pending && index === items.length - 1 ? (
          <Suggestions suggestions={item.suggestions} onPick={send} disabled={busy} />
        ) : null}
      </div>
    ),
  );
}

"use client";

import { useState } from "react";
import { Icon } from "./icons";

const VARIANTS = {
  /** 店面页面底部的输入区：一个宽松的输入框，发送箭头在框里。 */
  dock: {
    form: "items-center gap-2 rounded-[16px] border border-(--line-strong) bg-(--card) py-1.5 pl-4 pr-1.5 shadow-(--shadow) transition-colors focus-within:border-(--accent)",
    input: "bg-transparent py-1.5 text-[16px]",
    button: "h-9 w-9 rounded-[11px]",
  },
};

export function Composer({
  send,
  ready,
  busy,
  label,
  placeholder,
  variant = "dock",
  className = "",
}: {
  send: (text: string) => void;
  ready: boolean;
  busy: boolean;
  label: string;
  placeholder: string;
  variant?: keyof typeof VARIANTS;
  className?: string;
}) {
  const [draft, setDraft] = useState("");

  const submit = () => {
    if (!draft.trim() || busy || !ready) return;
    send(draft);
    setDraft("");
  };

  return (
    <form
      className={`flex ${VARIANTS[variant].form} ${className}`}
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <textarea
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            submit();
          }
        }}
        rows={1}
        aria-label={label}
        placeholder={busy ? "正在处理…" : placeholder}
        className={`max-h-40 min-w-0 flex-1 resize-none text-(--ink) outline-none transition placeholder:text-(--ink-soft)/70 ${VARIANTS[variant].input}`}
      />
      <button
        type="submit"
        disabled={busy || !ready || !draft.trim()}
        aria-label="发送"
        className={`grid shrink-0 place-items-center bg-(--ink) text-(--surface) transition hover:brightness-110 disabled:opacity-35 ${VARIANTS[variant].button}`}
      >
        <Icon name="arrow-up" size={16} />
      </button>
    </form>
  );
}

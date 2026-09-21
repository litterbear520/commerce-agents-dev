"use client";

/** 对话旁边的购物袋（购物车、行程、订单、占座），以及它的行用到的那些零件。 */
// 项目中对应 examples/web-shared/storefront/bag.tsx
// 当前跳过 BagPanel 顶部的关闭按钮（要 ui.tsx 的 IconButton，Step 25 补）

import type { ReactNode } from "react";
import { Icon } from "../icons";
import { useStoreFrame } from "./frame";

/**
 * 顶部是件数，中间是各行，底部留给合计和主操作。行和底部由各个垂直行业自己渲染；
 * 改数量和结算都作为消息走对话。
 */
export function BagPanel({
  title,
  count,
  empty,
  isEmpty,
  footer,
  children,
}: {
  title: string;
  /** 「1 件商品」「2 个预订」；变化时会弹一下。 */
  count: string;
  /** 购物袋为空时的占位内容：提示状态和可以问助手什么。 */
  empty: ReactNode;
  isEmpty: boolean;
  footer: ReactNode;
  children: ReactNode;
}) {
  return (
    <>
      <div className="flex items-center gap-2 border-b border-(--line) px-[18px] py-3.5">
        <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-(--ink)">{title}</h2>
        <span
          key={count}
          data-cart-target
          className="ac-pop rounded-full bg-(--well) px-2 py-0.5 text-[12px] font-semibold tabular-nums text-(--ink-2)"
        >
          {count}
        </span>
      </div>
      <div className="panel-scroll min-h-0 flex-1 overflow-y-auto px-[18px] py-3.5">
        {isEmpty ? (
          <div className="mt-10 px-4 text-center text-[13.5px] leading-relaxed text-(--ink-soft)">
            {empty}
          </div>
        ) : (
          children
        )}
      </div>
      <div className="border-t border-(--line) px-[18px] pb-[18px] pt-3.5">{footer}</div>
    </>
  );
}

/** 主操作上面的小计行。 */
export function TotalRow({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: ReactNode;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[13.5px] text-(--ink-2)">{label}</span>
        <span className="text-[18px] font-bold tabular-nums tracking-[-0.01em] text-(--ink)">
          {value}
        </span>
      </div>
      {note ? <p className="mt-0.5 text-right text-[11.5px] text-(--ink-soft)">{note}</p> : null}
    </div>
  );
}

/** 面板底部或卡片下方的操作入口：点击后向助手发一条消息。 */
export function AskLink({ label, prompt }: { label: string; prompt: string }) {
  const { ask } = useStoreFrame();
  return (
    <button
      type="button"
      onClick={() => ask(prompt)}
      className="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-(--accent-ink) transition-colors hover:text-(--accent)"
    >
      <Icon name="spark" size={13} className="text-(--accent)" />
      {label}
    </button>
  );
}

/**
 * 一行的数量控件。每按一下都是一条发给助手的消息，所以回复还在流式输出时它是禁用的；
 * 数的不是商品本身时，`unit` 说明数的是什么（「晚」「位」）。
 */
export function Stepper({
  quantity,
  unit,
  itemTitle,
  onChange,
}: {
  quantity: number;
  unit?: string;
  itemTitle: string;
  /** 用新数量调用；0 表示移除。 */
  onChange: (quantity: number) => void;
}) {
  const busy = useStoreFrame().chat?.busy ?? false;
  const units = unit ? ` ${unit}` : "";
  return (
    <div className="flex items-center rounded-full border border-(--line-strong) bg-(--card)">
      <button
        type="button"
        disabled={busy}
        onClick={() => onChange(quantity - 1)}
        aria-label={unit ? `减少 ${itemTitle} 的${unit}数` : `减少 ${itemTitle} 的数量`}
        className="px-2.5 py-0.5 text-sm text-(--ink-soft) hover:text-(--ink) disabled:opacity-40"
      >
        −
      </button>
      <span className="min-w-6 text-center text-[12.5px] font-semibold tabular-nums text-(--ink)">
        {quantity}
        {units}
      </span>
      <button
        type="button"
        disabled={busy}
        onClick={() => onChange(quantity + 1)}
        aria-label={unit ? `增加 ${itemTitle} 的${unit}数` : `增加 ${itemTitle} 的数量`}
        className="px-2.5 py-0.5 text-sm text-(--ink-soft) hover:text-(--ink) disabled:opacity-40"
      >
        +
      </button>
    </div>
  );
}

export function RemoveLink({ itemTitle, onClick }: { itemTitle: string; onClick: () => void }) {
  const busy = useStoreFrame().chat?.busy ?? false;
  return (
    <button
      type="button"
      disabled={busy}
      onClick={onClick}
      aria-label={`移除 ${itemTitle}`}
      className="text-[12px] text-(--ink-soft) underline-offset-2 hover:text-(--danger) hover:underline disabled:opacity-40"
    >
      移除
    </button>
  );
}

/** 助手已展示结算卡后，主操作变为滚动到那张卡。 */
export function CheckoutButton({
  staged,
  disabled,
  prompt,
}: {
  staged: boolean;
  disabled: boolean;
  prompt: string;
}) {
  const { ask } = useStoreFrame();
  if (staged && !disabled) {
    return (
      <button
        type="button"
        onClick={() => {
          const cards = document.querySelectorAll("[data-checkout-card]");
          const card = cards[cards.length - 1];
          if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
          else ask("再给我看一遍结算卡。");
        }}
        className="mt-3 w-full rounded-(--radius) border border-(--line-strong) bg-(--card) py-2.5 text-[14px] font-semibold text-(--ink) transition hover:border-(--accent)"
      >
        查看结算卡
      </button>
    );
  }
  return (
    <button
      type="button"
      onClick={() => ask(prompt)}
      disabled={disabled}
      className="btn-primary mt-3 w-full"
    >
      结算
    </button>
  );
}

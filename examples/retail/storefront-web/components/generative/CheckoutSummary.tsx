"use client";

import { useId } from "react";
import { formatMoney, safeHandoffs } from "web-shared";
import type { CheckoutPayload } from "@/lib/types";

export default function CheckoutSummary({ payload }: { payload: CheckoutPayload }) {
  const cart = payload.cart;
  const handoffs = safeHandoffs(payload.handoffs);
  // 好几张结算卡可以跨轮次同时存在，所以 describedby 的 id 按卡片生成。
  const handoffNoteId = useId();
  return (
    <section
      data-checkout-card
      className="rounded-2xl border-2 border-(--accent) bg-(--card) p-4 shadow-(--shadow-sm)"
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[15px] font-semibold text-(--ink)">可以结算了</h3>
        <div className="flex items-center gap-1.5">
          <span className="whitespace-nowrap rounded-full border border-(--line) bg-(--well)/60 px-2.5 py-0.5 text-[11px] font-semibold text-(--ink-soft)">
            未扣款
          </span>
          {payload.fulfillment_method ? (
            <span className="rounded-full bg-(--accent-soft) px-2.5 py-0.5 text-[13px] font-semibold capitalize text-(--ink)">
              {payload.fulfillment_method}
            </span>
          ) : null}
        </div>
      </div>
      {payload.note ? <p className="mt-1 text-[13px] text-(--ink-soft)">{payload.note}</p> : null}
      <div className="mt-3 space-y-2 rounded-lg bg-(--well)/60 p-3 text-sm">
        {cart.items.map((item) => (
          <div key={item.product_id} className="flex justify-between gap-2">
            <span className="line-clamp-1 text-(--ink)" title={item.title}>
              {item.title} × {item.quantity}
            </span>
            <span className="shrink-0 text-(--ink)">{formatMoney(item.line_total)}</span>
          </div>
        ))}
        <div className="flex justify-between border-t border-(--line) pt-1.5 text-base font-bold text-(--ink)">
          <span>预计总计</span>
          <span>{formatMoney(cart.subtotal, cart.currency)}</span>
        </div>
        <p className="text-[11px] leading-snug text-(--ink-soft)">
          不含运费和税；最终金额在结算页显示。
        </p>
      </div>
      {handoffs.length ? (
        // 后端说明了付款在哪里完成（一个托管结账 URL，或者每个卖家一条）。
        <div className="mt-3 flex flex-col gap-2">
          {handoffs.map((h) => (
            <a
              key={h.url}
              href={h.url}
              target="_blank"
              rel="noopener noreferrer"
              aria-describedby={handoffNoteId}
              className="w-full rounded-xl bg-(--accent) py-2.5 text-center text-sm font-bold text-(--ink)"
            >
              {h.label ?? (h.seller ? `去 ${h.seller} 结算` : "去结算")}
            </a>
          ))}
        </div>
      ) : (
        // 设成 disabled，免得给辅助技术一个能聚焦但什么都不做的控件。
        <button
          disabled
          aria-disabled
          aria-describedby={handoffNoteId}
          className="mt-3 w-full cursor-not-allowed rounded-xl bg-(--accent) py-2.5 text-sm font-bold text-(--ink) opacity-90"
          title="这里不扣款。付款在你结算时发生。"
        >
          去结算
        </button>
      )}
      <p id={handoffNoteId} className="mt-2 text-center text-[11px] text-(--ink-soft)/80">
        这里不扣款。付款在你结算时发生。
      </p>
    </section>
  );
}

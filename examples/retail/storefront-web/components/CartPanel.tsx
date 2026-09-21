"use client";

import { formatMoney, optionValuesLabel } from "web-shared";
import type { CartPayload } from "@/lib/types";
import { ProductTitle } from "./ProductTile";

/** 停靠在侧边的购物车。改数量和结算都是发给助手的消息，所以每一次写入都由它经手。 */
// 项目中对应 examples/retail/storefront-web/components/CartPanel.tsx
// 当前跳过 Stepper / RemoveLink / 免运费进度条 —— 它们要 StoreShell 的 ask()，是 Step 25 的内容
export default function CartPanel({
  cart,
  checkoutStaged = false,
}: {
  cart: CartPayload | null;
  checkoutStaged?: boolean;
}) {
  const items = cart?.items ?? [];
  const count = cart?.item_count ?? 0;
  return (
    <section className="flex h-full flex-col p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-[15px] font-semibold text-(--ink)">购物车</h2>
        <span className="text-[13px] text-(--ink-soft)">{count} 件商品</span>
      </div>
      {items.length === 0 ? (
        <p className="mt-6 text-center text-[13px] leading-relaxed text-(--ink-soft)">
          购物车还是空的。
          <br />
          店里有什么，问 ACME 助手就行。
        </p>
      ) : (
        <ul className="mt-3 flex-1 divide-y divide-(--line)">
          {items.map((item) => (
            <li key={item.product_id} className="ac-reveal py-3 first:pt-0">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <ProductTitle
                    title={item.title}
                    className="line-clamp-3 text-[13.5px] font-semibold leading-snug text-(--ink)"
                  />
                  {optionValuesLabel(item) ? (
                    <div className="text-[11.5px] text-(--ink-soft)">{optionValuesLabel(item)}</div>
                  ) : null}
                  <div className="text-[11.5px] text-(--ink-soft)">数量 {item.quantity}</div>
                </div>
                <div className="shrink-0 text-right">
                  <div className="text-[14px] font-bold tabular-nums text-(--ink)">
                    {formatMoney(item.line_total)}
                  </div>
                  {item.quantity > 1 ? (
                    <div className="text-[11px] text-(--ink-soft)">单价 {formatMoney(item.price)}</div>
                  ) : null}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-4 border-t border-(--line) pt-3">
        <div className="mb-2.5 flex items-baseline justify-between text-[14px] text-(--ink)">
          <span>小计</span>
          <span className="font-bold tabular-nums">
            {formatMoney(cart?.subtotal ?? 0, cart?.currency)}
          </span>
        </div>
        <p className="text-center text-[12px] text-(--ink-soft)">
          {checkoutStaged
            ? "结算卡已经在对话里了。"
            : "跟助手说「帮我结算」就能拿到结算卡。"}
        </p>
      </div>
    </section>
  );
}

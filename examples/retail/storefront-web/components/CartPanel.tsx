"use client";

import {
  AskLink,
  BagPanel,
  CheckoutButton,
  formatMoney,
  optionValuesLabel,
  RemoveLink,
  Stepper,
  TotalRow,
  useStoreFrame,
} from "web-shared";
import type { CartItem, CartPayload } from "@/lib/types";
import { ProductTitle } from "./ProductTile";

/** 购物车行在消息中的称呼，如「ACME 睡眠混合床垫（queen）」。 */
function lineName(item: CartItem): string {
  const chosen = optionValuesLabel(item);
  return chosen ? `${item.title}（${chosen}）` : item.title;
}

/** 停靠在侧边的购物车。改数量和结算都是发给助手的消息，所以每一次写入都由它经手。 */
// 项目中对应 examples/retail/storefront-web/components/CartPanel.tsx
// 当前跳过商品图、品牌行、配送承诺（都要商品目录索引）和免运费进度条（要 storePolicy）
export default function CartPanel({
  cart,
  checkoutStaged = false,
}: {
  cart: CartPayload | null;
  checkoutStaged?: boolean;
}) {
  const { ask } = useStoreFrame();
  const items = cart?.items ?? [];
  const count = cart?.item_count ?? 0;

  return (
    <BagPanel
      title="购物车"
      count={`${count} 件商品`}
      isEmpty={items.length === 0}
      empty={
        <>
          购物车还是空的。
          <br />
          店里有什么，问 ACME 助手就行。
        </>
      }
      footer={
        <>
          <TotalRow
            label={count ? `小计 · ${count} 件商品` : "小计"}
            value={formatMoney(cart?.subtotal ?? 0, cart?.currency)}
          />
          <CheckoutButton
            staged={checkoutStaged}
            disabled={items.length === 0}
            prompt="帮我把购物车结算了。"
          />
          {items.length ? (
            <div className="mt-2.5 flex justify-center">
              <AskLink label="问问这个购物车" prompt="帮我看看购物车：有没有漏掉的，或者值得换的？" />
            </div>
          ) : null}
        </>
      }
    >
      <ul className="divide-y divide-(--line)">
        {items.map((item) => (
          <li key={item.product_id} className="ac-reveal py-3 first:pt-0">
            <div className="min-w-0 flex-1">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  {/* 两行截断会把长名字砍掉一半，这里放到三行。 */}
                  <ProductTitle
                    title={item.title}
                    className="line-clamp-3 text-[13.5px] font-semibold leading-snug text-(--ink)"
                  />
                  {optionValuesLabel(item) ? (
                    <div className="text-[11.5px] text-(--ink-soft)">{optionValuesLabel(item)}</div>
                  ) : null}
                </div>
                <div className="shrink-0 text-right">
                  <div className="text-[14px] font-bold tabular-nums text-(--ink)">
                    {formatMoney(item.line_total)}
                  </div>
                  {item.quantity > 1 ? (
                    <div className="text-[11px] text-(--ink-soft)">
                      单价 {formatMoney(item.price)}
                    </div>
                  ) : null}
                </div>
              </div>
              <div className="mt-2 flex items-center gap-2.5">
                <Stepper
                  quantity={item.quantity}
                  itemTitle={lineName(item)}
                  onChange={(quantity) =>
                    ask(
                      quantity < 1
                        ? `把 ${lineName(item)} 从购物车里移除。`
                        : `把 ${lineName(item)} 的数量改成 ${quantity}。`,
                    )
                  }
                />
                <RemoveLink
                  itemTitle={lineName(item)}
                  onClick={() => ask(`把 ${lineName(item)} 从购物车里移除。`)}
                />
              </div>
            </div>
          </li>
        ))}
      </ul>
    </BagPanel>
  );
}

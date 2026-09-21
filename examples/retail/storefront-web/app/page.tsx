"use client";

import { useCallback, useEffect, useState } from "react";
import { type AgentEvent, Composer, formatMoney, useAgentTurn, useSession } from "web-shared";
import CartPanel from "@/components/CartPanel";
import Chat from "@/components/Chat";
import { api, UNREACHABLE } from "@/lib/api";
import type { CartPayload } from "@/lib/types";

const ASSISTANT = "ACME 助手";

function Wordmark() {
  return (
    <span className="flex items-center gap-2.5 pr-1">
      <span
        aria-hidden
        className="grid h-[30px] w-[30px] place-items-center rounded-lg bg-(--ink) text-[15px] font-bold text-(--surface)"
      >
        A
      </span>
      <span className="text-[17px] font-bold tracking-[-0.02em] text-(--ink)">ACME</span>
    </span>
  );
}

export default function StorefrontPage() {
  const session = useSession(api);
  const [cart, setCart] = useState<CartPayload | null>(null);
  // 一张摆好的结算卡占住面板的主操作，直到购物车再次变化。
  const [checkoutStaged, setCheckoutStaged] = useState(false);

  const handleCartUpdate = useCallback((next: CartPayload) => {
    setCart(next);
    setCheckoutStaged(false);
  }, []);

  const onEvent = useCallback(
    (event: AgentEvent) => {
      if (event.type === "cart_update") handleCartUpdate(event.data.cart as CartPayload);
      else if (event.type === "ui" && event.data.component === "checkout") setCheckoutStaged(true);
    },
    [handleCartUpdate],
  );

  const chat = useAgentTurn(api, { ...session, unreachable: UNREACHABLE, onEvent });

  useEffect(() => {
    if (session.sessionId) void api.fetchCart<CartPayload>().then((next) => next && setCart(next));
  }, [session.sessionId]);

  const count = cart?.item_count ?? 0;

  // 布局在这里手写；Step 25 换成 web-shared 的 StoreShell。
  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 items-center justify-between border-b border-(--line) bg-(--chrome) px-4 py-2.5">
        <Wordmark />
        <span className="text-[13px] text-(--ink-soft)">
          购物车 · {count} 件
          {count ? (
            <span className="ml-1.5 font-semibold text-(--ink)">
              {formatMoney(cart?.subtotal ?? 0, cart?.currency)}
            </span>
          ) : null}
        </span>
      </header>
      <div className="flex min-h-0 flex-1">
        <main className="panel-scroll min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex w-full max-w-[760px] flex-col gap-5 px-4 py-6">
            <Chat chat={chat} onCartUpdate={handleCartUpdate} />
          </div>
        </main>
        <aside className="panel-scroll hidden w-[340px] shrink-0 overflow-y-auto border-l border-(--line) bg-(--card) lg:block">
          <CartPanel cart={cart} checkoutStaged={checkoutStaged} />
        </aside>
      </div>
      <div className="shrink-0 border-t border-(--line) bg-(--chrome) px-4 py-3">
        <div className="mx-auto w-full max-w-[760px]">
          <Composer
            send={chat.send}
            ready={chat.ready}
            busy={chat.busy}
            label={`给 ${ASSISTANT} 发消息`}
            placeholder="问问商品、方案或者订单…"
          />
        </div>
      </div>
    </div>
  );
}

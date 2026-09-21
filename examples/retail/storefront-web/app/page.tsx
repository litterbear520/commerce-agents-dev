"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  type AgentEvent,
  Composer,
  formatMoney,
  FrameContext,
  useAgentTurn,
  useSession,
} from "web-shared";
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
  // 已展示的结算卡占住面板的主操作，直到购物车再次变化。
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
  const { send } = chat;

  /** 页面上每一个交接都走这里。 */
  const ask = useCallback((message: string) => void send(message), [send]);
  const frame = useMemo(
    () => ({ chat, assistantName: ASSISTANT, ask, closePanel: () => {} }),
    [chat, ask],
  );

  useEffect(() => {
    if (session.sessionId) void api.fetchCart<CartPayload>().then((next) => next && setCart(next));
  }, [session.sessionId]);

  const count = cart?.item_count ?? 0;

  // 布局在这里手写；Step 25 建好 web-shared/storefront/Shell.tsx 之后换成 StoreShell。
  return (
    <FrameContext.Provider value={frame}>
      <div className="flex h-dvh flex-col text-(--ink)">
        <header className="flex h-[58px] shrink-0 items-center justify-between border-b border-(--line) bg-(--chrome) px-3 sm:px-5">
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
          <main className="panel-scroll min-w-0 flex-1 overflow-y-auto px-4 pb-8 pt-6 sm:px-6">
            <div className="mx-auto flex max-w-[760px] flex-col gap-5 text-[15.5px]">
              <Chat chat={chat} onCartUpdate={handleCartUpdate} />
            </div>
          </main>
          <aside className="hidden w-[340px] shrink-0 flex-col border-l border-(--line) bg-(--card) lg:flex">
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
    </FrameContext.Provider>
  );
}

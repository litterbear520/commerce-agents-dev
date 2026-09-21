"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { type AgentEvent, Composer, FrameContext, useAgentTurn, useSession } from "web-shared";
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

  // 页面上每一个交接都走这里。源码在 web-shared/storefront/Shell.tsx（StoreShell），
  // 那里还会先关抽屉、切回对话视图；Step 25 搬回。
  const ask = useCallback((message: string) => void send(message), [send]);
  const frame = useMemo(
    () => ({ chat, assistantName: ASSISTANT, ask, closePanel: () => {} }),
    [chat, ask],
  );

  useEffect(() => {
    if (session.sessionId) void api.fetchCart<CartPayload>().then((next) => next && setCart(next));
  }, [session.sessionId]);

  // 下面的布局是源码 StoreShell 的子集：去掉了视图切换、Activity、购物车按钮和抽屉、
  // 账号面板；侧栏只在 xl 以上停靠。Step 25 建好 web-shared/storefront/Shell.tsx 之后换成 StoreShell。
  return (
    <FrameContext.Provider value={frame}>
      <div className="flex h-dvh flex-col text-(--ink)">
        <header className="flex h-[58px] shrink-0 items-center gap-2 border-b border-(--line) bg-(--chrome) px-3 sm:gap-5 sm:px-5">
          <div className="flex shrink-0 items-center">
            <Wordmark />
          </div>
        </header>

        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col">
            <main className="min-h-0 flex-1">
              <div className="h-full">
                <Chat chat={chat} onCartUpdate={handleCartUpdate} />
              </div>
            </main>
            <div className="relative shrink-0 px-4 pb-4 pt-2 sm:px-6">
              <div
                aria-hidden
                className="pointer-events-none absolute inset-x-0 -top-6 h-6 bg-linear-to-b from-transparent to-(--ground)"
              />
              <Composer
                send={ask}
                ready={chat.ready}
                busy={chat.busy}
                label={`给 ${ASSISTANT} 发消息`}
                placeholder="问问商品、方案或者订单…"
                className="mx-auto max-w-[760px]"
              />
            </div>
          </div>

          <aside
            aria-label="购物车"
            className="invisible fixed inset-y-0 right-0 z-50 flex w-[min(92vw,380px)] flex-col border-l border-(--line) bg-(--card) xl:visible xl:static xl:z-auto xl:w-[348px] xl:shrink-0"
          >
            <CartPanel cart={cart} checkoutStaged={checkoutStaged} />
          </aside>
        </div>
      </div>
    </FrameContext.Provider>
  );
}

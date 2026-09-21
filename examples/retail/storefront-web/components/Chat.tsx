"use client";

import { type AgentTurn, Transcript } from "web-shared";
import { addToCart } from "@/lib/api";
import type { CartPayload } from "@/lib/types";
import GenerativeBlock from "./generative";

export default function Chat({
  chat,
  onCartUpdate,
}: {
  chat: AgentTurn;
  onCartUpdate: (cart: CartPayload) => void;
}) {
  // 外面两层滚动容器是源码 web-shared/storefront/Chat.tsx（ChatShell）的子集：
  // 去掉了首页（home）、贴底滚动（useStickToBottom）和「最新」按钮；Step 25 搬回。
  return (
    <div className="relative h-full">
      <div className="panel-scroll h-full overflow-y-auto px-4 pb-8 pt-6 sm:px-6">
        <div className="mx-auto flex max-w-[760px] flex-col gap-5 text-[15.5px]">
          <Transcript
            items={chat.items}
            busy={chat.busy}
            send={chat.send}
            renderBlock={(segment) => (
              <GenerativeBlock
                block={segment.block}
                status={segment.status}
                onAdd={async (product) => {
                  const cart = await addToCart(product.product_id);
                  if (cart) onCartUpdate(cart);
                  return cart !== null;
                }}
              />
            )}
          />
        </div>
      </div>
    </div>
  );
}

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
  return (
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
  );
}

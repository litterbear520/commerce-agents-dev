import { AgentApi } from "web-shared";
import type { CartPayload } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const api = new AgentApi(API_URL, "/api");

// 源码指向 `uvicorn retail.api.main:app --app-dir examples --port 8000`（零售 API）；Step 22 改回。
export const UNREACHABLE =
  "连不上 8000 端口上的原型 API。用 " +
  "`uvicorn examples.prototype.app:app --reload --port 8000` 启动它再试一次。";

export async function addToCart(productId: string, quantity = 1): Promise<CartPayload | null> {
  const data = await api.post<{ cart: CartPayload }>("/cart/add", {
    product_id: productId,
    quantity,
  });
  return data?.cart ?? null;
}

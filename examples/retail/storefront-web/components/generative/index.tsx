/** 每个购物展示工具一条。 */
// 项目中对应 examples/retail/storefront-web/components/generative/index.tsx
// 还没做的 comparison / plan / guide / order_status 走 UnknownBlock

import { type GenerativeBlockProps, UnknownBlock } from "web-shared";
import type { CheckoutPayload, Product, ProductsPayload } from "@/lib/types";
import CheckoutSummary from "./CheckoutSummary";
import ProductCarousel from "./ProductCarousel";

export default function GenerativeBlock({
  block,
  status,
  onAdd,
}: GenerativeBlockProps & {
  onAdd?: (product: Product) => boolean | void | Promise<boolean | void>;
}) {
  const partial = status !== "final";
  switch (block.component) {
    case "products":
      return (
        <ProductCarousel payload={block.payload as ProductsPayload} onAdd={onAdd} partial={partial} />
      );
    case "checkout":
      if (partial) return null;
      return <CheckoutSummary payload={block.payload as CheckoutPayload} />;
    default:
      return partial ? null : <UnknownBlock component={block.component} />;
  }
}

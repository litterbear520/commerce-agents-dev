"use client";

import type { Product, ProductsPayload } from "@/lib/types";
import ProductTile from "../ProductTile";

export default function ProductCarousel({
  payload,
  onAdd,
  partial,
}: {
  payload: ProductsPayload;
  onAdd?: (product: Product) => boolean | void | Promise<boolean | void>;
  partial?: boolean;
}) {
  const layout = payload.layout ?? "carousel";
  const items = payload.items ?? [];
  return (
    <section className="rounded-2xl border border-(--line) bg-(--card) p-3 shadow-(--shadow-sm)">
      {payload.title ? (
        <h3 className="mb-3 text-[15px] font-semibold text-(--ink)">{payload.title}</h3>
      ) : null}
      <div
        className={
          layout === "grid"
            ? "grid grid-cols-2 gap-3 sm:grid-cols-3"
            : layout === "list"
              ? "flex flex-col gap-3"
              : "panel-scroll flex gap-3 overflow-x-auto pb-1"
        }
      >
        {items.map(({ product }) => (
          <div key={product.product_id} className="ac-reveal shrink-0">
            <ProductTile product={product} onAdd={onAdd} />
          </div>
        ))}
        {partial ? <div className="ac-skeleton h-[150px] w-48 shrink-0 rounded-xl" /> : null}
      </div>
    </section>
  );
}

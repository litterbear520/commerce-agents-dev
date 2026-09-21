"use client";

import { useState } from "react";
import { hasOptions, optionSummary, optionValuesLabel, priceLabel, useStoreFrame } from "web-shared";
import type { Product } from "@/lib/types";

/** 结尾的括号内容（比如「(48 包装)」）保持不换行，这样截断发生在它前面。 */
export function ProductTitle({ title, className = "" }: { title: string; className?: string }) {
  const match = /^(.*\S)\s+(\([^()]+\))$/.exec(title);
  return (
    <div className={className} title={title}>
      {match ? (
        <>
          {match[1]} <span className="whitespace-nowrap">{match[2]}</span>
        </>
      ) : (
        title
      )}
    </div>
  );
}

export function Rating({ rating, count }: { rating?: number | null; count?: number | null }) {
  if (rating == null) return null;
  // 评分只占一行，这样相邻卡片的价格行能对齐。
  return (
    <span className="whitespace-nowrap text-[13px] text-(--ink-soft)">
      <span className="text-(--star)">★</span> {rating.toFixed(1)}
      {count ? (
        <span className="text-[11px] text-(--ink-soft)/80"> ({count.toLocaleString()})</span>
      ) : null}
    </span>
  );
}

/** 一个变体选了什么，或者一个带选项的商品还需要选什么；其他情况是空串。 */
function optionText(product: Product): string {
  return optionValuesLabel(product) || optionSummary(product);
}

export function OptionLine({ product, className = "" }: { product: Product; className?: string }) {
  const text = optionText(product);
  if (!text) return null;
  return <div className={`truncate text-[11px] text-(--ink-soft) ${className}`}>{text}</div>;
}

/**
 * onAdd 解析出 `false` 表示服务端拒绝了这次写入。带选项的商品不从卡片上加：
 * 按钮把这个选择交给助手，由它跟顾客定下选项，再把变体加进购物车。
 */
export function AddButton({
  product,
  onAdd,
}: {
  product: Product;
  onAdd: (product: Product) => boolean | void | Promise<boolean | void>;
}) {
  const [phase, setPhase] = useState<"idle" | "busy" | "done" | "error">("idle");
  const { ask } = useStoreFrame();
  if (hasOptions(product)) {
    return (
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          ask(`把 ${product.title}（${product.product_id}）加进我的购物车。`);
        }}
        aria-label={`为 ${product.title} 选择规格`}
        className="pointer-events-auto absolute bottom-2 right-2 flex h-8 w-8 items-center justify-center rounded-full bg-(--ink) text-lg font-semibold leading-none text-(--surface) shadow-(--shadow-sm) transition-all hover:scale-105"
      >
        +
      </button>
    );
  }
  return (
    <button
      type="button"
      onClick={async (event) => {
        event.stopPropagation();
        if (phase !== "idle") return;
        setPhase("busy");
        const added = (await onAdd(product)) !== false;
        setPhase(added ? "done" : "error");
        window.setTimeout(() => setPhase("idle"), added ? 1200 : 1600);
      }}
      aria-label={`把 ${product.title} 加入购物车`}
      className={`pointer-events-auto absolute bottom-2 right-2 flex h-8 w-8 items-center justify-center rounded-full text-lg font-semibold leading-none text-(--surface) shadow-(--shadow-sm) transition-all hover:scale-105 ${
        phase === "done" ? "bg-(--ok)" : phase === "error" ? "bg-(--warn)" : "bg-(--ink)"
      } ${phase === "busy" ? "animate-pulse" : ""}`}
    >
      {phase === "done" ? "✓" : phase === "error" ? "!" : "+"}
    </button>
  );
}

export default function ProductTile({
  product,
  selected = false,
  onAdd,
  onOpen,
}: {
  product: Product;
  selected?: boolean;
  onAdd?: (product: Product) => boolean | void | Promise<boolean | void>;
  onOpen?: (product: Product) => void;
}) {
  const clickable = Boolean(onOpen);
  // 源码按 compact / fluid 取 h-16 / h-28 / h-24；这两个 prop 还没接，只留轮播用的一档。
  const imageHeight = "h-24";
  return (
    <div
      className={`relative flex w-48 shrink-0 flex-col overflow-hidden rounded-xl border bg-(--card) shadow-(--shadow-sm) transition-[box-shadow,border-color] duration-200 hover:shadow-md ${
        selected ? "border-(--ink)" : "border-(--line)"
      }`}
    >
      <div
        onClick={clickable ? () => onOpen?.(product) : undefined}
        onKeyDown={clickable ? (event) => event.key === "Enter" && onOpen?.(product) : undefined}
        role={clickable ? "button" : undefined}
        tabIndex={clickable ? 0 : undefined}
        className={`flex flex-1 flex-col rounded-xl focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-(--accent) ${
          clickable ? "cursor-pointer" : ""
        }`}
      >
        <div className="relative">
          {/* 源码这里是 <ProductImage>：有 image_url 就放图，否则放 productGlyph 的占位图。
              商品图和 lib/format 是 Step 23 的内容，先用同高的空块保住布局。 */}
          <div className={`w-full ${imageHeight}`} aria-hidden />
          {product.in_stock === false ? (
            <span className="absolute right-1.5 top-1.5 rounded-full bg-(--ink)/85 px-2 py-0.5 text-[11px] font-medium text-(--surface)">
              缺货
            </span>
          ) : null}
        </div>
        <div className="flex flex-1 flex-col gap-0.5 p-2.5">
          <div className="text-[11px] uppercase tracking-wide text-(--ink-soft)/80">
            {product.brand}
          </div>
          <ProductTitle
            title={product.title}
            className="line-clamp-2 text-[13px] font-medium leading-snug h-9"
          />
          <OptionLine product={product} className="h-[18px] pt-0.5 leading-4" />
          <div className="mt-auto flex items-center justify-between gap-1 pt-0.5">
            <span className="text-sm font-semibold">{priceLabel(product)}</span>
            <Rating rating={product.rating} count={product.review_count} />
          </div>
        </div>
      </div>
      {onAdd && product.in_stock !== false ? (
        // 盖在图片上，但和可点击区域是兄弟节点，这样一个控件不会套在另一个控件里。
        <div className={`pointer-events-none absolute inset-x-0 top-0 ${imageHeight}`}>
          <AddButton product={product} onAdd={onAdd} />
        </div>
      ) : null}
    </div>
  );
}

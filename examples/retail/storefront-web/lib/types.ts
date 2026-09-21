/** 镜像 shopping_agent/types.py 和 tools/presentation.py；详情页的额外字段在垂直行业的 api/ 中定义。 */
// 项目中对应 examples/retail/storefront-web/lib/types.ts
// 当前跳过 ProductDetails、PriceIntelligence、ReviewAspects，
// 以及 comparison / plan / guide / order_status 四个 payload

export interface Product {
  product_id: string;
  title: string;
  brand?: string | null;
  price: number;
  currency?: string;
  rating?: number | null;
  review_count?: number | null;
  category?: string | null;
  labels?: string[];
  attributes?: Record<string, string>;
  in_stock?: boolean;
  short_description?: string | null;
  /** 家族记录上还没选的选项；加进购物车的是它的某个变体。 */
  options?: Record<string, string[]>;
  /** 一个变体在每个选项上的取值。 */
  option_values?: Record<string, string>;
  variant_of?: string | null;
}

export interface CartItem {
  product_id: string;
  title: string;
  price: number;
  quantity: number;
  option_values?: Record<string, string>;
  variant_of?: string | null;
  line_total: number;
}

export interface CartPayload {
  items: CartItem[];
  item_count: number;
  subtotal: number;
  currency: string;
}

// ── 展示层 payload，服务端补全之后流式发出 ────────────────────

export interface ProductsPayload {
  title?: string;
  layout?: "carousel" | "grid" | "list";
  items: { product: Product; reason?: string | null }[];
}

export interface CheckoutHandoff {
  url: string;
  label?: string;
  seller?: string;
}

export interface CheckoutPayload {
  /** 付款不在这个应用里完成时，在哪里完成；由后端填。 */
  handoffs?: CheckoutHandoff[];
  note?: string;
  fulfillment_method?: "delivery" | "pickup" | "shipping";
  cart: CartPayload;
}

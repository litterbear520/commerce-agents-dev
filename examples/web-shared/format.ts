const moneyFormatters = new Map<string, Intl.NumberFormat>();

export function formatMoney(
  value: number,
  currency = "USD",
  options: { whole?: boolean } = {},
): string {
  const key = `${currency}:${options.whole ? 0 : 2}`;
  let formatter = moneyFormatters.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: options.whole ? 0 : 2,
    });
    moneyFormatters.set(key, formatter);
  }
  return formatter.format(value);
}

const plain = new Intl.NumberFormat("en-US");

export function formatNumber(value: number): string {
  return plain.format(value);
}

/** 商品有选项时还能选什么，以及一个变体选了什么。 */
export interface OptionFields {
  price: number;
  currency?: string;
  options?: Record<string, string[]>;
  option_values?: Record<string, string>;
}

/** 该商品是否有可选规格（颜色、尺寸等），即购物车加的是它的某个变体。 */
export function hasOptions(product: Pick<OptionFields, "options">): boolean {
  return Object.keys(product.options ?? {}).length > 0;
}

/** "twin · full · queen · king"，每组选项一段、用 " / " 隔开；没有选项的商品是空串。 */
export function optionSummary(product: Pick<OptionFields, "options">): string {
  return Object.values(product.options ?? {})
    .map((values) => values.join(" · "))
    .join(" / ");
}

/** 变体或购物车行的 "king · slate"；什么都没选时是空串。 */
export function optionValuesLabel(item: Pick<OptionFields, "option_values">): string {
  return Object.values(item.option_values ?? {}).join(" · ");
}

/** 家族记录显示「最低 $349」，它的价格是最便宜的变体；其他商品直接显示价格。 */
export function priceLabel(product: OptionFields): string {
  const money = formatMoney(product.price, product.currency);
  return hasOptions(product) ? `最低 ${money}` : money;
}

export interface HandoffLink {
  url: string;
  label?: string;
  seller?: string;
}

/** 过滤出安全的结账交接链接：只允许 https（开发时也允许 localhost 的 http）。
 * URL 来自后端而非模型；这里再校验一次协议，属于纵深防御。 */
export function safeHandoffs(handoffs: HandoffLink[] | undefined): HandoffLink[] {
  return (handoffs ?? []).filter((h) => {
    try {
      const u = new URL(h.url);
      return (
        u.protocol === "https:" ||
        (u.protocol === "http:" && ["localhost", "127.0.0.1"].includes(u.hostname))
      );
    } catch {
      return false;
    }
  });
}

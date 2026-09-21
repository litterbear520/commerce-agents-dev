import type { UIBlock, UISlotStatus } from "./protocol";

/** 每个应用 `components/generative/index.tsx` 注册表的基础 props；应用自己往上加回调。 */
export interface GenerativeBlockProps {
  block: UIBlock;
  status: UISlotStatus;
}

export function UnknownBlock({ component }: { component: string }) {
  return (
    <p className="rounded-(--radius) border border-(--line) bg-(--card) px-4 py-3 text-[13px] text-(--ink-soft)">
      这个页面还没有「{component}」的视图。
    </p>
  );
}

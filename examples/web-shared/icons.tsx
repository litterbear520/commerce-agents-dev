/** Web 应用的图标集：24px 线性图标画在这里，所以不需要额外的图标包。 */

import type { SVGProps } from "react";

const STROKE = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.7,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

const PATHS = {
  "arrow-up": <path d="M12 19V5M6 11l6-6 6 6" strokeWidth={2} />,
} as const;

export type IconName = keyof typeof PATHS | "spark";

/** `spark` 是助手的标记，也是唯一一个实心图形。 */
export function Icon({
  name,
  size = 18,
  className = "",
  ...rest
}: { name: IconName; size?: number } & Omit<SVGProps<SVGSVGElement>, "name">) {
  if (name === "spark") {
    return (
      <svg viewBox="0 0 24 24" width={size} height={size} fill="currentColor" aria-hidden className={`shrink-0 ${className}`} {...rest}>
        <path d="M12 2.5c.4 4.6 2.4 7.4 7.5 8-5.1.6-7.1 3.4-7.5 8-.4-4.6-2.4-7.4-7.5-8 5.1-.6 7.1-3.4 7.5-8z" />
        <path d="M19 15c.2 2 .9 3 3 3.2-2.1.3-2.8 1.3-3 3.3-.2-2-.9-3-3-3.3 2.1-.2 2.8-1.2 3-3.2z" opacity=".7" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden className={`shrink-0 ${className}`} {...STROKE} {...rest}>
      {PATHS[name]}
    </svg>
  );
}

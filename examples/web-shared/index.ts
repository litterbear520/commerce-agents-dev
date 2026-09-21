/**
 * 每个应用都导入 `base.css`；店面在自己的 globals.css 里定义 `.chip`、`.user-bubble`
 * 和 `.btn-primary`。
 */
// 标了「源码没有」的三行是临时的：源码的 Composer 由 storefront/Shell.tsx 内部用、
// Transcript 由 storefront/Chat.tsx 内部用，FrameContext 由 StoreShell 自己 Provide，
// 都不对外导出。这些文件是 Step 25 的内容，建好之后把那三行删掉。

export { AgentApi } from "./api";
export { Composer } from "./Composer"; // 源码没有
export * from "./format";
export { type GenerativeBlockProps, UnknownBlock } from "./generative";
export { Icon, type IconName } from "./icons";
export type * from "./protocol";
export { type Session, useSession } from "./session";
export { AskLink, BagPanel, CheckoutButton, RemoveLink, Stepper, TotalRow } from "./storefront/bag";
export { useStoreFrame } from "./storefront/frame";
export { FrameContext, type StoreFrame } from "./storefront/frame"; // 源码没有
export { Suggestions } from "./Suggestions";
export { ActivityLine } from "./Transcript";
export { Transcript } from "./Transcript"; // 源码没有
export { type AgentTurn, useAgentTurn } from "./turn";

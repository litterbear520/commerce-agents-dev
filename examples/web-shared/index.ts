/**
 * 每个应用都导入 `base.css`；店面在自己的 globals.css 里定义 `.chip`、`.user-bubble`
 * 和 `.btn-primary`。
 */
// 下面两行源码里没有：源码的 Composer 由 storefront/Shell.tsx 内部用、
// Transcript 由 storefront/Chat.tsx 内部用，都不对外导出。这两个文件是 Step 25 的内容，
// 建好之后这两行删掉。FrameContext 同理——源码由 StoreShell 自己 Provide。

export { AgentApi } from "./api";
export { Composer } from "./Composer";
export * from "./format";
export { type GenerativeBlockProps, UnknownBlock } from "./generative";
export { Icon, type IconName } from "./icons";
export type * from "./protocol";
export { type Session, useSession } from "./session";
export { AskLink, BagPanel, CheckoutButton, RemoveLink, Stepper, TotalRow } from "./storefront/bag";
export { FrameContext, type StoreFrame, useStoreFrame } from "./storefront/frame";
export { Suggestions } from "./Suggestions";
export { ActivityLine, Transcript } from "./Transcript";
export { type AgentTurn, useAgentTurn } from "./turn";

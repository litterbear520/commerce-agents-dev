"use client";

import { createContext, useContext } from "react";
import type { AgentTurn } from "../turn";

/**
 * `StoreShell` 里面的东西不走 props，而是从这里读：对话本身、助手的名字、
 * `ask`（发一条消息，并把对话滚进视野）、`closePanel`（xl 以下的购物袋抽屉）。
 * 默认值让购物袋面板或者主页区块能在 frame 外面单独渲染。
 */
export interface StoreFrame {
  chat: AgentTurn | null;
  assistantName: string;
  ask: (message: string) => void;
  closePanel: () => void;
}

export const FrameContext = createContext<StoreFrame>({
  chat: null,
  assistantName: "ACME 助手",
  ask: () => {},
  closePanel: () => {},
});

export function useStoreFrame(): StoreFrame {
  return useContext(FrameContext);
}

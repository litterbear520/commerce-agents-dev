"use client";

// 项目中对应 examples/web-shared/turn.ts
// 当前跳过 ui_partial 的逐帧节奏（DRIP_MS / schedule / drain / flush）、
// 失败帧的 retrying 状态、tool_call / tool_result / progress 的活动行、
// 追踪面板和记忆基线 —— 这些是 Step 24 的内容

import { type Dispatch, type SetStateAction, useCallback, useRef, useState } from "react";
import type { AgentApi } from "./api";
import type {
  AgentEvent,
  AssistantChatItem,
  AssistantSegment,
  ChatItem,
  UIBlock,
  UISlotStatus,
} from "./protocol";

/** 在 turn 层就地处理，不转发到应用的组件注册表。 */
const CHIPS_COMPONENT = "suggestions";

function eventBlock(event: AgentEvent): UIBlock {
  return { component: String(event.data.component ?? ""), payload: event.data.payload ?? {} };
}

/** key 用轮次 + 组件 + 序号，不用 tool_use id，这样重试时卡片的 DOM 节点不会换。 */
interface Slot {
  key: string;
  component: string;
  status: UISlotStatus;
}

export interface AgentTurnOptions {
  sessionId: string | null;
  unreachable: string;
  /** 在对话视图处理这个事件之前先跑。 */
  onEvent?: (event: AgentEvent, turn: number) => void;
}

export interface AgentTurn {
  items: ChatItem[];
  setItems: Dispatch<SetStateAction<ChatItem[]>>;
  ready: boolean;
  /** 有一条回复正在流式输出。 */
  busy: boolean;
  send: (text: string) => Promise<void>;
  turnCount: number;
  /** 已完成的回复数；每次递增时页面刷新该轮次的最终状态。 */
  completed: number;
}

export function useAgentTurn(api: AgentApi, options: AgentTurnOptions): AgentTurn {
  const { sessionId, unreachable, onEvent } = options;
  const [items, setItems] = useState<ChatItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [turnState, setTurnState] = useState({ turnCount: 0, completed: 0 });
  const turnRef = useRef(0);
  const slotsRef = useRef<Map<string, Slot>>(new Map());
  const ordinals = useRef<Map<string, number>>(new Map());
  const callbacks = useRef({ onEvent });
  callbacks.current = { onEvent };

  const updateTurn = useCallback(
    (turn: number, update: (item: AssistantChatItem) => AssistantChatItem) => {
      setItems((previous) =>
        previous.map((item) =>
          item.kind === "assistant" && item.turn === turn ? update(item) : item,
        ),
      );
    },
    [],
  );

  const commit = useCallback(
    (turn: number, slot: Slot, block: UIBlock, status: UISlotStatus) => {
      slot.status = status;
      updateTurn(turn, (item) => {
        const segments = [...item.segments];
        const index = segments.findIndex((s) => s.type === "ui" && s.slotKey === slot.key);
        const segment: AssistantSegment = { type: "ui", block, slotKey: slot.key, status };
        if (index >= 0) segments[index] = segment;
        else segments.push(segment);
        return { ...item, segments };
      });
    },
    [updateTurn],
  );

  const openSlot = useCallback((turn: number, component: string, status: UISlotStatus) => {
    const ordinal = ordinals.current.get(component) ?? 0;
    ordinals.current.set(component, ordinal + 1);
    const slot: Slot = { key: `${turn}-${component}-${ordinal}`, component, status };
    slotsRef.current.set(slot.key, slot);
    return slot;
  }, []);

  const findSlot = useCallback((component: string) => {
    let found: Slot | undefined;
    for (const slot of slotsRef.current.values()) {
      if (slot.component === component) found = slot;
    }
    return found;
  }, []);

  const handleEvent = useCallback(
    (turn: number, event: AgentEvent) => {
      callbacks.current.onEvent?.(event, turn);
      switch (event.type) {
        case "text_delta": {
          const delta = String(event.data.text ?? "");
          updateTurn(turn, (item) => {
            const segments = [...item.segments];
            const last = segments[segments.length - 1];
            if (last?.type === "text") {
              segments[segments.length - 1] = { type: "text", text: last.text + delta };
            } else {
              segments.push({ type: "text", text: delta });
            }
            return { ...item, segments };
          });
          return;
        }
        case "ui": {
          const block = eventBlock(event);
          if (block.component === CHIPS_COMPONENT) {
            const suggestions = (block.payload as { suggestions?: string[] }).suggestions ?? [];
            updateTurn(turn, (item) => ({ ...item, suggestions }));
            return;
          }
          // 一个不带 stream id 的 final 事件替换掉这个组件已有的卡片。
          const slot = findSlot(block.component) ?? openSlot(turn, block.component, "final");
          commit(turn, slot, block, "final");
          return;
        }
        case "error": {
          const text = String(event.data.message ?? "出了点问题。");
          updateTurn(turn, (item) => ({
            ...item,
            segments: [...item.segments, { type: "error", text }],
          }));
          return;
        }
        default:
          return;
      }
    },
    [commit, findSlot, openSlot, updateTurn],
  );

  const runTurn = useCallback(
    async (userText: string, events: AsyncIterable<AgentEvent>) => {
      const turn = ++turnRef.current;
      slotsRef.current = new Map();
      ordinals.current = new Map();
      setTurnState((state) => ({ ...state, turnCount: turn }));
      setItems((previous) => [
        ...previous,
        { kind: "user", text: userText },
        { kind: "assistant", turn, segments: [], suggestions: [], pending: true },
      ]);
      try {
        for await (const event of events) {
          handleEvent(turn, event);
        }
      } catch {
        updateTurn(turn, (item) =>
          item.segments.length
            ? item
            : { ...item, segments: [{ type: "error", text: unreachable }] },
        );
      } finally {
        updateTurn(turn, (item) => ({ ...item, pending: false }));
        setTurnState((state) => ({ turnCount: turn, completed: state.completed + 1 }));
      }
    },
    [handleEvent, unreachable, updateTurn],
  );

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || busy || !sessionId) return;
      setBusy(true);
      await runTurn(message, api.chatStream(message));
      setBusy(false);
    },
    [api, busy, sessionId, runTurn],
  );

  return {
    items,
    setItems,
    ready: sessionId != null,
    busy,
    send,
    ...turnState,
  };
}

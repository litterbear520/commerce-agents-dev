/** 事件形状镜像 commerce_common/streaming.py。 */
// 项目中对应 examples/web-shared/protocol.ts
// 当前跳过 ToolCallData、Order、MemoryFact、TraceEntry —— 它们属于 Step 24 的追踪面板

export type AgentEventType =
  | "text_delta"
  | "tool_call"
  | "tool_result"
  | "ui"
  | "ui_partial"
  | "cart_update"
  | "change_update"
  | "progress"
  | "turn_complete"
  | "error";

export interface AgentEvent {
  type: AgentEventType;
  data: Record<string, unknown>;
}

/** 每个应用在自己的注册表里收窄 `payload`。 */
export interface UIBlock {
  component: string;
  payload: unknown;
}

/** `retrying`：这次尝试没通过校验，它的最后一帧会一直留着，等重试接管。 */
export type UISlotStatus = "pending" | "partial" | "retrying" | "final";

export type AssistantSegment =
  | { type: "text"; text: string }
  | { type: "error"; text: string }
  | {
      type: "ui";
      block: UIBlock;
      slotKey: string;
      status: UISlotStatus;
    };

export type UISegment = Extract<AssistantSegment, { type: "ui" }>;

export interface UserChatItem {
  kind: "user";
  text: string;
}

export interface AssistantChatItem {
  kind: "assistant";
  turn: number;
  segments: AssistantSegment[];
  suggestions: string[];
  pending: boolean;
}

export type ChatItem = UserChatItem | AssistantChatItem;

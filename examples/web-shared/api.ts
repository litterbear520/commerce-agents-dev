import type { AgentEvent } from "./protocol";

const SESSION_HEADER = "X-Session-Id";

/**
 * 两个角色的 Web 应用共用的客户端；店面读购物车也走这里。
 * 会话令牌只在会话头里传。读取失败一律返回 null，调用方保留上一次的好状态。
 */
export class AgentApi {
  session: string | null = null;
  readonly base: string;

  /** `root` 是 API 的地址，`prefix` 是角色的路由前缀（"/api"、"/api/merchant"）。 */
  constructor(
    readonly root: string,
    prefix: string,
  ) {
    this.base = `${root}${prefix}`;
  }

  headers(json = false): Record<string, string> {
    const headers: Record<string, string> = {};
    if (this.session) headers[SESSION_HEADER] = this.session;
    if (json) headers["Content-Type"] = "application/json";
    return headers;
  }

  async get<T>(path: string, params?: Record<string, string>): Promise<T | null> {
    const query = params && Object.keys(params).length ? `?${new URLSearchParams(params)}` : "";
    return this.request<T>(`${path}${query}`, { headers: this.headers() });
  }

  async post<T>(path: string, body?: unknown): Promise<T | null> {
    return this.send<T>("POST", path, body);
  }

  private async send<T>(method: string, path: string, body?: unknown): Promise<T | null> {
    return this.request<T>(path, {
      method,
      headers: this.headers(body !== undefined),
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  }

  private async request<T>(path: string, init: RequestInit): Promise<T | null> {
    try {
      const response = await fetch(`${this.base}${path}`, init);
      if (!response.ok) return null;
      return (await response.json()) as T;
    } catch {
      return null;
    }
  }

  /** 店面把自己的 profile 作为 `{ user_id }` 传进来。 */
  async startSession(body?: Record<string, unknown>): Promise<{ sessionId: string } | null> {
    const data = await this.post<{ session_id: string }>("/session", body);
    if (!data?.session_id) return null;
    return { sessionId: data.session_id };
  }

  /** 购物袋，形状由垂直行业的 API 决定（行、件数、小计，外加它自己的字段）。 */
  async fetchCart<T>(): Promise<T | null> {
    return this.get<T>("/cart");
  }

  /** 请求本身失败时抛错。 */
  async *chatStream(message: string): AsyncGenerator<AgentEvent> {
    const response = await fetch(`${this.base}/chat`, {
      method: "POST",
      headers: this.headers(true),
      body: JSON.stringify({ message }),
    });
    if (!response.ok || !response.body) throw new Error(`chat request failed: ${response.status}`);
    yield* readEventStream(response.body);
  }
}

async function* readEventStream(body: ReadableStream<Uint8Array>): AsyncGenerator<AgentEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventType: string | null = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newline: number;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newline).trimEnd();
      buffer = buffer.slice(newline + 1);
      if (line.startsWith("event: ")) {
        eventType = line.slice(7).trim();
      } else if (line.startsWith("data: ") && eventType) {
        try {
          yield { type: eventType, data: JSON.parse(line.slice(6)) } as AgentEvent;
        } catch {
          // 坏掉的一帧直接丢掉，流继续往下读。
        }
      } else if (line === "") {
        eventType = null;
      }
    }
  }
}

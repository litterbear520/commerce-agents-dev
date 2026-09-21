"use client";

import { useEffect, useState } from "react";
import type { AgentApi } from "./api";

export interface Session {
  /** 会话尚未建立或建立失败时为 null。 */
  sessionId: string | null;
}

const generations = new WeakMap<AgentApi, number>();

/**
 * 只有最新一次 start 会把自己的令牌装上去。调用方按 profile 做 key，
 * 这样跟会话绑定的状态会跟着一起重置。
 */
export function useSession(api: AgentApi, options: { profile?: string } = {}): Session {
  const { profile } = options;
  const [session, setSession] = useState<Session>({ sessionId: null });

  useEffect(() => {
    const generation = (generations.get(api) ?? 0) + 1;
    generations.set(api, generation);
    const current = () => generations.get(api) === generation;
    void (async () => {
      const started = await api.startSession(profile ? { user_id: profile } : undefined);
      if (!current()) return;
      api.session = started?.sessionId ?? null;
      setSession({ sessionId: started?.sessionId ?? null });
    })();
    return () => {
      generations.set(api, (generations.get(api) ?? 0) + 1);
    };
  }, [api, profile]);

  return session;
}

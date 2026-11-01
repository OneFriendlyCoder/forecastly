import { useEffect, useState } from "react";

const INTERVAL_MS = 5000;

type State<T> = { data?: T; error?: unknown };

/** Refetches on a timer. After a failed refresh, the last good data stays on screen beside the error. */
export function usePolling<T>(load: () => Promise<T>, key: string): State<T> {
  const [state, setState] = useState<State<T> & { key?: string }>({});

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const data = await load();
        if (active) setState({ data, key });
      } catch (error) {
        if (active) setState((previous) => ({ ...previous, error, key }));
      }
      if (active) timer = setTimeout(tick, INTERVAL_MS);
    };
    tick();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [key]);

  return state.key === key ? state : {}; // never show the previous deal under a new address
}

import { useEffect, useState } from "react";

const INTERVAL_MS = 5000;

type State<T> = { data?: T; error?: unknown; updatedAt?: number };

/** Refetches on a timer. The last good data stays on screen through refreshes, new filters and failures. */
export function usePolling<T>(load: () => Promise<T>, key: string): State<T> {
  const [state, setState] = useState<State<T>>({});

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const data = await load();
        if (active) setState({ data, updatedAt: Date.now() });
      } catch (error) {
        if (active) setState((previous) => ({ ...previous, error }));
      }
      if (active) timer = setTimeout(tick, INTERVAL_MS);
    };
    tick();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [key]);

  return state;
}

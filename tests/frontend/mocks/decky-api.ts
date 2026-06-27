type AnyFn = (...args: unknown[]) => unknown;

const _callables = new Map<string, AnyFn>();
const _callLog = new Map<string, unknown[][]>();
const _handlers = new Map<string, AnyFn[]>();

export function callable<TArgs extends unknown[], TRet>(
  name: string
): (...args: TArgs) => Promise<TRet> {
  return async (...args: TArgs): Promise<TRet> => {
    const log = _callLog.get(name) ?? [];
    log.push(args);
    _callLog.set(name, log);
    const impl = _callables.get(name);
    if (impl) return impl(...args) as TRet;
    console.warn(`[decky-api mock] no impl for callable "${name}", returning null`);
    return null as unknown as TRet;
  };
}

export function addEventListener<TArgs extends unknown[]>(
  event: string,
  handler: (...args: TArgs) => void
): (...args: TArgs) => void {
  const list = _handlers.get(event) ?? [];
  list.push(handler as AnyFn);
  _handlers.set(event, list);
  return handler;
}

export function removeEventListener<TArgs extends unknown[]>(
  event: string,
  handler: (...args: TArgs) => void
): void {
  const list = _handlers.get(event) ?? [];
  _handlers.set(event, list.filter(h => h !== handler));
}

export function definePlugin<T>(factory: () => T): T {
  return factory();
}

export const toaster = {
  toast: (_opts: unknown) => {},
};

// ── Test control surface ──────────────────────────────────────────────────────

const testAPI = {
  mockCallable(name: string, impl: AnyFn): void {
    _callables.set(name, impl);
  },
  fireEvent(name: string, ...args: unknown[]): void {
    (_handlers.get(name) ?? []).forEach(h => h(...args));
  },
  callLog(name: string): unknown[][] {
    return _callLog.get(name) ?? [];
  },
  resetAll(): void {
    _callables.clear();
    _callLog.clear();
    _handlers.clear();
  },
};

// Default callable implementations so the component renders without errors
testAPI.mockCallable('get_status', async () => ({ running: false, connected: false, port: 12345 }));
testAPI.mockCallable('get_devices', async () => []);
testAPI.mockCallable('start_engine', async () => ({ success: true }));
testAPI.mockCallable('stop_engine', async () => ({ success: true }));

(window as unknown as Record<string, unknown>)['__deckyTestAPI__'] = testAPI;

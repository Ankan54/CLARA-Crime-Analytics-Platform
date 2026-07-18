import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

export type ToastKind = "ok" | "danger";

type ToastItem = {
  id: string;
  kind: ToastKind;
  message: string;
  leaving?: boolean;
};

type ToastApi = {
  success: (message: string) => void;
  error: (message: string) => void;
  dismiss: (id: string) => void;
};

const ToastContext = createContext<ToastApi | null>(null);

const AUTO_DISMISS_MS = 4500;
const FADE_MS = 280;

function makeToastId(): string {
  return `toast-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

export function useToast(): ToastApi {
  const api = useContext(ToastContext);
  if (!api) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return api;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timers = useRef<Map<string, number>>(new Map());

  const clearTimers = useCallback((id: string) => {
    const handle = timers.current.get(id);
    if (handle != null) {
      window.clearTimeout(handle);
      timers.current.delete(id);
    }
  }, []);

  const dismiss = useCallback(
    (id: string) => {
      clearTimers(id);
      setToasts((current) =>
        current.map((toast) => (toast.id === id ? { ...toast, leaving: true } : toast)),
      );
      const removeHandle = window.setTimeout(() => {
        setToasts((current) => current.filter((toast) => toast.id !== id));
        timers.current.delete(id);
      }, FADE_MS);
      timers.current.set(id, removeHandle);
    },
    [clearTimers],
  );

  const push = useCallback(
    (kind: ToastKind, message: string) => {
      const text = message.trim();
      if (!text) return;
      const id = makeToastId();
      setToasts((current) => [...current, { id, kind, message: text }]);
      const autoHandle = window.setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
      timers.current.set(id, autoHandle);
    },
    [dismiss],
  );

  useEffect(() => {
    return () => {
      timers.current.forEach((handle) => window.clearTimeout(handle));
      timers.current.clear();
    };
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      success: (message) => push("ok", message),
      error: (message) => push("danger", message),
      dismiss,
    }),
    [dismiss, push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toast-stack" aria-live="polite" aria-relevant="additions text">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`toast toast-${toast.kind}${toast.leaving ? " is-leaving" : ""}`}
            role={toast.kind === "danger" ? "alert" : "status"}
          >
            <p className="toast-message">{toast.message}</p>
            <button
              type="button"
              className="toast-close"
              aria-label="Dismiss"
              onClick={() => dismiss(toast.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

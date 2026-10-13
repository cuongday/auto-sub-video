import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

type Base = { title: string; message?: ReactNode; confirmLabel?: string; cancelLabel?: string; danger?: boolean };
type Request =
  | (Base & { kind: "confirm"; resolve: (ok: boolean) => void })
  | (Base & { kind: "prompt"; placeholder?: string; initial?: string; resolve: (value: string | null) => void });

type DialogApi = {
  confirm: (o: Base) => Promise<boolean>;
  prompt: (o: Base & { placeholder?: string; initial?: string }) => Promise<string | null>;
};

const Ctx = createContext<DialogApi | null>(null);

export function useDialog(): DialogApi {
  const d = useContext(Ctx);
  if (!d) throw new Error("useDialog outside DialogProvider");
  return d;
}

/** App-wide confirm/prompt modals that return promises (replaces window.confirm/prompt). */
export function DialogProvider({ children }: { children: ReactNode }) {
  const [req, setReq] = useState<Request | null>(null);
  const confirm = useCallback((o: Base) => new Promise<boolean>((resolve) => setReq({ ...o, kind: "confirm", resolve })), []);
  const prompt = useCallback((o: Base & { placeholder?: string; initial?: string }) =>
    new Promise<string | null>((resolve) => setReq({ ...o, kind: "prompt", resolve })), []);
  return (
    <Ctx.Provider value={{ confirm, prompt }}>
      {children}
      {req && <Modal req={req} onDone={() => setReq(null)} />}
    </Ctx.Provider>
  );
}

function Modal({ req, onDone }: { req: Request; onDone: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState(req.kind === "prompt" ? req.initial ?? "" : "");

  useEffect(() => {
    ref.current?.showModal();
    if (req.kind === "prompt") input.current?.select();
  }, [req]);

  const finish = (ok: boolean) => {
    if (req.kind === "confirm") req.resolve(ok);
    else req.resolve(ok && value.trim() ? value.trim() : null);
    ref.current?.close();
    onDone();
  };

  return (
    <dialog ref={ref} className="modal" aria-labelledby="modal-title"
      onCancel={(e) => { e.preventDefault(); finish(false); }}
      onClick={(e) => { if (e.target === ref.current) finish(false); }}>
      <form method="dialog" onSubmit={(e) => { e.preventDefault(); finish(true); }}>
        <h3 id="modal-title">{req.title}</h3>
        {req.message && <div className="modal-body">{req.message}</div>}
        {req.kind === "prompt" && (
          <input ref={input} value={value} placeholder={req.placeholder} onChange={(e) => setValue(e.target.value)} />
        )}
        <div className="modal-actions">
          <button type="button" className="ghost" onClick={() => finish(false)}>{req.cancelLabel ?? "Huỷ"}</button>
          <button type="submit" className={req.danger ? "danger-solid" : "primary"} autoFocus={req.kind === "confirm"}
            disabled={req.kind === "prompt" && !value.trim()}>
            {req.confirmLabel ?? "Đồng ý"}
          </button>
        </div>
      </form>
    </dialog>
  );
}

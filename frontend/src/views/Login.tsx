import { useState } from "react";

export default function Login({ onDone }: { onDone: () => void }) {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true); setErr("");
    const r = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: pw }) });
    setBusy(false);
    if (r.ok) onDone(); else setErr((await r.json().catch(() => ({}))).detail || "Đăng nhập lỗi");
  };
  return (
    <div className="login-screen">
      <form className="card login-card" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <div className="brand"><span className="logo" aria-hidden /> Auto-Sub</div>
        <label>Mật khẩu<input type="password" value={pw} autoFocus onChange={(e) => setPw(e.target.value)} /></label>
        {err && <p className="error">{err}</p>}
        <button className="primary" disabled={!pw || busy}>{busy ? "Đang vào…" : "Đăng nhập"}</button>
      </form>
    </div>
  );
}

"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AUTH_MODE, supabase } from "@/lib/auth";

type Mode = "signin" | "signup" | "magic";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  if (AUTH_MODE !== "supabase") {
    return <p className="card mx-auto max-w-md p-5 text-sm">目前是開發模式，請在右上角輸入開發用帳號。</p>;
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setMessage(null);
    const auth = supabase().auth;
    const redirect = `${location.origin}/studio`;
    const { error } = mode === "signin" ? await auth.signInWithPassword({ email, password })
      : mode === "signup" ? await auth.signUp({ email, password, options: { emailRedirectTo: redirect } })
      : await auth.signInWithOtp({ email, options: { emailRedirectTo: redirect } });
    setBusy(false);
    if (error) { setMessage({ ok: false, text: error.message }); return; }
    if (mode === "signin") { router.push("/studio"); return; }
    setMessage({ ok: true, text: mode === "signup" ? "已寄出確認信，請到信箱點連結完成註冊。" : "已寄出登入連結，請到信箱點擊。" });
  };

  const tabs: [Mode, string][] = [["signin", "登入"], ["signup", "註冊"], ["magic", "寄送登入連結"]];
  return (
    <form onSubmit={submit} className="card mx-auto max-w-md space-y-4 p-6">
      <div className="flex gap-1 rounded-lg border border-line p-1 text-sm" role="tablist">
        {tabs.map(([m, label]) => (
          <button key={m} type="button" role="tab" aria-selected={mode === m} onClick={() => setMode(m)}
            className={`flex-1 rounded-md px-2 py-1 ${mode === m ? "bg-accent text-accent-ink" : ""}`}>{label}</button>
        ))}
      </div>
      <label className="block text-sm">Email
        <input className="field mt-1" type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)} />
      </label>
      {mode !== "magic" && (
        <label className="block text-sm">密碼
          <input className="field mt-1" type="password" minLength={8} required value={password}
            autoComplete={mode === "signup" ? "new-password" : "current-password"} onChange={e => setPassword(e.target.value)} />
        </label>
      )}
      {message && <p className={`text-sm ${message.ok ? "text-ok" : "text-bad"}`} role="status">{message.text}</p>}
      <button className="btn btn-primary w-full justify-center" disabled={busy} type="submit">
        {busy ? "處理中…" : tabs.find(t => t[0] === mode)![1]}
      </button>
    </form>
  );
}

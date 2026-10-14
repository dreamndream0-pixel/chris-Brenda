"use client";
import { useEffect, useState } from "react";
import { getDevUser, setDevUser } from "@/lib/api";

// Development login: the API runs with EMB_AUTH_MODE=dev and trusts X-Dev-User.
// Supabase Auth replaces this before any real deployment.
export default function AuthBar() {
  const [user, setUser] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  useEffect(() => setUser(getDevUser()), []);

  if (user) {
    return (
      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted">使用者</span><strong>{user}</strong>
        <button className="btn py-1" onClick={() => { setDevUser(null); location.reload(); }}>登出</button>
      </div>
    );
  }
  return (
    <form className="flex items-center gap-2 text-sm" onSubmit={e => {
      e.preventDefault();
      const name = draft.trim();
      if (!/^[A-Za-z0-9_.@-]{1,64}$/.test(name)) return;
      setDevUser(name); location.reload();
    }}>
      <input className="field w-40 py-1" placeholder="開發用帳號（英數）" value={draft} onChange={e => setDraft(e.target.value)} aria-label="使用者名稱" />
      <button className="btn btn-primary py-1" type="submit">登入</button>
    </form>
  );
}

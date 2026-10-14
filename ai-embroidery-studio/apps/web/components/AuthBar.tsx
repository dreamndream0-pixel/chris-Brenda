"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { AUTH_MODE, currentUserLabel, setDevUser, signOut, supabase } from "@/lib/auth";

export default function AuthBar() {
  const [user, setUser] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    currentUserLabel().then(u => { setUser(u); setReady(true); });
    if (AUTH_MODE !== "supabase") return;
    const { data } = supabase().auth.onAuthStateChange((_event, session) => setUser(session?.user.email ?? null));
    return () => data.subscription.unsubscribe();
  }, []);

  if (!ready) return <div className="h-8" />;
  if (user) {
    return (
      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted">使用者</span><strong className="max-w-48 truncate">{user}</strong>
        <button className="btn py-1" onClick={async () => { await signOut(); location.assign("/studio"); }}>登出</button>
      </div>
    );
  }
  if (AUTH_MODE === "supabase") return <Link href="/login" className="btn btn-primary py-1 text-sm">登入</Link>;
  // Development login: the API runs with EMB_AUTH_MODE=dev and trusts X-Dev-User.
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

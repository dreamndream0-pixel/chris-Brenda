// Sign-in for the two API auth modes:
//   dev      - a typed name sent as X-Dev-User (local development only)
//   supabase - Supabase Auth; the access token goes to the API as a Bearer token
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

export const AUTH_MODE: "dev" | "supabase" = process.env.NEXT_PUBLIC_AUTH_MODE === "supabase" ? "supabase" : "dev";
const DEV_USER_KEY = "emb.devUser";

let client: SupabaseClient | null = null;
export function supabase(): SupabaseClient {
  if (!client) {
    const url = process.env.NEXT_PUBLIC_SUPABASE_URL, key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    if (!url || !key) throw new Error("NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY are not set");
    client = createClient(url, key, { auth: { persistSession: true, autoRefreshToken: true } });
  }
  return client;
}

export function getDevUser(): string | null {
  try { return localStorage.getItem(DEV_USER_KEY); } catch { return null; }
}
export function setDevUser(name: string | null) {
  try { if (name) localStorage.setItem(DEV_USER_KEY, name); else localStorage.removeItem(DEV_USER_KEY); } catch { /* storage blocked */ }
}

/** Headers that authenticate an API request, or {} when signed out. */
export async function authHeaders(): Promise<Record<string, string>> {
  if (AUTH_MODE === "supabase") {
    const { data } = await supabase().auth.getSession();
    return data.session ? { Authorization: `Bearer ${data.session.access_token}` } : {};
  }
  const user = getDevUser();
  return user ? { "X-Dev-User": user } : {};
}

/** Display name of the signed-in user, or null. */
export async function currentUserLabel(): Promise<string | null> {
  if (AUTH_MODE === "supabase") {
    const { data } = await supabase().auth.getSession();
    return data.session?.user.email ?? null;
  }
  return getDevUser();
}

export async function signOut() {
  if (AUTH_MODE === "supabase") await supabase().auth.signOut();
  else setDevUser(null);
}

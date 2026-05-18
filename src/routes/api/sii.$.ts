import { createFileRoute } from "@tanstack/react-router";
import { getEvent } from "vinxi/http";
import { getSiiBackendUrl } from "@/lib/sii-config";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

interface ServiceAccountKey {
  client_email: string;
  private_key: string;
}

async function getGCPIdentityToken(sa: ServiceAccountKey, audience: string): Promise<string> {
  const now = Math.floor(Date.now() / 1000);

  const header = { alg: "RS256", typ: "JWT" };
  const payload = {
    iss: sa.client_email,
    sub: sa.client_email,
    aud: "https://oauth2.googleapis.com/token",
    iat: now,
    exp: now + 3600,
    target_audience: audience,
  };

  const b64url = (obj: object) =>
    btoa(JSON.stringify(obj)).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");

  const signingInput = `${b64url(header)}.${b64url(payload)}`;

  const pemContents = sa.private_key
    .replace("-----BEGIN PRIVATE KEY-----", "")
    .replace("-----END PRIVATE KEY-----", "")
    .replace(/\n/g, "");
  const keyData = Uint8Array.from(atob(pemContents), (c) => c.charCodeAt(0));

  const cryptoKey = await crypto.subtle.importKey(
    "pkcs8",
    keyData,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"],
  );

  const signature = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    cryptoKey,
    new TextEncoder().encode(signingInput),
  );

  const sigB64 = btoa(String.fromCharCode(...new Uint8Array(signature)))
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");

  const jwt = `${signingInput}.${sigB64}`;

  const res = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion: jwt,
    }),
  });

  const data = (await res.json()) as { id_token?: string; error?: string };
  if (!data.id_token) throw new Error(`GCP token error: ${data.error ?? JSON.stringify(data)}`);
  return data.id_token;
}

// Lee un secret desde CF Workers bindings (via H3 event context de Vinxi/TanStack Start)
// o como fallback desde process.env / globalThis.
function readSecret(key: string): string {
  // 1. CF Workers binding via H3 event context (Vinxi adapter)
  try {
    const event = getEvent();
    const cfEnv = (event.context as Record<string, unknown>)?.cloudflare as
      | Record<string, Record<string, string>>
      | undefined;
    if (cfEnv?.env?.[key]) return cfEnv.env[key];
  } catch {
    // getEvent() falla fuera de un request context
  }

  // 2. globalThis.env (Wrangler / Miniflare dev)
  const g = globalThis as Record<string, unknown>;
  const cfEnv = g["env"] as Record<string, string> | undefined;
  if (cfEnv?.[key]) return cfEnv[key];

  // 3. Binding directo en globalThis
  if (typeof g[key] === "string" && g[key]) return g[key] as string;

  // 4. process.env (Node / polyfill)
  const procEnv = (g["process"] as { env?: Record<string, string> } | undefined)?.env;
  if (procEnv?.[key]) return procEnv[key];

  return "";
}

async function resolveAuthToken(request: Request, backendUrl: string): Promise<string | null> {
  void request;
  const saKeyB64 = readSecret("GCP_SA_KEY_JSON");
  if (saKeyB64) {
    try {
      const sa: ServiceAccountKey = JSON.parse(atob(saKeyB64));
      const audience = backendUrl.replace(/\/$/, "").split("/").slice(0, 3).join("/");
      const token = await getGCPIdentityToken(sa, audience);
      console.info("[sii-proxy] OIDC token OK para", sa.client_email);
      return token;
    } catch (e) {
      console.error("[sii-proxy] Error generando OIDC token:", e);
    }
  } else {
    console.warn("[sii-proxy] GCP_SA_KEY_JSON no encontrado en ningún scope");
  }
  const staticToken = readSecret("SII_BACKEND_TOKEN");
  return staticToken || null;
}

async function proxy(request: Request, splat: string): Promise<Response> {
  const backend = getSiiBackendUrl().replace(/\/$/, "");
  const target = `${backend}/${splat}`;

  try {
    const token = await resolveAuthToken(request, backend);
    console.info("[sii-proxy] token presente:", !!token, "→", target);

    const h = new Headers(request.headers);
    h.delete("host");
    h.delete("content-length");
    if (token) h.set("Authorization", `Bearer ${token}`);

    const isBodyless = request.method === "GET" || request.method === "HEAD";
    const body = isBodyless ? undefined : await request.arrayBuffer();

    const upstream = await fetch(target, {
      method: request.method,
      headers: h,
      body,
    });

    const headers = new Headers(upstream.headers);
    Object.entries(corsHeaders).forEach(([k, v]) => headers.set(k, v));
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers,
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Backend SII no disponible";
    return new Response(
      JSON.stringify({ detail: `No se pudo contactar al backend Python en ${target}. ${msg}` }),
      { status: 502, headers: { "Content-Type": "application/json", ...corsHeaders } },
    );
  }
}

export const Route = createFileRoute("/api/sii/$")({
  server: {
    handlers: {
      OPTIONS: async () => new Response(null, { status: 204, headers: corsHeaders }),
      GET: async ({ request, params }) => proxy(request, params._splat ?? ""),
      POST: async ({ request, params }) => proxy(request, params._splat ?? ""),
    },
  },
});

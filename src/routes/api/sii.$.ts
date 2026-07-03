import { createFileRoute } from "@tanstack/react-router";
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
  // 1. globalThis.env (Wrangler / Miniflare dev)
  const g = globalThis as Record<string, unknown>;
  const cfEnv = g["env"] as Record<string, string> | undefined;
  if (cfEnv?.[key]) return cfEnv[key];

  // 2. Binding directo en globalThis
  if (typeof g[key] === "string" && g[key]) return g[key] as string;

  // 3. process.env (Node / polyfill)
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

// DEBUG TEMPORAL — diagnosticar por qué /api/sii/* devuelve 403 en producción.
// Quitar este bloque (y su uso en GET más abajo) una vez resuelto.
async function diagnose(request: Request): Promise<Response> {
  const backend = getSiiBackendUrl().replace(/\/$/, "");
  const g = globalThis as Record<string, unknown>;
  const cfEnv = g["env"] as Record<string, string> | undefined;
  const procEnv = (g["process"] as { env?: Record<string, string> } | undefined)?.env;

  const saKeyB64 = readSecret("GCP_SA_KEY_JSON");
  const staticToken = readSecret("SII_BACKEND_TOKEN");

  const result: Record<string, unknown> = {
    backend,
    foundVia: {
      "globalThis.env": !!cfEnv?.["GCP_SA_KEY_JSON"],
      "globalThis[key]": typeof g["GCP_SA_KEY_JSON"] === "string",
      "process.env": !!procEnv?.["GCP_SA_KEY_JSON"],
    },
    gcpSaKeyFound: !!saKeyB64,
    gcpSaKeyLength: saKeyB64.length,
    staticTokenFound: !!staticToken,
  };

  if (saKeyB64) {
    try {
      const sa = JSON.parse(atob(saKeyB64)) as ServiceAccountKey;
      result.saClientEmail = sa.client_email ?? null;
      result.privateKeyLooksLikePem = sa.private_key?.startsWith("-----BEGIN PRIVATE KEY-----") ?? false;
      result.privateKeyLength = sa.private_key?.length ?? 0;
      result.privateKeyHasLiteralBackslashN = sa.private_key?.includes("\\n") ?? false;

      // Llamar getGCPIdentityToken directo (no resolveAuthToken) para no perder el error real.
      try {
        const audience = backend.split("/").slice(0, 3).join("/");
        result.audience = audience;
        const token = await getGCPIdentityToken(sa, audience);
        result.tokenObtained = !!token;
      } catch (e) {
        result.tokenObtained = false;
        result.tokenError = e instanceof Error ? e.message : String(e);
      }
    } catch (e) {
      result.saParseError = e instanceof Error ? e.message : String(e);
    }
  }

  return new Response(JSON.stringify(result, null, 2), {
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });
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
      GET: async ({ request, params }) => {
        const url = new URL(request.url);
        if (url.searchParams.get("felixdiag") === "pudu2026tmp") {
          return diagnose(request);
        }
        return proxy(request, params._splat ?? "");
      },
      POST: async ({ request, params }) => proxy(request, params._splat ?? ""),
    },
  },
});

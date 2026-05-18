// Lee una variable de entorno compatible con Cloudflare Workers (Lovable Cloud),
// Node.js y Vite. CF Workers expone los secrets como propiedades del objeto `env`
// inyectado en el handler, o como globales directos según el adaptador.
function readEnv(key: string): string {
  // 1. CF Workers: binding directo en globalThis (Vinxi/TanStack Start adapter)
  const g = globalThis as Record<string, unknown>;
  if (typeof g[key] === "string" && g[key]) return g[key] as string;

  // 2. CF Workers: objeto env en globalThis
  const cfEnv = g["env"] as Record<string, string> | undefined;
  if (cfEnv?.[key]) return cfEnv[key];

  // 3. Node.js / polyfill
  const procEnv = g["process"] as { env?: Record<string, string> } | undefined;
  if (procEnv?.env?.[key]) return procEnv.env[key];

  // 4. Vite build-time (solo vars VITE_*)
  const metaEnv = (import.meta as { env?: Record<string, string> }).env;
  if (metaEnv?.[key]) return metaEnv[key];

  return "";
}

export function getSiiBackendUrl(): string {
  return (
    readEnv("SII_BACKEND_URL") ||
    readEnv("VITE_SII_BACKEND_URL") ||
    "https://certificador-sii-jzani6twoq-uc.a.run.app"
  );
}

export function getSiiBackendToken(): string {
  return readEnv("SII_BACKEND_TOKEN");
}

export function getSiiSaKeyJson(): string {
  return readEnv("GCP_SA_KEY_JSON") || readEnv("VITE_GCP_SA_KEY_JSON");
}
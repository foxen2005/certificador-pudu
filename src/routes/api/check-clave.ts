import { createFileRoute } from "@tanstack/react-router";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

function readSecret(key: string): string {
  const g = globalThis as Record<string, unknown>;
  const cfEnv = g["env"] as Record<string, string> | undefined;
  if (cfEnv?.[key]) return cfEnv[key];
  if (typeof g[key] === "string" && g[key]) return g[key] as string;
  const procEnv = (g["process"] as { env?: Record<string, string> } | undefined)?.env;
  if (procEnv?.[key]) return procEnv[key];
  return "";
}

export const Route = createFileRoute("/api/check-clave")({
  server: {
    handlers: {
      OPTIONS: async () => new Response(null, { status: 204, headers: corsHeaders }),
      POST: async ({ request }) => {
        const { clave } = (await request.json().catch(() => ({}))) as { clave?: string };
        const expected = readSecret("WIZARD_PASSWORD");
        const ok = !!expected && clave === expected;
        return new Response(JSON.stringify({ ok }), {
          headers: { "Content-Type": "application/json", ...corsHeaders },
        });
      },
    },
  },
});

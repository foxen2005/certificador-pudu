import { useState } from "react";
import { Download, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";

export interface CheckResult {
  nombre: string;
  ok: boolean;
  detalle?: string;
}

export interface DocResult {
  folio: number;
  tipo: number;
  tipo_nombre: string;
  cedible: boolean;
  archivo: string;
  validacion: {
    aprobado: boolean;
    puntaje: string;
    checks: CheckResult[];
  };
}

export interface BatchResult {
  nro_atencion?: string;
  nro_atencion_ventas?: string;
  nro_atencion_compras?: string;
  libro_ventas_generado?: boolean;
  libro_compras_generado?: boolean;
  documentos: number;
  pdfs_generados: number;
  aprobados: number;
  rechazados: number;
  resultados: DocResult[];
  zip_base64?: string;
}

const tipoColor: Record<number, string> = {
  33: "bg-blue-100 text-blue-800",
  34: "bg-emerald-100 text-emerald-800",
  46: "bg-blue-100 text-blue-800",
  52: "bg-pink-100 text-pink-800",
  56: "bg-amber-100 text-amber-800",
  61: "bg-violet-100 text-violet-800",
};

function Stat({
  num,
  lbl,
  tone,
}: {
  num: number | string;
  lbl: string;
  tone: "ok" | "fail" | "info";
}) {
  const color =
    tone === "ok"
      ? "text-success"
      : tone === "fail"
        ? "text-primary"
        : "text-info";
  return (
    <div className="rounded-lg bg-muted/40 p-4 text-center">
      <div className={`text-3xl font-bold ${color}`}>{num}</div>
      <div className="mt-1 text-xs text-muted-foreground">{lbl}</div>
    </div>
  );
}

function DocItem({ r }: { r: DocResult }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between bg-card px-4 py-2.5 text-left hover:bg-muted/40"
      >
        <div className="flex items-center gap-2.5">
          <span
            className={`rounded px-2 py-0.5 text-[11px] font-semibold ${
              tipoColor[r.tipo] ?? "bg-slate-100 text-slate-800"
            }`}
          >
            {r.tipo_nombre.split(" ").slice(0, 2).join(" ")}
          </span>
          <span className="text-sm font-medium text-foreground">{r.archivo}</span>
          {r.cedible && (
            <span className="rounded bg-header px-1.5 py-0.5 text-[10px] font-bold text-header-foreground">
              CEDIBLE
            </span>
          )}
        </div>
        <div className="flex items-center gap-2.5">
          <span className="text-xs text-muted-foreground">
            {r.validacion.puntaje} checks
          </span>
          <span
            className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
              r.validacion.aprobado
                ? "bg-emerald-100 text-emerald-800"
                : "bg-red-100 text-red-800"
            }`}
          >
            {r.validacion.aprobado ? "✓ OK" : "✗ FALLA"}
          </span>
          <ChevronDown
            className={`h-4 w-4 text-muted-foreground transition-transform ${
              open ? "rotate-180" : ""
            }`}
          />
        </div>
      </button>
      {open && (
        <div className="border-t border-border bg-muted/30 px-4 py-3">
          {r.validacion.checks.map((c, i) => (
            <div
              key={i}
              className="flex items-start gap-2 border-b border-border/50 py-1 text-sm last:border-0"
            >
              <span>{c.ok ? "✅" : "❌"}</span>
              <span className="flex-1 font-medium text-foreground">{c.nombre}</span>
              <span className="text-xs text-muted-foreground">{c.detalle}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function Results({
  data,
  filename = "certificacion.zip",
}: {
  data: BatchResult;
  filename?: string;
}) {
  function descargar() {
    if (!data.zip_base64) return;
    const a = document.createElement("a");
    a.href = "data:application/zip;base64," + data.zip_base64;
    a.download = filename;
    a.click();
  }

  return (
    <div className="space-y-4">
      {/* Números de atención */}
      <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
        {data.nro_atencion && (
          <span>Set Básico: <b className="text-foreground">{data.nro_atencion}</b></span>
        )}
        {data.nro_atencion_ventas && (
          <span>Libro Ventas: <b className="text-foreground">{data.nro_atencion_ventas}</b></span>
        )}
        {data.nro_atencion_compras && (
          <span>Libro Compras: <b className="text-foreground">{data.nro_atencion_compras}</b></span>
        )}
      </div>

      {/* Estadísticas DTEs */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat num={data.documentos} lbl="DTEs" tone="info" />
        <Stat num={data.pdfs_generados} lbl="PDFs" tone="info" />
        <Stat num={data.aprobados} lbl="Aprobados" tone="ok" />
        <Stat num={data.rechazados} lbl="Rechazados" tone="fail" />
      </div>

      {/* Estado de libros */}
      {(data.nro_atencion_ventas || data.nro_atencion_compras) && (
        <div className="rounded-lg border border-border bg-muted/20 px-4 py-3">
          <div className="mb-2 text-xs font-bold uppercase tracking-wider text-muted-foreground">
            Libros electrónicos
          </div>
          <div className="flex flex-wrap gap-3">
            {data.nro_atencion_ventas && (
              <div className="flex items-center gap-1.5 text-sm">
                <span>{data.libro_ventas_generado ? "✅" : "❌"}</span>
                <span className="font-medium text-foreground">LibroVentas XML</span>
                {data.libro_ventas_generado && (
                  <span className="text-xs text-muted-foreground">incluido en ZIP</span>
                )}
              </div>
            )}
            {data.nro_atencion_compras && (
              <div className="flex items-center gap-1.5 text-sm">
                <span>{data.libro_compras_generado ? "✅" : "❌"}</span>
                <span className="font-medium text-foreground">LibroCompras XML</span>
                {data.libro_compras_generado ? (
                  <span className="text-xs text-muted-foreground">incluido en ZIP</span>
                ) : (
                  <span className="text-xs text-amber-600">sin entradas en el set</span>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="space-y-2">
        {data.resultados.map((r, i) => (
          <DocItem key={i} r={r} />
        ))}
      </div>
      {data.zip_base64 && (
        <Button onClick={descargar} className="w-full">
          <Download className="h-4 w-4" />
          Descargar XML + PDFs (.zip)
        </Button>
      )}
    </div>
  );
}
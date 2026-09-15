import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, Download, AlertCircle, ChevronRight, Lock, FileDown } from "lucide-react";
import { DATOS_LINEAS, DATOS_OBLIGATORIAS, decodificarDatos, plantillaDatosTxt, validarDatosTxt } from "@/lib/datos-txt";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { UploadBox } from "@/components/sii/UploadBox";
import { PortalGuide } from "@/components/sii/PortalGuide";
import { Results, type BatchResult } from "@/components/sii/Results";
import { VersionBadge } from "@/components/VersionBadge";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Certificador DTE — SII Chile" },
      { name: "description", content: "Guía paso a paso para certificación SII DTE" },
    ],
  }),
  component: CertWizard,
});

// ─── Types ────────────────────────────────────────────────────────────────────

type StepState = "locked" | "active" | "done" | "error";

interface StepStatus {
  setup: StepState;
  etapa1: StepState;
  etapa2: StepState;
  etapa3: StepState;
  etapa4: StepState;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatDetail(detail: unknown): string {
  // FastAPI 422 devuelve detail como lista de objetos {loc, msg, type};
  // otros errores lo devuelven como string. Formatear ambos de forma legible.
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((e) => {
        if (e && typeof e === "object" && "msg" in e) {
          const loc = Array.isArray((e as { loc?: unknown[] }).loc)
            ? (e as { loc: unknown[] }).loc.filter((p) => p !== "body").join(".")
            : "";
          const msg = String((e as { msg: unknown }).msg);
          return loc ? `${loc}: ${msg}` : msg;
        }
        return typeof e === "string" ? e : JSON.stringify(e);
      })
      .join(" · ");
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return String(detail);
}

// Header que el proxy /api/sii/* valida contra WIZARD_PASSWORD. Sin esto, cualquiera
// que conociera la URL podía usar el backend (la clave solo protegía la UI).
const WIZARD_KEY_HEADER = "X-Wizard-Key";

async function postForm(path: string, fd: FormData, clave: string) {
  // encodeURIComponent: los headers HTTP solo admiten Latin-1; una clave con
  // "€", "—" o emoji haría fallar fetch(). El proxy la decodifica.
  const res = await fetch(path, { method: "POST", body: fd, headers: { [WIZARD_KEY_HEADER]: encodeURIComponent(clave) } });
  const ct = res.headers.get("content-type") ?? "";
  const data = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    const msg =
      typeof data === "object" && data && "detail" in data
        ? formatDetail((data as { detail: unknown }).detail)
        : typeof data === "string" && data ? data : `Error ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function downloadB64(b64: string, filename: string) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length).map((_, i) => bin.charCodeAt(i));
  downloadBlob(new Blob([bytes]), filename);
}

// ─── Step indicator sidebar ───────────────────────────────────────────────────

const STEPS = [
  { key: "setup",  label: "Configuración",       num: 0 },
  { key: "etapa1", label: "Etapa 1 — Set Básico", num: 1 },
  { key: "etapa2", label: "Etapa 2 — Simulación", num: 2 },
  { key: "etapa3", label: "Etapa 3 — Intercambio",num: 3 },
  { key: "etapa4", label: "Etapa 4 — Muestras",   num: 4 },
] as const;

type StepKey = (typeof STEPS)[number]["key"];

function StepIcon({ state, num }: { state: StepState; num: number }) {
  if (state === "done")   return <CheckCircle2 className="h-6 w-6 text-green-500" />;
  if (state === "error")  return <AlertCircle className="h-6 w-6 text-red-500" />;
  if (state === "locked") return <Lock className="h-5 w-5 text-muted-foreground" />;
  return (
    <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-xs font-bold text-primary-foreground">
      {num}
    </div>
  );
}

function Stepper({
  current,
  status,
  onGo,
}: {
  current: StepKey;
  status: StepStatus;
  onGo: (k: StepKey) => void;
}) {
  return (
    <nav className="flex flex-col gap-1">
      {STEPS.map((s, i) => {
        const st = status[s.key];
        const isCurrent = current === s.key;
        const canClick = st !== "locked";
        return (
          <button
            key={s.key}
            disabled={!canClick}
            onClick={() => canClick && onGo(s.key)}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition-colors
              ${isCurrent ? "bg-primary/10 font-semibold text-primary" : ""}
              ${!isCurrent && canClick ? "hover:bg-muted" : ""}
              ${st === "locked" ? "opacity-40 cursor-not-allowed" : "cursor-pointer"}
            `}
          >
            <StepIcon state={st} num={s.num} />
            <span className="flex-1">{s.label}</span>
            {isCurrent && <ChevronRight className="h-4 w-4 text-primary" />}
            {st === "done" && !isCurrent && (
              <Badge variant="outline" className="text-xs text-green-600 border-green-300">OK</Badge>
            )}
          </button>
        );
      })}
    </nav>
  );
}

// ─── Individual step panels ───────────────────────────────────────────────────

function DatosTxtGuide({ datos, onValidez }: { datos: File | null; onValidez: (ok: boolean) => void }) {
  const [errores, setErrores] = useState<string[] | null>(null);
  const [lineas, setLineas] = useState<string[]>([]);

  useEffect(() => {
    if (!datos) {
      setErrores(null);
      setLineas([]);
      onValidez(false);
      return;
    }
    let cancelado = false;
    datos.arrayBuffer().then((buf) => {
      if (cancelado) return;
      const v = validarDatosTxt(decodificarDatos(buf));
      setErrores(v.errores);
      setLineas(v.lineas);
      onValidez(v.errores.length === 0);
    });
    return () => {
      cancelado = true;
    };
    // onValidez es un setter de estado estable del padre
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datos]);

  const ok = errores !== null && errores.length === 0;

  return (
    <Card className={ok ? "border-green-200" : errores?.length ? "border-destructive/40" : ""}>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base">Formato del DATOS.txt — {DATOS_OBLIGATORIAS} líneas obligatorias</CardTitle>
          <Button
            size="sm"
            variant="outline"
            onClick={() => downloadBlob(new Blob([plantillaDatosTxt()], { type: "text/plain;charset=utf-8" }), "DATOS.txt")}
          >
            <FileDown className="mr-1 h-4 w-4" /> Descargar plantilla
          </Button>
        </div>
        <CardDescription>
          Un dato por línea, en este orden exacto, sin líneas vacías intermedias. Las líneas 10 y 11 son las que el
          SII revisa en la carátula: si faltan, rechaza el envío con <code className="rounded bg-muted px-1">CRT-3-19 Fecha/Numero Resolucion Invalido</code>.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <tbody>
              {DATOS_LINEAS.map((d) => {
                const valor = lineas[d.n - 1];
                const cargado = errores !== null;
                return (
                  <tr key={d.n} className="border-t">
                    <td className="w-8 py-1.5 pr-2 font-mono text-muted-foreground">{d.n}</td>
                    <td className="py-1.5 pr-3">
                      <span className={d.opcional ? "text-muted-foreground" : "font-medium text-foreground"}>{d.nombre}</span>
                      {d.nota && <span className="block text-[11px] text-muted-foreground">{d.nota}</span>}
                    </td>
                    <td className="py-1.5 font-mono text-[11px] text-muted-foreground">
                      {cargado ? (
                        valor ? (
                          <span className="text-foreground">{d.n === 5 ? "••••••" : valor}</span>
                        ) : d.opcional ? (
                          <span className="opacity-60">—</span>
                        ) : (
                          <span className="text-destructive">falta</span>
                        )
                      ) : (
                        <span className="opacity-70">{d.ejemplo}</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <p className="mt-3 text-[11px] text-muted-foreground">
          La fecha de resolución se consulta en <em>maullin.sii.cl → Mi SII → datos de la empresa</em> (ambiente de
          certificación). Guarda el archivo como texto plano (UTF-8 o ANSI).
        </p>

        {errores && errores.length > 0 && (
          <Alert variant="destructive" className="mt-3">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              <p className="font-semibold">Corrige el DATOS.txt antes de continuar:</p>
              <ul className="mt-1 list-disc pl-4">
                {errores.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}
        {ok && (
          <p className="mt-3 flex items-center gap-1.5 text-xs text-green-700">
            <CheckCircle2 className="h-4 w-4" /> DATOS.txt válido — {lineas[2]} ({lineas[3]}), resolución N° {lineas[9]} del {lineas[10]}.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function SetupStep({
  onDone,
}: {
  onDone: (files: SharedFiles) => void;
}) {
  const [pfx, setPfx] = useState<File | null>(null);
  const [datos, setDatos] = useState<File | null>(null);
  const [datosOk, setDatosOk] = useState(false);
  const [caf33, setCaf33] = useState<File | null>(null);
  const [caf56, setCaf56] = useState<File | null>(null);
  const [caf61, setCaf61] = useState<File | null>(null);
  const [caf46, setCaf46] = useState<File | null>(null);
  const [claveError, setClaveError] = useState(false);

  const ready = !!pfx && !!datos && datosOk && !!(caf33 || caf56 || caf61 || caf46);

  async function handleGuardarYContinuar() {
    const clave = window.prompt("Ingresa la clave para continuar:");
    if (clave === null) return; // canceló
    try {
      const res = await fetch("/api/check-clave", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clave }),
      });
      const data = (await res.json()) as { ok?: boolean };
      if (!data.ok) {
        setClaveError(true);
        return;
      }
    } catch {
      setClaveError(true);
      return;
    }
    setClaveError(false);
    onDone({ pfx: pfx!, datos: datos!, clave, cafs: { ...(caf33 && { "33": caf33 }), ...(caf56 && { "56": caf56 }), ...(caf61 && { "61": caf61 }), ...(caf46 && { "46": caf46 }) } });
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Configuración inicial</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Antes de empezar necesitas tener 3 cosas del SII: tu <strong>certificado digital</strong>,
          el <strong>archivo DATOS.txt</strong> con los datos de tu empresa, y los <strong>archivos CAF</strong>
          que el SII te entrega al solicitar folios autorizados.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">¿Cómo obtener estos archivos?</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <div className="flex gap-3">
            <span className="text-xl">🔑</span>
            <div>
              <strong className="text-foreground">Certificado digital (.p12 / .pfx)</strong> — Lo obtiene el representante
              legal en el SII. Ir a <em>maullin.sii.cl → Mi SII → Administrar Certificados Digitales</em>.
            </div>
          </div>
          <div className="flex gap-3">
            <span className="text-xl">📋</span>
            <div>
              <strong className="text-foreground">DATOS.txt</strong> — Créalo tú con un editor de texto: son{" "}
              <strong className="text-foreground">{DATOS_OBLIGATORIAS} líneas obligatorias</strong> (ver formato más abajo, con plantilla
              descargable). Incluye el número y fecha de resolución del SII.
            </div>
          </div>
          <div className="flex gap-3">
            <span className="text-xl">🧾</span>
            <div>
              <strong className="text-foreground">CAF (Código de Autorización de Folios)</strong> — Solicítalo en
              <em> maullin.sii.cl → Boletas y Documentos → Solicitar Folios</em>. Pide un CAF por
              cada tipo de DTE que quieras certificar (T33, T56, T61, T46).
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        <UploadBox label="Certificado .pfx / .p12" hint="Firma digital del representante legal" icon="🔑" accept=".pfx,.p12" file={pfx} onChange={setPfx} />
        <UploadBox label="DATOS.txt" hint="11 líneas: representante, empresa, clave PFX, giro, acteco, dirección, comuna, N° y fecha de resolución" icon="👤" accept=".txt" file={datos} onChange={setDatos} />
      </div>

      <DatosTxtGuide datos={datos} onValidez={setDatosOk} />

      <div>
        <p className="mb-2 text-sm font-medium">Archivos CAF (uno por tipo de documento)</p>
        <div className="grid gap-3 sm:grid-cols-3">
          <UploadBox label="CAF Factura Electrónica" hint="dte33d1a100.xml" icon="🧾" accept=".xml" optionalTag="T33" file={caf33} onChange={setCaf33} />
          <UploadBox label="CAF Nota de Crédito" hint="dte61d1a100.xml" icon="📉" accept=".xml" optionalTag="T61" file={caf61} onChange={setCaf61} />
          <UploadBox label="CAF Nota de Débito" hint="dte56d1a100.xml" icon="📈" accept=".xml" optionalTag="T56" file={caf56} onChange={setCaf56} />
          <UploadBox label="CAF Factura de Compra" hint="dte46d1a100.xml" icon="🛒" accept=".xml" optionalTag="T46" file={caf46} onChange={setCaf46} />
        </div>
      </div>

      <Button size="lg" disabled={!ready} onClick={handleGuardarYContinuar}>
        Guardar y continuar →
      </Button>
      {claveError && (
        <p className="text-sm text-destructive">Clave incorrecta.</p>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

interface SharedFiles {
  pfx: File;
  datos: File;
  cafs: Record<string, File>;
  clave: string;
}

function Etapa1Step({
  shared,
  onDone,
}: {
  shared: SharedFiles;
  onDone: (result: BatchResult) => void;
}) {
  const [setF, setSetF] = useState<File | null>(null);
  const [nroBasico, setNroBasico] = useState("");
  const [nroVentas, setNroVentas] = useState("");
  const [nroCompras, setNroCompras] = useState("");
  const [foliosIni, setFoliosIni] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BatchResult | null>(null);
  const [error, setError] = useState("");

  const ready = !!setF && !!nroBasico;

  async function generate() {
    setLoading(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("set_pruebas", setF!);
      fd.append("datos", shared.datos);
      fd.append("pfx", shared.pfx);
      if (shared.cafs["33"]) fd.append("caf_33", shared.cafs["33"]);
      if (shared.cafs["56"]) fd.append("caf_56", shared.cafs["56"]);
      if (shared.cafs["61"]) fd.append("caf_61", shared.cafs["61"]);
      if (shared.cafs["46"]) fd.append("caf_46", shared.cafs["46"]);
      if (nroBasico)  fd.append("nro_atencion_basico", nroBasico);
      if (nroVentas)  fd.append("nro_atencion_ventas", nroVentas);
      if (nroCompras) fd.append("nro_atencion_compras", nroCompras);
      for (const [tipo, folio] of Object.entries(foliosIni)) {
        if (folio.trim()) fd.append(`folio_inicial_${tipo}`, folio.trim());
      }
      const data = await postForm("/api/sii/certificar", fd, shared.clave) as BatchResult;
      setResult(data);
      onDone(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Etapa 1 — Set de Pruebas</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          El SII te entrega un archivo <strong>.txt</strong> con 8 casos de prueba que debes certificar:
          4 Facturas (T33), 3 Notas de Crédito (T61) y 1 Nota de Débito (T56).
          Aquí generamos todos los XMLs firmados y los PDFs, listos para subir al portal.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">¿Cómo obtener el Set de Pruebas y los Nº de Atención?</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground space-y-2">
          <p>
            1. Entra al portal SII de certificación: <strong>maullin.sii.cl</strong>
          </p>
          <p>
            2. Ve a <em>Boletas y Documentos → Certificación de Software → Set de Pruebas</em>
          </p>
          <p>
            3. Descarga el archivo <strong>SIISetDePruebas{"{RUT}"}.txt</strong>
          </p>
          <p>
            4. En esa misma sección anota los <strong>Números de Atención</strong> para Set Básico,
            Libro de Ventas y Libro de Compras — los necesitas para generar los libros.
          </p>
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <UploadBox
            label="SIISetDePruebas*.txt"
            hint="Archivo de casos de prueba descargado del portal SII"
            icon="📋"
            accept=".txt"
            file={setF}
            onChange={setSetF}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="nro-basico">Nº Atención Set Básico <span className="text-red-500">*</span></Label>
          <Input id="nro-basico" placeholder="ej. 4809211" value={nroBasico} onChange={e => setNroBasico(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="nro-ventas">Nº Atención Libro de Ventas</Label>
          <Input id="nro-ventas" placeholder="ej. 4809212 (opcional)" value={nroVentas} onChange={e => setNroVentas(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="nro-compras">Nº Atención Libro de Compras</Label>
          <Input id="nro-compras" placeholder="ej. 4809213 (opcional)" value={nroCompras} onChange={e => setNroCompras(e.target.value)} />
        </div>
      </div>

      {Object.keys(shared.cafs).length > 0 && (
        <div>
          <p className="mb-1 text-sm font-medium">Folio inicial por tipo (opcional)</p>
          <p className="mb-2 text-xs text-muted-foreground">
            Si un folio ya se usó en un envío previo (aunque el SII lo haya rechazado), indica desde qué folio
            empezar: el SII rechaza folios repetidos con DTE-3-100. En blanco = primer folio del CAF.
          </p>
          <div className="grid gap-3 sm:grid-cols-4">
            {Object.keys(shared.cafs).sort().map(tipo => (
              <div className="space-y-1" key={tipo}>
                <Label htmlFor={`folio-${tipo}`}>Folio inicial T{tipo}</Label>
                <Input
                  id={`folio-${tipo}`}
                  type="number"
                  min="1"
                  placeholder="auto"
                  value={foliosIni[tipo] ?? ""}
                  onChange={e => setFoliosIni(prev => ({ ...prev, [tipo]: e.target.value }))}
                />
              </div>
            ))}
          </div>
        </div>
      )}

      <Button size="lg" disabled={!ready || loading} onClick={generate}>
        {loading ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Generando XMLs y PDFs…</> : "Generar Set de Pruebas"}
      </Button>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {result && (
        <div className="space-y-5">
          <div className="flex items-center gap-3 rounded-lg bg-green-50 border border-green-200 px-4 py-3">
            <CheckCircle2 className="h-5 w-5 text-green-600" />
            <div className="flex-1 text-sm text-green-800">
              <strong>Archivos generados.</strong> Descarga el ZIP y <strong>guárdalo</strong>: el EnvioDTE, los libros y
              los PDFs de la Etapa 4 deben salir de <em>esta misma</em> descarga. Cada "Generar" firma de nuevo los
              TED, y el SII rechaza PDFs cuya firma no coincida con el XML que aprobó.
            </div>
            <Button
              size="sm"
              variant="outline"
              className="border-green-400 text-green-700 hover:bg-green-100"
              onClick={() => downloadB64(result.zip_base64 ?? "", "etapa1_certificacion.zip")}
            >
              <Download className="mr-1 h-4 w-4" /> Descargar ZIP
            </Button>
          </div>

          <PortalGuide
            title="Subir al portal SII — Etapa 1"
            url="https://maullin.sii.cl/cgi_dte/UPL/DTEUpload"
            steps={[
              { text: "Entra a maullin.sii.cl con tu RUT y clave del SII" },
              { text: "Ve a: Boletas y Documentos → Certificación DTE → Envío de Documentos" },
              { text: "Sube EnvioDTE_{RUT}.xml — anota el Identificador de Envío", highlight: true },
              { text: "Sube LibroVentas_{RUT}.xml de la misma forma" },
              { text: "Sube LibroCompras_{RUT}.xml (puede ser en periodo diferente, ej. 2000-02)" },
              { text: "Espera el email del SII o consulta el estado en el portal — busca EPR + AOK (sin reparos)", highlight: true },
            ]}
            note="Si el SII responde EPR pero con RCH en algún DTE, los folios quedan consumidos. Deberás generar nuevamente con folios distintos en los CAF."
          />

          <Results data={result} filename="etapa1_certificacion.zip" />
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function Etapa2Step({ shared, onDone }: { shared: SharedFiles; onDone: () => void }) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BatchResult | null>(null);
  const [error, setError] = useState("");
  const [folio33, setFolio33] = useState("");
  const [folio46, setFolio46] = useState("");
  const [folio61, setFolio61] = useState("");
  const [folio56, setFolio56] = useState("");
  const [modo, setModo] = useState<"basico" | "compra">("basico");

  const cafsBasico = ["33", "61", "56"].filter(t => !shared.cafs[t]);
  const cafsCompra = ["46", "61", "56"].filter(t => !shared.cafs[t]);
  const listo = modo === "compra" ? cafsCompra.length === 0 : cafsBasico.length === 0;

  async function generate() {
    setLoading(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("datos", shared.datos);
      fd.append("pfx", shared.pfx);
      fd.append("modo", modo);
      // Los folios van SIEMPRE (ambos modos): sin ellos el backend arranca en el
      // primer folio del CAF, que ya se consumió en Etapa 1 → DTE-3-100 repetido.
      if (modo === "compra") {
        if (shared.cafs["46"]) fd.append("caf_46", shared.cafs["46"]);
        if (folio46.trim()) fd.append("folio_46", folio46.trim());
      } else {
        if (shared.cafs["33"]) fd.append("caf_33", shared.cafs["33"]);
        if (folio33.trim()) fd.append("folio_33", folio33.trim());
      }
      if (shared.cafs["61"]) fd.append("caf_61", shared.cafs["61"]);
      if (shared.cafs["56"]) fd.append("caf_56", shared.cafs["56"]);
      if (folio61.trim()) fd.append("folio_61", folio61.trim());
      if (folio56.trim()) fd.append("folio_56", folio56.trim());
      const data = await postForm("/api/sii/etapa2", fd, shared.clave) as BatchResult;
      setResult(data);
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Etapa 2 — Simulación</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Emite DTEs reales a la empresa de prueba <strong>C&C SPA (77221286-0)</strong>.
          Elige qué tipo de simulación necesitas según lo que estés certificando.
        </p>
      </div>

      {/* Selector de modo */}
      <div className="grid gap-3 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => setModo("basico")}
          className={`rounded-lg border p-4 text-left transition-colors ${modo === "basico" ? "border-primary bg-primary/5 ring-1 ring-primary" : "hover:bg-muted"}`}
        >
          <p className="font-semibold">🧾 Set Básico</p>
          <p className="mt-1 text-xs text-muted-foreground">Factura (T33) → Nota de Crédito (T61) → Nota de Débito (T56)</p>
        </button>
        <button
          type="button"
          onClick={() => setModo("compra")}
          className={`rounded-lg border p-4 text-left transition-colors ${modo === "compra" ? "border-primary bg-primary/5 ring-1 ring-primary" : "hover:bg-muted"}`}
        >
          <p className="font-semibold">🛒 Factura de Compra</p>
          <p className="mt-1 text-xs text-muted-foreground">Factura de Compra (T46) con retención total del IVA</p>
        </button>
      </div>

      <Card className="border-amber-200 bg-amber-50">
        <CardContent className="pt-4 text-sm text-amber-800 space-y-2">
          {modo === "basico" ? (
            <>
              <p className="font-semibold">Simulación Set Básico — 3 DTEs</p>
              <div className="flex gap-2"><span>🧾</span><span><strong>T33 — Factura:</strong> 2 × Producto @ $35.000 → Total $83.300 (con IVA 19%)</span></div>
              <div className="flex gap-2"><span>📉</span><span><strong>T61 — Nota de Crédito:</strong> Devolución parcial de 1 unidad → $41.650</span></div>
              <div className="flex gap-2"><span>📈</span><span><strong>T56 — Nota de Débito:</strong> Anula la NC anterior → $41.650</span></div>
            </>
          ) : (
            <>
              <p className="font-semibold">Simulación Factura de Compra — 3 DTEs</p>
              <div className="flex gap-2"><span>🛒</span><span><strong>T46 — Factura de Compra:</strong> 2 × Producto @ $35.000 → Neto $70.000, IVA retenido $13.300 (el proveedor recibe solo el neto)</span></div>
              <div className="flex gap-2"><span>📉</span><span><strong>T61 — Nota de Crédito:</strong> Devolución de 1 unidad, referencia la Factura de Compra (IVA retenido)</span></div>
              <div className="flex gap-2"><span>📈</span><span><strong>T56 — Nota de Débito:</strong> Anula la NC anterior (IVA retenido)</span></div>
            </>
          )}
        </CardContent>
      </Card>

      <div className="grid max-w-2xl gap-4 sm:grid-cols-3">
        {modo === "compra" ? (
          <div className="space-y-1">
            <Label htmlFor="folio-46-sim">Folio T46 — Factura de Compra</Label>
            <Input id="folio-46-sim" type="number" min="1" placeholder="primer folio del CAF" value={folio46} onChange={e => setFolio46(e.target.value)} />
          </div>
        ) : (
          <div className="space-y-1">
            <Label htmlFor="folio-33-sim">Folio T33 — Factura</Label>
            <Input id="folio-33-sim" type="number" min="1" placeholder="primer folio del CAF" value={folio33} onChange={e => setFolio33(e.target.value)} />
          </div>
        )}
        <div className="space-y-1">
          <Label htmlFor="folio-61-sim">Folio T61 — Nota de Crédito</Label>
          <Input id="folio-61-sim" type="number" min="1" placeholder="primer folio del CAF" value={folio61} onChange={e => setFolio61(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="folio-56-sim">Folio T56 — Nota de Débito</Label>
          <Input id="folio-56-sim" type="number" min="1" placeholder="primer folio del CAF" value={folio56} onChange={e => setFolio56(e.target.value)} />
        </div>
        <p className="text-xs text-muted-foreground sm:col-span-3">
          ⚠️ Usa folios que <strong>no</strong> hayas enviado en la Etapa 1 (ni en envíos rechazados): el SII rechaza
          folios repetidos con DTE-3-100. En blanco se usa el primer folio del CAF, que normalmente ya está consumido.
        </p>
      </div>

      {!listo && (
        <Alert>
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            {modo === "compra"
              ? `Faltan CAFs para la Factura de Compra: ${cafsCompra.map(t => "T" + t).join(", ")}. Súbelos en Configuración.`
              : `Faltan CAFs para el Set Básico: ${cafsBasico.map(t => "T" + t).join(", ")}. Súbelos en Configuración.`}
          </AlertDescription>
        </Alert>
      )}

      <Button size="lg" disabled={loading || !listo} onClick={generate}>
        {loading
          ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Generando simulación…</>
          : modo === "compra" ? "Generar Factura de Compra" : "Generar DTEs de Simulación"}
      </Button>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {result && (
        <div className="space-y-5">
          <div className="flex items-center gap-3 rounded-lg bg-green-50 border border-green-200 px-4 py-3">
            <CheckCircle2 className="h-5 w-5 text-green-600" />
            <div className="flex-1 text-sm text-green-800"><strong>Simulación generada.</strong></div>
            <Button size="sm" variant="outline" className="border-green-400 text-green-700 hover:bg-green-100"
              onClick={() => downloadB64(result.zip_base64 ?? "", "etapa2_simulacion.zip")}>
              <Download className="mr-1 h-4 w-4" /> Descargar ZIP
            </Button>
          </div>

          <PortalGuide
            title="Subir al portal SII — Etapa 2"
            url="https://maullin.sii.cl/cgi_dte/UPL/DTEUpload"
            steps={[
              { text: "Entra a maullin.sii.cl → Certificación DTE → Envío de Documentos" },
              { text: "Sube EnvioDTE_{RUT}.xml de la simulación", highlight: true },
              { text: "En la carátula del XML, el RutReceptor es 60803000-K (portal SII) pero los DTEs van a C&C SPA" },
              { text: "Espera respuesta EPR + 3/3 AOK sin reparos", highlight: true },
              { text: "Una vez aprobada, avanza a Etapa 3" },
            ]}
          />
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function Etapa3Step({ shared, onDone }: { shared: SharedFiles; onDone: () => void }) {
  const [setXml, setSetXml] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BatchResult | null>(null);
  const [error, setError] = useState("");

  async function generate() {
    setLoading(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("set_intercambio", setXml!);
      // Certificado y DATOS.txt ya validados en Configuración — no se piden de nuevo.
      fd.append("pfx", shared.pfx);
      fd.append("datos", shared.datos);
      const data = await postForm("/api/sii/etapa3", fd, shared.clave) as BatchResult;
      setResult(data);
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Etapa 3 — Intercambio</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          El SII te envía un SET XML con DTEs de otra empresa — algunos son <strong>para ti</strong>
          (debes aceptarlos) y otros son <strong>ajenos</strong> (debes rechazarlos indicando
          error en RUT receptor). Debes responder con 3 archivos XML firmados.
        </p>
      </div>

      <PortalGuide
        title="Paso 1 — Descargar el SET de Intercambio del portal"
        url="https://maullin.sii.cl"
        steps={[
          { text: "Entra a maullin.sii.cl → Certificación DTE → Intercambio de Documentos" },
          { text: "El SII habrá depositado un SET XML con DTEs para procesar" },
          { text: "Descarga el archivo ENVIO_DTE_{N°Atención}.xml", highlight: true },
          { text: "⚠️ Si lo descargas más de una vez, el SII genera un NUEVO N° Atención — usa siempre el último descargado", highlight: true },
        ]}
        note="Cada descarga crea un nuevo N° Atención. El SII valida contra el último. Siempre usa el archivo más reciente."
      />

      <div className="grid gap-4 sm:grid-cols-2">
        <UploadBox
          label="ENVIO_DTE_*.xml"
          hint="SET recibido del SII — usar el último descargado"
          icon="📥"
          accept=".xml"
          file={setXml}
          onChange={setSetXml}
        />
        <div className="rounded-lg border bg-muted/30 p-4 text-xs text-muted-foreground">
          <p className="font-semibold text-foreground">Se firma con lo cargado en Configuración</p>
          <p className="mt-1">🔑 {shared.pfx.name}</p>
          <p>👤 {shared.datos.name}</p>
        </div>
      </div>

      <Button size="lg" disabled={!setXml || loading} onClick={generate}>
        {loading
          ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Generando respuestas…</>
          : "Generar 3 XMLs de Respuesta"}
      </Button>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {result && (
        <div className="space-y-5">
          <div className="flex items-center gap-3 rounded-lg bg-green-50 border border-green-200 px-4 py-3">
            <CheckCircle2 className="h-5 w-5 text-green-600" />
            <div className="flex-1 text-sm text-green-800">
              <strong>3 archivos generados.</strong> Descarga y súbelos al portal en este orden exacto.
            </div>
            <Button size="sm" variant="outline" className="border-green-400 text-green-700 hover:bg-green-100"
              onClick={() => downloadB64(result.zip_base64 ?? "", "etapa3_intercambio.zip")}>
              <Download className="mr-1 h-4 w-4" /> Descargar ZIP
            </Button>
          </div>

          <PortalGuide
            title="Paso 2 — Subir los 3 XMLs de respuesta al portal"
            url="https://maullin.sii.cl"
            steps={[
              { text: "Ir a maullin.sii.cl → Certificación DTE → Intercambio → Respuesta Intercambio" },
              { text: "Subir primero: 1_RecepcionDTE.xml — acuse de recepción del envío", highlight: true },
              { text: "Subir segundo: 2_EnvioRecibos.xml — acuse de recibo de mercaderías", highlight: true },
              { text: "Subir tercero: 3_ResultadoDTE.xml — resultado comercial (aceptado/rechazado)", highlight: true },
              { text: "Verificar que los 3 aparezcan como OK en el portal" },
            ]}
            note='DTEs donde el RUT receptor no es el tuyo deben ir rechazados (EstadoRecepDTE=3). Ya viene configurado automáticamente.'
          />
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function Etapa4Step({ shared }: { shared: SharedFiles }) {
  const [xml1, setXml1] = useState<File | null>(null);
  const [xml2, setXml2] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BatchResult | null>(null);
  const [error, setError] = useState("");

  async function generate() {
    setLoading(true);
    setError("");
    try {
      const fd = new FormData();
      if (xml1) fd.append("envio_basico", xml1);
      if (xml2) fd.append("envio_simulacion", xml2);
      const data = await postForm("/api/sii/etapa4", fd, shared.clave) as BatchResult;
      setResult(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Etapa 4 — Muestras Impresas</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Debes subir al portal un <strong>PDF por cada DTE</strong> de las Etapas 1 y 2.
          El SII valida que el barcode PDF417 tenga el TED correcto (firma válida, CAF íntegro).
          Para un set básico típico (4 T33 + 3 T61 + 1 T56) más la simulación son <strong>16 PDFs</strong>.
        </p>
      </div>

      <Card className="border-blue-100 bg-blue-50">
        <CardContent className="pt-4 text-sm text-blue-800 space-y-1">
          <p className="font-semibold">¿Qué PDFs necesitas?</p>
          <p>• Set Básico: cada Factura (T33) en ejemplar tributario <strong>y</strong> cedible; NC (T61) y ND (T56) solo tributario.</p>
          <p>• Simulación: lo mismo para los DTEs de la Etapa 2.</p>
          <p className="mt-2 text-xs">
            Sube los EnvioDTE XML <strong>exactamente iguales a los que subiste al SII</strong> (del mismo ZIP). Si
            regeneraste la Etapa 1 o 2 después de subirla, el TED cambió y el portal responde "Firma TED del timbre
            no coincide con firma TED del XML".
          </p>
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        <UploadBox
          label="EnvioDTE Set Básico (Etapa 1)"
          hint="EnvioDTE_{RUT}.xml generado en Etapa 1"
          icon="📄"
          accept=".xml"
          file={xml1}
          onChange={setXml1}
        />
        <UploadBox
          label="EnvioDTE Simulación (Etapa 2)"
          hint="EnvioDTE_{RUT}.xml generado en Etapa 2"
          icon="📄"
          accept=".xml"
          file={xml2}
          onChange={setXml2}
        />
      </div>

      <Button size="lg" disabled={(!xml1 && !xml2) || loading} onClick={generate}>
        {loading
          ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Generando PDFs…</>
          : "Generar PDFs de muestra"}
      </Button>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {result && (
        <div className="space-y-5">
          <div className="flex items-center gap-3 rounded-lg bg-green-50 border border-green-200 px-4 py-3">
            <CheckCircle2 className="h-5 w-5 text-green-600" />
            <div className="flex-1 text-sm text-green-800">
              <strong>PDFs generados.</strong> Descarga y súbelos al portal SII.
            </div>
            <Button size="sm" variant="outline" className="border-green-400 text-green-700 hover:bg-green-100"
              onClick={() => downloadB64(result.zip_base64 ?? "", "etapa4_muestras.zip")}>
              <Download className="mr-1 h-4 w-4" /> Descargar {result.pdfs_generados ?? ""} PDFs
            </Button>
          </div>

          <PortalGuide
            title="Subir Muestras Impresas al portal SII"
            url="https://maullin.sii.cl"
            steps={[
              { text: "Entra a maullin.sii.cl → Certificación DTE → Muestras Impresas" },
              { text: "RUT Empresa = la empresa que se certifica. RUT Proveedor = 78392059-K (PUDU TECNOLOGIA SPA, proveedor del software) — NO el receptor de prueba C&C SPA", highlight: true },
              { text: "Arrastra o selecciona los PDFs del ZIP descargado (prueba + simulación)", highlight: true },
              { text: "Verifica que los de prueba queden bajo 'PRUEBA' con su N° de caso y los de simulación bajo 'SIMULACIÓN', todos con ✓ en Timbre, Caf y Ted" },
              { text: "Si una fila queda naranja ('no hay archivo PDF') o cae en el grupo equivocado, elimínala y vuelve a subir ese PDF", highlight: true },
              { text: "Con los PDFs completos, 'Enviar al SII' inicia la Revisión; 'Rev. Func.' se llena después" },
            ]}
            note="'Firma TED del timbre no coincide' = el PDF salió de una corrida distinta al XML aprobado (usa el ZIP original). 'Ha habido alguna alteración en el CAF' = whitespace en el TED — regenera los PDFs desde el XML."
          />

          <Results data={result} filename="etapa4_muestras.zip" />
        </div>
      )}
    </div>
  );
}

// ─── Main wizard ──────────────────────────────────────────────────────────────

function CertWizard() {
  const [current, setCurrent] = useState<StepKey>("setup");
  const [status, setStatus] = useState<StepStatus>({
    setup:  "active",
    etapa1: "locked",
    etapa2: "locked",
    etapa3: "locked",
    etapa4: "locked",
  });
  const [shared, setShared] = useState<SharedFiles | null>(null);

  function unlock(key: StepKey) {
    setStatus(s => ({ ...s, [key]: s[key] === "locked" ? "active" : s[key] }));
  }
  function markDone(key: StepKey, next?: StepKey) {
    setStatus(s => ({ ...s, [key]: "done", ...(next ? { [next]: "active" } : {}) }));
  }

  return (
    <div className="min-h-screen bg-muted/30">
      {/* Header */}
      <header className="border-b bg-white px-6 py-4">
        <div className="mx-auto flex max-w-6xl items-center gap-4">
          <div>
            <h1 className="text-lg font-bold text-foreground">Certificador DTE</h1>
            <p className="text-xs text-muted-foreground">Guía paso a paso — Certificación SII Chile</p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <VersionBadge />
            <Badge variant="outline">Ambiente Certificación</Badge>
          </div>
        </div>
      </header>

      <div className="mx-auto flex max-w-6xl gap-6 px-4 py-8">
        {/* Sidebar stepper */}
        <aside className="w-56 shrink-0">
          <div className="sticky top-8">
            <p className="mb-3 text-xs font-bold uppercase tracking-wider text-muted-foreground">Progreso</p>
            <Stepper current={current} status={status} onGo={setCurrent} />

            <div className="mt-6 rounded-lg bg-muted/60 p-3 text-xs text-muted-foreground">
              <p className="font-semibold text-foreground mb-1">¿Qué es la certificación?</p>
              <p>El SII te pide demostrar que tu software puede emitir DTEs válidos antes de operar en producción. Son 4 etapas, cada una con un Nº de Atención.</p>
            </div>

            <div className="mt-6 rounded-xl border border-[#5D17EB]/10 bg-[#5D17EB]/5 p-3 text-center">
              <img src="/pudu-logo.png" alt="PUDU Tecnología" className="mx-auto h-12 w-12 object-contain" />
              <p className="mt-2 text-xs text-muted-foreground">
                Si necesitan trabajar con el certificador, deben comunicarse primero.
              </p>
              <a
                href="mailto:contacto@pudutecnologia.cl"
                className="mt-3 inline-block rounded-lg bg-[#5D17EB] px-4 py-2 text-xs font-bold text-white shadow-lg shadow-[#5D17EB]/20 transition-transform hover:scale-[1.02] hover:bg-[#5D17EB]/90"
              >
                Contactar a PUDU
              </a>
            </div>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 min-w-0">
          {current === "setup" && (
            <SetupStep
              onDone={files => {
                setShared(files);
                // Con los archivos ya cargados, desbloquear todas las etapas para
                // poder saltar directo a la que se necesite (ej. ir a Simulación
                // sin repetir la Etapa 1 si ya fue aprobada en el portal SII).
                setStatus(s => ({
                  ...s,
                  setup:  "done",
                  etapa1: s.etapa1 === "locked" ? "active" : s.etapa1,
                  etapa2: s.etapa2 === "locked" ? "active" : s.etapa2,
                  etapa3: s.etapa3 === "locked" ? "active" : s.etapa3,
                  etapa4: s.etapa4 === "locked" ? "active" : s.etapa4,
                }));
                setCurrent("etapa1");
              }}
            />
          )}
          {current === "etapa1" && shared && (
            <Etapa1Step
              shared={shared}
              onDone={() => {
                markDone("etapa1", "etapa2");
                unlock("etapa2");
              }}
            />
          )}
          {current === "etapa2" && shared && (
            <Etapa2Step
              shared={shared}
              onDone={() => {
                markDone("etapa2", "etapa3");
                unlock("etapa3");
              }}
            />
          )}
          {current === "etapa3" && shared && (
            <Etapa3Step
              shared={shared}
              onDone={() => {
                markDone("etapa3", "etapa4");
                unlock("etapa4");
              }}
            />
          )}
          {current === "etapa4" && shared && (
            <Etapa4Step shared={shared} />
          )}
        </main>
      </div>
    </div>
  );
}

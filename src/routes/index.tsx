import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { CheckCircle2, Circle, Loader2, Download, AlertCircle, ChevronRight, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { UploadBox } from "@/components/sii/UploadBox";
import { PortalGuide } from "@/components/sii/PortalGuide";
import { Results, type BatchResult } from "@/components/sii/Results";

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

async function postForm(path: string, fd: FormData) {
  const res = await fetch(path, { method: "POST", body: fd });
  const ct = res.headers.get("content-type") ?? "";
  const data = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    const msg =
      typeof data === "object" && data && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : typeof data === "string" ? data : `Error ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

function downloadB64(b64: string, filename: string) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length).map((_, i) => bin.charCodeAt(i));
  const url = URL.createObjectURL(new Blob([bytes]));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
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

function SetupStep({
  onDone,
}: {
  onDone: (files: { pfx: File; datos: File; cafs: Record<string, File> }) => void;
}) {
  const [pfx, setPfx] = useState<File | null>(null);
  const [datos, setDatos] = useState<File | null>(null);
  const [caf33, setCaf33] = useState<File | null>(null);
  const [caf56, setCaf56] = useState<File | null>(null);
  const [caf61, setCaf61] = useState<File | null>(null);
  const [claveError, setClaveError] = useState(false);

  const ready = !!pfx && !!datos && !!(caf33 || caf56 || caf61);

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
    onDone({ pfx: pfx!, datos: datos!, cafs: { ...(caf33 && { "33": caf33 }), ...(caf56 && { "56": caf56 }), ...(caf61 && { "61": caf61 }) } });
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
              <strong className="text-foreground">DATOS.txt</strong> — Créalo tú. Cada línea tiene un dato:
              <code className="ml-1 rounded bg-muted px-1 text-xs">
                nombre_rep · rut_rep · razón_social · rut_empresa · clave_pfx
              </code>
            </div>
          </div>
          <div className="flex gap-3">
            <span className="text-xl">🧾</span>
            <div>
              <strong className="text-foreground">CAF (Código de Autorización de Folios)</strong> — Solicítalo en
              <em> maullin.sii.cl → Boletas y Documentos → Solicitar Folios</em>. Pide un CAF por
              cada tipo de DTE que quieras certificar (T33, T56, T61).
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        <UploadBox label="Certificado .pfx / .p12" hint="Firma digital del representante legal" icon="🔑" accept=".pfx,.p12" file={pfx} onChange={setPfx} />
        <UploadBox label="DATOS.txt" hint="Línea 1: nombre rep · 2: rut_rep · 3: razón social · 4: rut empresa · 5: clave PFX" icon="👤" accept=".txt" file={datos} onChange={setDatos} />
      </div>

      <div>
        <p className="mb-2 text-sm font-medium">Archivos CAF (uno por tipo de documento)</p>
        <div className="grid gap-3 sm:grid-cols-3">
          <UploadBox label="CAF Factura Electrónica" hint="dte33d1a100.xml" icon="🧾" accept=".xml" optionalTag="T33" file={caf33} onChange={setCaf33} />
          <UploadBox label="CAF Nota de Crédito" hint="dte61d1a100.xml" icon="📉" accept=".xml" optionalTag="T61" file={caf61} onChange={setCaf61} />
          <UploadBox label="CAF Nota de Débito" hint="dte56d1a100.xml" icon="📈" accept=".xml" optionalTag="T56" file={caf56} onChange={setCaf56} />
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
      if (nroBasico)  fd.append("nro_atencion_basico", nroBasico);
      if (nroVentas)  fd.append("nro_atencion_ventas", nroVentas);
      if (nroCompras) fd.append("nro_atencion_compras", nroCompras);
      const data = await postForm("/api/sii/certificar", fd) as BatchResult;
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
              <strong>Archivos generados.</strong> Descarga el ZIP y sigue las instrucciones del portal.
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

  async function generate() {
    setLoading(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("datos", shared.datos);
      fd.append("pfx", shared.pfx);
      if (shared.cafs["33"]) fd.append("caf_33", shared.cafs["33"]);
      if (shared.cafs["56"]) fd.append("caf_56", shared.cafs["56"]);
      if (shared.cafs["61"]) fd.append("caf_61", shared.cafs["61"]);
      const data = await postForm("/api/sii/etapa2", fd) as BatchResult;
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
          Debes emitir <strong>3 DTEs reales</strong> a una empresa certificada: una Factura (T33),
          una Nota de Crédito (T61) que la corrija, y una Nota de Débito (T56) que anule la NC.
          El receptor es <strong>C&C SPA (77221286-0)</strong>, una empresa de prueba del SII.
        </p>
      </div>

      <Card className="border-amber-200 bg-amber-50">
        <CardContent className="pt-4 text-sm text-amber-800 space-y-2">
          <p className="font-semibold">¿Qué son los 3 DTEs de simulación?</p>
          <div className="flex gap-2">
            <span>🧾</span>
            <span><strong>T33 — Factura:</strong> Por ejemplo, 2 × Producto @ $35.000 → Monto total $83.300 (con IVA 19%)</span>
          </div>
          <div className="flex gap-2">
            <span>📉</span>
            <span><strong>T61 — Nota de Crédito:</strong> Devolución parcial de 1 unidad de esa factura → $41.650</span>
          </div>
          <div className="flex gap-2">
            <span>📈</span>
            <span><strong>T56 — Nota de Débito:</strong> Anula la NC anterior → $41.650</span>
          </div>
        </CardContent>
      </Card>

      <Button size="lg" disabled={loading} onClick={generate}>
        {loading
          ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Generando simulación…</>
          : "Generar DTEs de Simulación"}
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

function Etapa3Step({ onDone }: { onDone: () => void }) {
  const [setXml, setSetXml] = useState<File | null>(null);
  const [pfx, setPfx] = useState<File | null>(null);
  const [datos, setDatos] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BatchResult | null>(null);
  const [error, setError] = useState("");

  async function generate() {
    setLoading(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("set_intercambio", setXml!);
      fd.append("pfx", pfx!);
      fd.append("datos", datos!);
      const data = await postForm("/api/sii/etapa3", fd) as BatchResult;
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

      <div className="grid gap-4 sm:grid-cols-3">
        <UploadBox
          label="ENVIO_DTE_*.xml"
          hint="SET recibido del SII — usar el último descargado"
          icon="📥"
          accept=".xml"
          file={setXml}
          onChange={setSetXml}
        />
        <UploadBox label="Certificado .pfx / .p12" hint="Firma digital" icon="🔑" accept=".pfx,.p12" file={pfx} onChange={setPfx} />
        <UploadBox label="DATOS.txt" hint="Datos de la empresa" icon="👤" accept=".txt" file={datos} onChange={setDatos} />
      </div>

      <Button size="lg" disabled={!setXml || !pfx || !datos || loading} onClick={generate}>
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
      const data = await postForm("/api/sii/etapa4", fd) as BatchResult;
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
          En total son <strong>16 PDFs</strong>: 12 del Set Básico + 4 de la Simulación.
        </p>
      </div>

      <Card className="border-blue-100 bg-blue-50">
        <CardContent className="pt-4 text-sm text-blue-800 space-y-1">
          <p className="font-semibold">¿Qué PDFs necesitas?</p>
          <p>• Set Básico: T33 F33-36 (×2 tributaria+cedible), T61 F25-27, T56 F9 → <strong>12 PDFs</strong></p>
          <p>• Simulación: T33 F37 (×2), T61 F28, T56 F10 → <strong>4 PDFs</strong></p>
          <p className="mt-2 text-xs">
            Sube los EnvioDTE XML de cada etapa y generamos todos los PDFs con el barcode correcto.
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
          : "Generar 16 PDFs"}
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
              <Download className="mr-1 h-4 w-4" /> Descargar 16 PDFs
            </Button>
          </div>

          <PortalGuide
            title="Subir Muestras Impresas al portal SII"
            url="https://maullin.sii.cl"
            steps={[
              { text: "Entra a maullin.sii.cl → Certificación DTE → Muestras Impresas" },
              { text: "Ingresa el RUT Empresa y el RUT Proveedor (mismo RUT en ambos campos si eres el emisor)" },
              { text: "Arrastra o selecciona los 16 PDFs del ZIP descargado", highlight: true },
              { text: "Haz clic en 'Enviar al SII' — verifica que todos muestren ✓ en Timbre, Caf y Ted" },
              { text: "Si alguno muestra ✗, revisa el detalle del error en el portal", highlight: true },
            ]}
            note="El portal valida el barcode PDF417 de cada DTE. Si aparece 'Ha habido alguna alteración en el CAF' significa que el TED tiene whitespace incorrecto — regenera los PDFs."
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
          <Badge variant="outline" className="ml-auto">Ambiente Certificación</Badge>
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
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 min-w-0">
          {current === "setup" && (
            <SetupStep
              onDone={files => {
                setShared(files);
                markDone("setup", "etapa1");
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
          {current === "etapa3" && (
            <Etapa3Step
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

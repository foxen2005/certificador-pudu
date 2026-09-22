import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState, type ChangeEvent, type InputHTMLAttributes, type ReactNode } from "react";
import { AlertCircle, AlertTriangle, ArrowLeft, CheckCircle2, Download, Globe, Loader2, Lock, ShoppingCart, Truck, FileText } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PortalGuide } from "@/components/sii/PortalGuide";
import { Results, type BatchResult } from "@/components/sii/Results";
import { UploadBox } from "@/components/sii/UploadBox";
import { VersionBadge } from "@/components/VersionBadge";
import { decodificarDatos, validarDatosTxt } from "@/lib/datos-txt";

// Certificaciones adicionales — módulo INDEPENDIENTE del wizard del set básico
// (src/routes/index.tsx no se toca). Cada tipo de documento que el SII certifica
// con su propio set vive aquí: Exportación (110/111/112) hoy; Guía (52) y
// Factura Exenta (34) cuando tengamos su set de pruebas.

export const Route = createFileRoute("/adicionales")({
  head: () => ({
    meta: [
      { title: "Certificaciones adicionales — Certificador DTE" },
      { name: "description", content: "Exportación, guías de despacho y otros sets de certificación SII" },
    ],
  }),
  component: Adicionales,
});

const WIZARD_KEY_HEADER = "X-Wizard-Key";

function formatDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail.map((e) => (e && typeof e === "object" && "msg" in e ? String((e as { msg: unknown }).msg) : String(e))).join(" · ");
  return detail ? JSON.stringify(detail) : "Error";
}

async function postForm(path: string, fd: FormData, clave: string) {
  const res = await fetch(path, { method: "POST", body: fd, headers: { [WIZARD_KEY_HEADER]: encodeURIComponent(clave) } });
  const ct = res.headers.get("content-type") ?? "";
  const data = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    throw new Error(typeof data === "object" && data && "detail" in data ? formatDetail((data as { detail: unknown }).detail) : `Error ${res.status}`);
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

// Rango de folios del CAF (<RNG><D>1</D><H>100</H></RNG>) para validar en cliente
// antes de enviar: un folio fuera de rango o repetido quema el folio (DTE-3-100).
async function leerRangoCaf(file: File): Promise<{ tipo: number; desde: number; hasta: number } | null> {
  try {
    const txt = new TextDecoder("iso-8859-1").decode(await file.arrayBuffer());
    const td = /<TD>(\d+)<\/TD>/.exec(txt);
    const d = /<D>(\d+)<\/D>/.exec(txt);
    const h = /<H>(\d+)<\/H>/.exec(txt);
    if (!td || !d || !h) return null;
    return { tipo: Number(td[1]), desde: Number(d[1]), hasta: Number(h[1]) };
  } catch {
    return null;
  }
}

interface Shared {
  pfx: File;
  datos: File;
  clave: string;
}

// SiiTypes_v10.xsd → TipMonType (las de uso común primero)
const MONEDAS = ["DOLAR USA", "EURO", "PESO CL", "LIBRA EST", "YEN", "RENMINBI", "FRANCO SZ", "NUEVO SOL", "PESO COL", "PESO MEX", "PESO URUG", "OTRAS MONEDAS"];
const MOD_VENTA = [["1", "A firme"], ["2", "Bajo condición"], ["3", "Consignación libre"], ["4", "Consignación con mínimo a firme"], ["9", "Sin pago"]];
const CLAU_VENTA = [["", "— (no informar)"], ["5", "FOB"], ["1", "CIF"], ["2", "CFR"], ["3", "EXW"], ["4", "FAS"], ["7", "DAP"], ["9", "Otros"]];
const VIA_TRANSP = [["", "— (no informar)"], ["1", "Marítima"], ["4", "Aérea"], ["7", "Terrestre / carretera"], ["6", "Ferroviaria"], ["11", "Courier"], ["5", "Postal"]];

const SELECT_CLASS =
  "flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm " +
  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50";

// ─── Configuración (propia de esta página) ───────────────────────────────────

function Setup({ onDone }: { onDone: (s: Shared) => void }) {
  const [pfx, setPfx] = useState<File | null>(null);
  const [datos, setDatos] = useState<File | null>(null);
  const [errores, setErrores] = useState<string[] | null>(null);
  const [clave, setClave] = useState("");
  const [claveError, setClaveError] = useState("");
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    if (!datos) {
      setErrores(null);
      return;
    }
    let cancelado = false;
    datos.arrayBuffer().then((buf) => {
      if (!cancelado) setErrores(validarDatosTxt(decodificarDatos(buf)).errores);
    });
    return () => {
      cancelado = true;
    };
  }, [datos]);

  const ready = !!pfx && !!datos && errores !== null && errores.length === 0 && clave.trim() !== "";

  async function continuar() {
    setChecking(true);
    setClaveError("");
    try {
      const res = await fetch("/api/check-clave", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clave }),
      });
      const data = (await res.json()) as { ok?: boolean };
      if (!data.ok) {
        setClaveError("Clave incorrecta. Es la misma clave del wizard principal.");
        return;
      }
      onDone({ pfx: pfx!, datos: datos!, clave });
    } catch {
      setClaveError("No se pudo verificar la clave (sin conexión con el servidor).");
    } finally {
      setChecking(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Configuración</CardTitle>
        <CardDescription>
          El mismo certificado y <code className="rounded bg-muted px-1">DATOS.txt</code> del set básico (11 líneas; el
          formato está en la página principal). Los CAF se suben en cada módulo.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <UploadBox label="Certificado .pfx / .p12" hint="Firma digital del representante legal" icon="🔑" accept=".pfx,.p12" file={pfx} onChange={setPfx} />
          <UploadBox label="DATOS.txt" hint="11 líneas obligatorias (ver formato en el wizard principal)" icon="👤" accept=".txt" file={datos} onChange={setDatos} />
        </div>
        {errores && errores.length > 0 && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              <ul className="list-disc pl-4">{errores.map((e) => <li key={e}>{e}</li>)}</ul>
            </AlertDescription>
          </Alert>
        )}
        <div className="max-w-sm space-y-1">
          <Label htmlFor="clave">Clave del certificador</Label>
          <Input
            id="clave"
            type="password"
            autoComplete="current-password"
            value={clave}
            onChange={(e) => setClave(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && ready && continuar()}
            aria-invalid={!!claveError}
            aria-describedby={claveError ? "clave-error" : undefined}
          />
          {claveError && (
            <p id="clave-error" role="alert" className="flex items-center gap-1 text-sm text-destructive">
              <AlertCircle className="h-4 w-4" /> {claveError}
            </p>
          )}
        </div>
        <Button disabled={!ready || checking} onClick={continuar}>
          {checking ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Verificando…</> : "Continuar →"}
        </Button>
      </CardContent>
    </Card>
  );
}

// ─── Exportación 110 / 111 / 112 ─────────────────────────────────────────────

type CafSlot = { file: File | null; rango: { desde: number; hasta: number } | null; error: string; folio: string };
const cafVacio = (): CafSlot => ({ file: null, rango: null, error: "", folio: "" });

function CafConFolio({ tipo, label, icon, slot, onChange }: {
  tipo: 52 | 110 | 111 | 112;
  label: string;
  icon: string;
  slot: CafSlot;
  onChange: (s: CafSlot) => void;
}) {
  async function setFile(file: File | null) {
    if (!file) {
      onChange(cafVacio());
      return;
    }
    const r = await leerRangoCaf(file);
    if (!r) onChange({ file, rango: null, error: "No se pudo leer el rango de folios del CAF", folio: slot.folio });
    else if (r.tipo !== tipo) onChange({ file, rango: null, error: `Este CAF es tipo ${r.tipo}, no ${tipo}`, folio: slot.folio });
    else onChange({ file, rango: { desde: r.desde, hasta: r.hasta }, error: "", folio: slot.folio });
  }
  const folioNum = Number(slot.folio);
  const fueraDeRango = slot.rango && slot.folio.trim() !== "" && (folioNum < slot.rango.desde || folioNum > slot.rango.hasta);
  return (
    <div className="space-y-2">
      <UploadBox label={label} hint={slot.rango ? `folios ${slot.rango.desde}–${slot.rango.hasta}` : `tipo ${tipo}`} icon={icon} accept=".xml" optionalTag={`T${tipo}`} file={slot.file} onChange={setFile} />
      {slot.error && (
        <p role="alert" className="flex items-center gap-1 text-xs text-destructive"><AlertCircle className="h-3.5 w-3.5" /> {slot.error}</p>
      )}
      <div className="space-y-1">
        <Label htmlFor={`folio-${tipo}`} className="text-xs">Folio T{tipo}</Label>
        <Input
          id={`folio-${tipo}`}
          type="number"
          min={slot.rango?.desde ?? 1}
          max={slot.rango?.hasta}
          placeholder={slot.rango ? `primer libre (${slot.rango.desde})` : "primer folio del CAF"}
          value={slot.folio}
          aria-invalid={!!fueraDeRango}
          onChange={(e) => onChange({ ...slot, folio: e.target.value })}
        />
        {fueraDeRango && (
          <p role="alert" className="flex items-center gap-1 text-xs text-destructive"><AlertCircle className="h-3.5 w-3.5" /> Fuera del rango del CAF</p>
        )}
      </div>
    </div>
  );
}

interface ExpSetResult extends BatchResult {
  sets?: {
    nro_atencion: string;
    nombre: string;
    archivo: string;
    casos: { numero: string; tipo: number; folio: number; moneda: string; mnt_total: string; ind_servicio: string; fma_pag_exp: string }[];
  }[];
}

function Fieldset({ legend, hint, children }: { legend: string; hint?: string; children: ReactNode }) {
  return (
    <fieldset className="space-y-3 rounded-lg border p-4">
      <legend className="px-1 text-sm font-semibold">{legend}</legend>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      <div className="grid gap-4 sm:grid-cols-3">{children}</div>
    </fieldset>
  );
}

function Exportacion({ shared }: { shared: Shared }) {
  const [cafs, setCafs] = useState<Record<110 | 111 | 112, CafSlot>>({ 110: cafVacio(), 111: cafVacio(), 112: cafVacio() });
  const [form, setForm] = useState({
    producto: "",
    cantidad: "1",
    precio: "",
    moneda: "DOLAR USA",
    tipoCambio: "",
    receptorRazon: "",
    receptorDireccion: "",
    receptorCiudad: "",
    codPaisRecep: "",
    codModVenta: "1",
    codClauVenta: "5",
    codViaTransp: "1",
    codPtoEmbarque: "",
    codPtoDesemb: "",
    totBultos: "",
    codTpoBultos: "",
    pesoBruto: "",
  });
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BatchResult | null>(null);
  const [error, setError] = useState("");
  const [xmlMuestras, setXmlMuestras] = useState<File | null>(null);
  const [muestras, setMuestras] = useState<BatchResult | null>(null);
  const [loadingM, setLoadingM] = useState(false);
  const [setF, setSetF] = useState<File | null>(null);
  const [resultSet, setResultSet] = useState<ExpSetResult | null>(null);
  const [loadingS, setLoadingS] = useState(false);

  const set = (k: keyof typeof form) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const tipos = [110, 112, 111] as const;

  async function generarSet() {
    setLoadingS(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("set_pruebas", setF!);
      fd.append("datos", shared.datos);
      fd.append("pfx", shared.pfx);
      for (const t of tipos) {
        fd.append(`caf_${t}`, cafs[t].file!);
        if (cafs[t].folio.trim()) fd.append(`folio_${t}`, cafs[t].folio.trim());
      }
      fd.append("tipo_cambio", form.tipoCambio);
      if (form.receptorRazon.trim()) fd.append("receptor_razon", form.receptorRazon.trim());
      setResultSet((await postForm("/api/sii/adicionales/exportacion/set", fd, shared.clave)) as ExpSetResult);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoadingS(false);
    }
  }
  const cafsOk = tipos.every((t) => cafs[t].file && cafs[t].rango && !cafs[t].error);
  const foliosOk = tipos.every((t) => {
    const s = cafs[t];
    if (!s.rango || s.folio.trim() === "") return true;
    const n = Number(s.folio);
    return n >= s.rango.desde && n <= s.rango.hasta;
  });
  const obligatoriosOk = form.producto.trim() !== "" && form.precio.trim() !== "" && form.tipoCambio.trim() !== "" && form.receptorRazon.trim() !== "" && form.codPaisRecep.trim() !== "";
  const listo = cafsOk && foliosOk && obligatoriosOk;
  const foliosResumen = tipos.map((t) => `T${t}: ${cafs[t].folio.trim() || cafs[t].rango?.desde || "—"}`).join(" · ");

  async function generar() {
    setLoading(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("datos", shared.datos);
      fd.append("pfx", shared.pfx);
      for (const t of tipos) {
        fd.append(`caf_${t}`, cafs[t].file!);
        if (cafs[t].folio.trim()) fd.append(`folio_${t}`, cafs[t].folio.trim());
      }
      const campos: Record<string, string> = {
        producto: form.producto, cantidad: form.cantidad, precio: form.precio, moneda: form.moneda,
        tipo_cambio: form.tipoCambio, receptor_razon: form.receptorRazon, receptor_direccion: form.receptorDireccion,
        receptor_ciudad: form.receptorCiudad, cod_pais_recep: form.codPaisRecep, cod_mod_venta: form.codModVenta,
        cod_clau_venta: form.codClauVenta, cod_via_transp: form.codViaTransp, cod_pto_embarque: form.codPtoEmbarque,
        cod_pto_desemb: form.codPtoDesemb, tot_bultos: form.totBultos, cod_tpo_bultos: form.codTpoBultos, peso_bruto: form.pesoBruto,
      };
      Object.entries(campos).forEach(([k, v]) => fd.append(k, v));
      setResult((await postForm("/api/sii/adicionales/exportacion/simulacion", fd, shared.clave)) as BatchResult);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function generarMuestras() {
    setLoadingM(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("envio", xmlMuestras!);
      setMuestras((await postForm("/api/sii/adicionales/exportacion/muestras", fd, shared.clave)) as BatchResult);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoadingM(false);
    }
  }

  const field = (label: string, k: keyof typeof form, props: Partial<InputHTMLAttributes<HTMLInputElement>> & { requerido?: boolean } = {}) => {
    const { requerido, ...rest } = props;
    return (
      <div className="space-y-1">
        <Label htmlFor={`exp-${k}`}>{label}{requerido && <span className="text-destructive"> *</span>}</Label>
        <Input id={`exp-${k}`} value={form[k]} onChange={set(k)} required={requerido} aria-required={requerido} {...rest} />
      </div>
    );
  };
  const select = (label: string, k: keyof typeof form, opts: string[][]) => (
    <div className="space-y-1">
      <Label htmlFor={`exp-${k}`}>{label}</Label>
      <select id={`exp-${k}`} value={form[k]} onChange={set(k)} className={SELECT_CLASS}>
        {opts.map(([v, l]) => (
          <option key={v} value={v}>{l}</option>
        ))}
      </select>
    </div>
  );

  return (
    <div className="space-y-6">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold"><Globe className="h-5 w-5 text-primary" /> Exportación — Factura (110), Nota de Crédito (112) y Nota de Débito (111)</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Genera la cadena <strong>T110 → T112 (anula) → T111 (anula la NC)</strong> con receptor extranjero
          (RUT 55.555.555-5), montos en moneda extranjera y conversión a pesos. El XML se valida contra el XSD oficial
          del SII antes de entregarse. Sirve para la <em>simulación</em> y para probar envíos; el <em>set de pruebas</em>
          de exportación lo entrega el SII por contribuyente y se agrega aquí cuando lo tengamos.
        </p>
      </div>

      <PortalGuide
        title="Antes de generar — qué pide el SII"
        url="https://maullin.sii.cl/cvc/dte/menu_postulantes.html"
        steps={[
          { text: "Menú Postulantes → Postulación: marcar Factura (110), NC (112) y ND (111) de Exportación", highlight: true },
          { text: "Solicitar CAF de los tres tipos en el ambiente de certificación y subirlos abajo" },
          { text: "Los códigos de país, puertos, cláusula, modalidad, vía y bultos son tablas del Servicio Nacional de Aduanas: aduana.cl → Normativa → Anexos / Códigos" },
          { text: "Tipo de cambio: el del Banco Central (bcentral.cl) a la fecha de emisión; va en OtraMoneda" },
        ]}
      />

      <div>
        <p className="mb-2 text-sm font-medium">CAF y folio de cada documento</p>
        <div className="grid gap-4 sm:grid-cols-3">
          <CafConFolio tipo={110} label="CAF Factura de Exportación" icon="🧾" slot={cafs[110]} onChange={(s) => setCafs((c) => ({ ...c, 110: s }))} />
          <CafConFolio tipo={112} label="CAF Nota de Crédito Exp." icon="📉" slot={cafs[112]} onChange={(s) => setCafs((c) => ({ ...c, 112: s }))} />
          <CafConFolio tipo={111} label="CAF Nota de Débito Exp." icon="📈" slot={cafs[111]} onChange={(s) => setCafs((c) => ({ ...c, 111: s }))} />
        </div>
      </div>

      <Card className="border-primary/30">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">A · Set de pruebas del SII (certificación)</CardTitle>
          <CardDescription>
            Sube el <code className="rounded bg-muted px-1">SIISetDePruebas*.txt</code> con los "SET BASICO DOCUMENTOS DE EXPORTACION". El SII entrega
            dos sets (mercaderías con NC/ND; servicios, consignación y hotelería) que <strong>se envían por separado</strong>: se genera un EnvioDTE por set,
            con folios correlativos. Los códigos de Aduana (país, puertos, cláusula, vía, bultos, unidades, forma de pago) se resuelven desde los textos del set.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <UploadBox label="SIISetDePruebas*.txt" hint="Set de exportación descargado de maullin" icon="📋" accept=".txt" file={setF} onChange={setSetF} />
            <div className="space-y-1">
              <Label htmlFor="exp-set-tc">Tipo de cambio a CLP<span className="text-destructive"> *</span></Label>
              <Input id="exp-set-tc" type="number" min={0} step="0.0001" placeholder="ej. 945.37 (Banco Central, fecha de emisión)" value={form.tipoCambio} onChange={set("tipoCambio")} required aria-required />
            </div>
            <div className="space-y-1">
              <Label htmlFor="exp-set-rec">Razón social del importador (ficticio)</Label>
              <Input id="exp-set-rec" placeholder="IMPORTADOR DE PRUEBA" value={form.receptorRazon} onChange={set("receptorRazon")} />
            </div>
          </div>
          <Button size="lg" disabled={!setF || !cafsOk || !foliosOk || form.tipoCambio.trim() === "" || loadingS} onClick={generarSet}>
            {loadingS ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Generando sets y validando contra XSD…</> : "Generar documentos del set"}
          </Button>
          {!cafsOk && <p className="text-xs text-muted-foreground">Sube los tres CAF (110, 112, 111) arriba para habilitar el set.</p>}
          {error && !loading && (
            <Alert variant="destructive" role="alert">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          {resultSet && (
            <div className="space-y-4">
              <div className="flex items-center gap-3 rounded-lg border border-success/40 bg-success/5 px-4 py-3">
                <CheckCircle2 className="h-5 w-5 text-success" />
                <div className="flex-1 text-sm">
                  <strong>{resultSet.sets?.length} EnvioDTE generados y válidos según XSD.</strong> Descarga y guarda el ZIP (una carpeta por set).
                </div>
                <Button size="sm" variant="outline" onClick={() => downloadB64(resultSet.zip_base64 ?? "", "exportacion_set.zip")}>
                  <Download className="mr-1 h-4 w-4" /> Descargar ZIP
                </Button>
              </div>
              {resultSet.sets?.map((s) => (
                <div key={s.nro_atencion} className="overflow-x-auto rounded-lg border">
                  <div className="bg-muted/60 px-3 py-2 text-xs font-semibold">{s.nombre} — N° atención {s.nro_atencion} — <span className="font-mono">{s.archivo}</span></div>
                  <table className="w-full text-xs">
                    <thead className="text-left"><tr><th className="p-2">Caso</th><th className="p-2">Tipo</th><th className="p-2">Folio</th><th className="p-2">Moneda</th><th className="p-2">Total</th><th className="p-2">IndServicio</th><th className="p-2">FmaPagExp</th></tr></thead>
                    <tbody>
                      {s.casos.map((c) => (
                        <tr key={c.numero} className="border-t">
                          <td className="p-2 font-mono">{c.numero}</td><td className="p-2">{c.tipo}</td><td className="p-2 font-mono">{c.folio}</td>
                          <td className="p-2">{c.moneda}</td><td className="p-2 font-mono">{c.mnt_total}</td><td className="p-2">{c.ind_servicio || "—"}</td><td className="p-2">{c.fma_pag_exp || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
              <PortalGuide
                title="Subir al portal SII"
                url="https://maullin.sii.cl/cgi_dte/UPL/DTEUpload"
                steps={[
                  { text: "Certificación DTE → Envío de Documentos → subir el EnvioDTE del set (1); luego, en otro envío, el del set (2)", highlight: true },
                  { text: "Esperar EPR + AOK en todos los documentos de cada envío; declarar cada set en 'Revisión del Set'" },
                  { text: "Muestras impresas: PDFs de este mismo ZIP", highlight: true },
                ]}
              />
              <Results data={resultSet} filename="exportacion_set.zip" />
            </div>
          )}
        </CardContent>
      </Card>

      <div className="space-y-4">
        <h3 className="text-base font-semibold">B · Simulación (sin set)</h3>
        <p className="text-xs text-muted-foreground">Los campos marcados con <span className="text-destructive">*</span> son obligatorios. Todos los montos van en la moneda elegida; la exportación es exenta de IVA.</p>
        <Fieldset legend="Ítem y moneda">
          {field("Producto", "producto", { requerido: true, placeholder: "ej. Alfajores artesanales caja 12u" })}
          {field("Cantidad", "cantidad", { type: "number", min: 1, requerido: true })}
          {field("Precio unitario", "precio", { type: "number", min: 0, step: "0.01", requerido: true })}
          {select("Moneda (TpoMoneda)", "moneda", MONEDAS.map((m) => [m, m]))}
          {field("Tipo de cambio a CLP", "tipoCambio", { type: "number", min: 0, step: "0.0001", placeholder: "ej. 945.37", requerido: true })}
          {select("Modalidad de venta (CodModVenta)", "codModVenta", MOD_VENTA)}
        </Fieldset>
        <Fieldset legend="Receptor extranjero" hint="El RUT es siempre 55.555.555-5; el país va con el código de 3 dígitos de la tabla de Aduana.">
          {field("Razón social", "receptorRazon", { requerido: true, placeholder: "ACME IMPORTS LLC" })}
          {field("Dirección", "receptorDireccion")}
          {field("Ciudad", "receptorCiudad")}
          {field("País receptor (código Aduana)", "codPaisRecep", { requerido: true, placeholder: "ej. 225", inputMode: "numeric" })}
        </Fieldset>
        <Fieldset legend="Aduana y transporte" hint="El SII acepta envíos con solo la modalidad de venta (par 110/112 de referencia aceptado en certificación). El resto es opcional para la validación automática, pero el Manual de Muestras exige puertos, bultos y país en el PDF cuando hay transporte de mercaderías.">
          {select("Cláusula de venta (CodClauVenta)", "codClauVenta", CLAU_VENTA)}
          {select("Vía de transporte (CodViaTransp)", "codViaTransp", VIA_TRANSP)}
          {field("Puerto de embarque (código)", "codPtoEmbarque", { inputMode: "numeric" })}
          {field("Puerto de desembarque (código)", "codPtoDesemb", { inputMode: "numeric" })}
          {field("Total de bultos", "totBultos", { type: "number", min: 1, step: 1 })}
          {field("Tipo de bulto (código)", "codTpoBultos", { placeholder: "ej. 75 = caja", inputMode: "numeric" })}
          {field("Peso bruto (kg)", "pesoBruto", { type: "number", min: 0, step: "0.01" })}
        </Fieldset>
      </div>

      <Alert className="border-amber-300 bg-amber-50 text-amber-900 [&>svg]:text-amber-700">
        <AlertTriangle className="h-4 w-4" />
        <AlertDescription>
          Al generar se firman los folios <strong>{foliosResumen}</strong>. Un folio ya enviado al SII no se puede
          reutilizar (DTE-3-100), aunque el envío haya sido rechazado. Guarda el ZIP: los PDF de muestra deben salir del
          mismo XML que subas.
        </AlertDescription>
      </Alert>

      <Button size="lg" disabled={!listo || loading} onClick={generar}>
        {loading ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Generando y validando contra XSD…</> : "Generar DTEs de exportación"}
      </Button>

      {error && (
        <Alert variant="destructive" role="alert">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {result && (
        <div className="space-y-5">
          <div className="flex items-center gap-3 rounded-lg border border-success/40 bg-success/5 px-4 py-3">
            <CheckCircle2 className="h-5 w-5 text-success" />
            <div className="flex-1 text-sm">
              <strong>EnvioDTE de exportación generado y válido según XSD.</strong> Descarga y guarda el ZIP.
            </div>
            <Button size="sm" variant="outline" onClick={() => downloadB64(result.zip_base64 ?? "", "exportacion.zip")}>
              <Download className="mr-1 h-4 w-4" /> Descargar ZIP
            </Button>
          </div>
          <PortalGuide
            title="Subir al portal SII"
            url="https://maullin.sii.cl/cgi_dte/UPL/DTEUpload"
            steps={[
              { text: "Certificación DTE → Envío de Documentos → subir EnvioDTE_EXP_{RUT}.xml", highlight: true },
              { text: "Esperar EPR + 3/3 AOK. Si hay RCH, los folios quedan consumidos: regenerar con folios nuevos" },
              { text: "Las muestras impresas (abajo) deben generarse desde este mismo XML", highlight: true },
            ]}
          />
          <Results data={result} filename="exportacion.zip" />
        </div>
      )}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Muestras impresas desde un EnvioDTE ya enviado</CardTitle>
          <CardDescription>
            Sube el <code className="rounded bg-muted px-1">EnvioDTE_EXP_*.xml</code> que aprobó el SII y genera los PDFs
            (sin cedible: la Factura de Exportación no lo lleva según el Manual de Muestras §1.4).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="max-w-sm">
            <UploadBox label="EnvioDTE de exportación" hint="XML firmado subido al SII" icon="📄" accept=".xml" file={xmlMuestras} onChange={setXmlMuestras} />
          </div>
          <Button variant="outline" disabled={!xmlMuestras || loadingM} onClick={generarMuestras}>
            {loadingM ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Generando PDFs…</> : "Generar PDFs de muestra"}
          </Button>
          {muestras && (
            <div className="space-y-3">
              <Button size="sm" variant="outline" onClick={() => downloadB64(muestras.zip_base64 ?? "", "exportacion_muestras.zip")}>
                <Download className="mr-1 h-4 w-4" /> Descargar {muestras.pdfs_generados} PDFs
              </Button>
              <Results data={muestras} filename="exportacion_muestras.zip" />
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ─── Guía de Despacho 52 ─────────────────────────────────────────────────────

interface GuiaResult extends BatchResult {
  nro_atencion?: string;
  casos?: { numero: string; folio: number; motivo: string; ind_traslado: number; tipo_despacho: number | null; cedible: boolean }[];
}

// Tabla "Indicador Tipo de traslado de bienes" del Formato DTE v2.5
const TRASLADOS = [
  ["1", "1 — Operación constituye venta"],
  ["2", "2 — Ventas por efectuar"],
  ["3", "3 — Consignaciones"],
  ["4", "4 — Entrega gratuita"],
  ["5", "5 — Traslado interno"],
  ["6", "6 — Otros traslados no venta"],
  ["7", "7 — Devolución de mercaderías"],
];
const DESPACHOS = [
  ["", "— (sin indicar)"],
  ["1", "1 — Por cuenta del receptor (cliente)"],
  ["2", "2 — Por cuenta del emisor, al local del cliente"],
  ["3", "3 — Por cuenta del emisor, a otras instalaciones"],
];

function Guias({ shared }: { shared: Shared }) {
  const [setF, setSetF] = useState<File | null>(null);
  const [caf, setCaf] = useState<CafSlot>(cafVacio());
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<GuiaResult | null>(null);
  const [error, setError] = useState("");
  const [xmlMuestras, setXmlMuestras] = useState<File | null>(null);
  const [muestras, setMuestras] = useState<BatchResult | null>(null);
  const [loadingM, setLoadingM] = useState(false);
  // Los datos precargados los sirve el backend (`/simulacion/defaults`), que es
  // el dueño del receptor de prueba de la Etapa 2 del set básico: así no se
  // duplican aquí y no se desincronizan.
  const [sim, setSim] = useState({
    folio: "",
    traslados: ["5", "1"] as string[],
    tipoDespacho: "2",
    producto: "",
    cantidad: "1",
    precio: "",
    producto2: "",
    cantidad2: "1",
    precio2: "",
    receptorRut: "",
    receptorRazon: "",
    receptorGiro: "",
    receptorDir: "",
    receptorCmna: "",
  });

  useEffect(() => {
    let cancelado = false;
    fetch("/api/sii/adicionales/guias/simulacion/defaults", { headers: { [WIZARD_KEY_HEADER]: encodeURIComponent(shared.clave) } })
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { producto: string; cantidad: number; precio: number; traslados: number[]; tipo_despacho: number;
                  receptor: { rut: string; razon_social: string; giro: string; dir: string; cmna: string } } | null) => {
        if (!d || cancelado) return;
        setSim((s) => ({
          ...s,
          producto: s.producto || d.producto,
          cantidad: s.cantidad === "1" ? String(d.cantidad) : s.cantidad,
          precio: s.precio || String(d.precio),
          traslados: s.traslados.length ? s.traslados : d.traslados.map(String),
          tipoDespacho: s.tipoDespacho || String(d.tipo_despacho),
          receptorRut: s.receptorRut || d.receptor.rut,
          receptorRazon: s.receptorRazon || d.receptor.razon_social,
          receptorGiro: s.receptorGiro || d.receptor.giro,
          receptorDir: s.receptorDir || d.receptor.dir,
          receptorCmna: s.receptorCmna || d.receptor.cmna,
        }));
      })
      .catch(() => {});
    return () => {
      cancelado = true;
    };
  }, [shared.clave]);
  const [resultSim, setResultSim] = useState<GuiaResult | null>(null);
  const [loadingSim, setLoadingSim] = useState(false);
  const [errorSim, setErrorSim] = useState("");
  const setS = (k: keyof typeof sim) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setSim((s) => ({ ...s, [k]: e.target.value }));
  const simEsVenta = sim.traslados.some((t) => ["1", "2", "9"].includes(t));
  const simFolioOk = sim.folio.trim() !== "" && (!caf.rango || (Number(sim.folio) >= caf.rango.desde && Number(sim.folio) + sim.traslados.length - 1 <= caf.rango.hasta));
  const simListo =
    !!caf.file && !!caf.rango && !caf.error && sim.traslados.length > 0 && simFolioOk &&
    sim.producto.trim() !== "" && sim.precio.trim() !== "" &&
    sim.receptorRut.trim() !== "" && sim.receptorRazon.trim() !== "" &&
    (!simEsVenta || (sim.receptorGiro.trim() !== "" && sim.receptorDir.trim() !== "" && sim.receptorCmna.trim() !== ""));

  async function generarSim() {
    setLoadingSim(true);
    setErrorSim("");
    setResultSim(null);   // no dejar a la vista un resultado viejo si falla
    try {
      const fd = new FormData();
      fd.append("datos", shared.datos);
      fd.append("pfx", shared.pfx);
      fd.append("caf_52", caf.file!);
      if (sim.folio.trim()) fd.append("folio_inicial_52", sim.folio.trim());
      fd.append("traslados", sim.traslados.join(","));
      if (sim.tipoDespacho) fd.append("tipo_despacho", sim.tipoDespacho);
      fd.append("producto", sim.producto);
      fd.append("cantidad", sim.cantidad || "1");
      fd.append("precio", sim.precio);
      if (sim.producto2.trim()) {
        fd.append("producto_2", sim.producto2);
        fd.append("cantidad_2", sim.cantidad2 || "1");
        fd.append("precio_2", sim.precio2 || "0");
      }
      fd.append("receptor_rut", sim.receptorRut);
      fd.append("receptor_razon", sim.receptorRazon);
      fd.append("receptor_giro", sim.receptorGiro);
      fd.append("receptor_dir", sim.receptorDir);
      fd.append("receptor_cmna", sim.receptorCmna);
      setResultSim((await postForm("/api/sii/adicionales/guias/simulacion", fd, shared.clave)) as GuiaResult);
    } catch (e) {
      setErrorSim((e as Error).message);
    } finally {
      setLoadingSim(false);
    }
  }

  const folioNum = Number(caf.folio);
  const folioOk = !caf.rango || caf.folio.trim() === "" || (folioNum >= caf.rango.desde && folioNum <= caf.rango.hasta);
  const listo = !!setF && !!caf.file && !!caf.rango && !caf.error && folioOk;

  async function generar() {
    setLoading(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("set_pruebas", setF!);
      fd.append("datos", shared.datos);
      fd.append("pfx", shared.pfx);
      fd.append("caf_52", caf.file!);
      if (caf.folio.trim()) fd.append("folio_inicial_52", caf.folio.trim());
      setResult((await postForm("/api/sii/adicionales/guias/set", fd, shared.clave)) as GuiaResult);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function generarMuestras() {
    setLoadingM(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("envio", xmlMuestras!);
      setMuestras((await postForm("/api/sii/adicionales/guias/muestras", fd, shared.clave)) as BatchResult);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoadingM(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold"><Truck className="h-5 w-5 text-primary" /> Guía de Despacho (52)</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          <strong>A · Set de pruebas</strong> con el archivo del SII, y <strong>B · Simulación</strong> con tus productos y cliente reales.
          En ambos, el traslado interno lleva al propio emisor como receptor, sin precios ni cedible ni <code className="rounded bg-muted px-1">TipoDespacho</code>;
          la venta lleva neto/IVA/total y cedible "CEDIBLE CON SU FACTURA".
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <UploadBox label="SIISetDePruebas*.txt" hint="Debe contener 'SET GUIA DE DESPACHO - NUMERO DE ATENCIÓN'" icon="📋" accept=".txt" file={setF} onChange={setSetF} />
        <CafConFolio tipo={52} label="CAF Guía de Despacho" icon="🚚" slot={caf} onChange={setCaf} />
      </div>

      <Alert className="border-amber-300 bg-amber-50 text-amber-900 [&>svg]:text-amber-700">
        <AlertTriangle className="h-4 w-4" />
        <AlertDescription>
          Se consumen tantos folios como casos tenga el set (normalmente 3), correlativos desde el folio inicial. Un folio ya
          enviado al SII no se reutiliza (DTE-3-100), y el set y la simulación consumen folios distintos. Guarda cada ZIP:
          los PDF de muestra deben salir del mismo XML que subas.
        </AlertDescription>
      </Alert>

      <h3 className="text-base font-semibold">A · Set de pruebas del SII</h3>

      <Button size="lg" disabled={!listo || loading} onClick={generar}>
        {loading ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Generando y validando contra XSD…</> : "Generar guías del set"}
      </Button>

      {error && (
        <Alert variant="destructive" role="alert">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {result && (
        <div className="space-y-5">
          <div className="flex items-center gap-3 rounded-lg border border-success/40 bg-success/5 px-4 py-3">
            <CheckCircle2 className="h-5 w-5 text-success" />
            <div className="flex-1 text-sm">
              <strong>EnvioDTE de guías generado y válido según XSD</strong> — N° atención {result.nro_atencion}. Descarga y guarda el ZIP.
            </div>
            <Button size="sm" variant="outline" onClick={() => downloadB64(result.zip_base64 ?? "", "guias_set.zip")}>
              <Download className="mr-1 h-4 w-4" /> Descargar ZIP
            </Button>
          </div>
          {result.casos && (
            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full text-xs">
                <thead className="bg-muted/60 text-left">
                  <tr><th className="p-2">Caso</th><th className="p-2">Folio</th><th className="p-2">Motivo</th><th className="p-2">IndTraslado</th><th className="p-2">TipoDespacho</th><th className="p-2">Cedible</th></tr>
                </thead>
                <tbody>
                  {result.casos.map((c) => (
                    <tr key={c.numero} className="border-t">
                      <td className="p-2 font-mono">{c.numero}</td><td className="p-2 font-mono">{c.folio}</td><td className="p-2">{c.motivo}</td>
                      <td className="p-2">{c.ind_traslado}</td><td className="p-2">{c.tipo_despacho ?? "—"}</td><td className="p-2">{c.cedible ? "sí" : "no"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <PortalGuide
            title="Subir al portal SII"
            url="https://maullin.sii.cl/cgi_dte/UPL/DTEUpload"
            steps={[
              { text: "Certificación DTE → Envío de Documentos → subir EnvioDTE_GUIAS_{RUT}.xml", highlight: true },
              { text: "Esperar EPR + AOK en los 3 documentos; luego declarar el set en 'Revisión del Set'" },
              { text: "Muestras impresas: subir los PDF de este mismo ZIP (tributario de los 3, cedible solo de las ventas)", highlight: true },
            ]}
          />
          <Results data={result} filename="guias_set.zip" />
        </div>
      )}

      <Card className="border-primary/30">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">B · Simulación (Etapa 2) — datos reales</CardTitle>
          <CardDescription>
            Mismos tipos de traslado que el set, pero sin el <code className="rounded bg-muted px-1">.txt</code>: viene precargado con el
            producto y el receptor de prueba (C&amp;C SPA), igual que la Etapa 2 del set básico, y puedes reemplazarlos por la
            operación real de la empresa — el Manual de Certificación pide documentos "representativos, paralelos de la
            operación real". No llevan referencia SET/CASO. En el traslado interno el detalle va sin precio y en 0 (el SII
            repara con HED-2-210 si el encabezado va en 0 y el detalle valorizado).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Fieldset legend="Documentos a generar" hint="Se emite una guía por cada tipo de traslado marcado, con el mismo detalle.">
            <div className="space-y-1 sm:col-span-2">
              <Label>Tipos de traslado</Label>
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                {TRASLADOS.map(([v, l]) => (
                  <label key={v} className="flex items-center gap-1.5 text-sm">
                    <input
                      type="checkbox"
                      className="h-4 w-4 rounded border-input"
                      checked={sim.traslados.includes(v)}
                      onChange={(e) =>
                        setSim((s) => ({ ...s, traslados: e.target.checked ? [...s.traslados, v] : s.traslados.filter((x) => x !== v) }))
                      }
                    />
                    {l}
                  </label>
                ))}
              </div>
            </div>
            <div className="space-y-1">
              <Label htmlFor="sim-desp">Tipo de despacho (solo ventas)</Label>
              <select id="sim-desp" value={sim.tipoDespacho} onChange={setS("tipoDespacho")} className={SELECT_CLASS}>
                {DESPACHOS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="sim-folio">Folio inicial T52<span className="text-destructive"> *</span></Label>
              <Input id="sim-folio" type="number" min={caf.rango?.desde ?? 1} max={caf.rango?.hasta} placeholder={caf.rango ? `${caf.rango.desde}–${caf.rango.hasta}` : "primer folio del CAF"} value={sim.folio} onChange={setS("folio")} required aria-required aria-invalid={sim.folio.trim() !== "" && !simFolioOk} />
              <p className="text-[11px] text-muted-foreground">Debe ser distinto de los folios usados en el set (A).</p>
            </div>
          </Fieldset>
          <Fieldset legend="Detalle (productos reales)">
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="sim-prod">Producto<span className="text-destructive"> *</span></Label>
              <Input id="sim-prod" value={sim.producto} onChange={setS("producto")} placeholder="ej. Torta de mil hojas 20 porciones" required aria-required />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label htmlFor="sim-cant">Cantidad</Label>
                <Input id="sim-cant" type="number" min={1} value={sim.cantidad} onChange={setS("cantidad")} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="sim-prec">Precio<span className="text-destructive"> *</span></Label>
                <Input id="sim-prec" type="number" min={0} value={sim.precio} onChange={setS("precio")} required aria-required />
              </div>
            </div>
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="sim-prod2">Segundo producto (opcional)</Label>
              <Input id="sim-prod2" value={sim.producto2} onChange={setS("producto2")} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label htmlFor="sim-cant2">Cantidad</Label>
                <Input id="sim-cant2" type="number" min={1} value={sim.cantidad2} onChange={setS("cantidad2")} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="sim-prec2">Precio</Label>
                <Input id="sim-prec2" type="number" min={0} value={sim.precio2} onChange={setS("precio2")} />
              </div>
            </div>
          </Fieldset>
          <Fieldset legend="Cliente real" hint={simEsVenta
            ? "Guías de venta: el Manual de Muestras exige giro, dirección y comuna impresos. En el traslado interno se ignora (el receptor es la propia empresa)."
            : "En el traslado interno se ignora: el receptor es la propia empresa."}>
            <div className="space-y-1">
              <Label htmlFor="sim-rut">RUT<span className="text-destructive"> *</span></Label>
              <Input id="sim-rut" value={sim.receptorRut} onChange={setS("receptorRut")} placeholder="76746877-6" required aria-required />
            </div>
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="sim-razon">Razón social<span className="text-destructive"> *</span></Label>
              <Input id="sim-razon" value={sim.receptorRazon} onChange={setS("receptorRazon")} required aria-required />
            </div>
            <div className="space-y-1">
              <Label htmlFor="sim-giro">Giro{simEsVenta && <span className="text-destructive"> *</span>}</Label>
              <Input id="sim-giro" value={sim.receptorGiro} onChange={setS("receptorGiro")} required={simEsVenta} aria-required={simEsVenta} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="sim-dir">Dirección{simEsVenta && <span className="text-destructive"> *</span>}</Label>
              <Input id="sim-dir" value={sim.receptorDir} onChange={setS("receptorDir")} required={simEsVenta} aria-required={simEsVenta} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="sim-cmna">Comuna{simEsVenta && <span className="text-destructive"> *</span>}</Label>
              <Input id="sim-cmna" value={sim.receptorCmna} onChange={setS("receptorCmna")} required={simEsVenta} aria-required={simEsVenta} />
            </div>
          </Fieldset>
          <Button size="lg" disabled={!simListo || loadingSim} onClick={generarSim}>
            {loadingSim ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Generando simulación…</> : `Generar ${sim.traslados.length || ""} guía(s) de simulación`}
          </Button>
          {errorSim && (
            <Alert variant="destructive" role="alert">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{errorSim}</AlertDescription>
            </Alert>
          )}
          {resultSim && (
            <div className="space-y-4">
              <div className="flex items-center gap-3 rounded-lg border border-success/40 bg-success/5 px-4 py-3">
                <CheckCircle2 className="h-5 w-5 text-success" />
                <div className="flex-1 text-sm"><strong>Simulación generada y válida según XSD.</strong> Descarga y guarda el ZIP.</div>
                <Button size="sm" variant="outline" onClick={() => downloadB64(resultSim.zip_base64 ?? "", "guias_simulacion.zip")}>
                  <Download className="mr-1 h-4 w-4" /> Descargar ZIP
                </Button>
              </div>
              {resultSim.casos && (
                <div className="overflow-x-auto rounded-lg border">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/60 text-left"><tr><th className="p-2">Folio</th><th className="p-2">Motivo</th><th className="p-2">IndTraslado</th><th className="p-2">TipoDespacho</th><th className="p-2">Cedible</th></tr></thead>
                    <tbody>
                      {resultSim.casos.map((c) => (
                        <tr key={c.numero} className="border-t">
                          <td className="p-2 font-mono">{c.folio}</td><td className="p-2">{c.motivo}</td><td className="p-2">{c.ind_traslado}</td>
                          <td className="p-2">{c.tipo_despacho ?? "—"}</td><td className="p-2">{c.cedible ? "sí" : "no"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <PortalGuide
                title="Subir la simulación al portal SII"
                url="https://maullin.sii.cl/cgi_dte/UPL/DTEUpload"
                steps={[
                  { text: "Certificación DTE → Envío de Documentos → subir el EnvioDTE de simulación", highlight: true },
                  { text: "Esperar EPR + AOK sin reparos y declarar el avance de la Simulación" },
                  { text: "Las muestras impresas incluyen documentos de la simulación: usa los PDF de este mismo ZIP", highlight: true },
                ]}
              />
              <Results data={resultSim} filename="guias_simulacion.zip" />
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Muestras impresas desde un EnvioDTE de guías ya enviado</CardTitle>
          <CardDescription>Sube el <code className="rounded bg-muted px-1">EnvioDTE_GUIAS_*.xml</code> que aprobó el SII y genera los PDFs.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="max-w-sm">
            <UploadBox label="EnvioDTE de guías" hint="XML firmado subido al SII" icon="📄" accept=".xml" file={xmlMuestras} onChange={setXmlMuestras} />
          </div>
          <Button variant="outline" disabled={!xmlMuestras || loadingM} onClick={generarMuestras}>
            {loadingM ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Generando PDFs…</> : "Generar PDFs de muestra"}
          </Button>
          {muestras && (
            <div className="space-y-3">
              <Button size="sm" variant="outline" onClick={() => downloadB64(muestras.zip_base64 ?? "", "guias_muestras.zip")}>
                <Download className="mr-1 h-4 w-4" /> Descargar {muestras.pdfs_generados} PDFs
              </Button>
              <Results data={muestras} filename="guias_muestras.zip" />
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ─── Módulos pendientes de set ───────────────────────────────────────────────

function Pendiente({ titulo, icon, detalle }: { titulo: string; icon: ReactNode; detalle: string }) {
  return (
    <div className="space-y-4">
      <h2 className="flex items-center gap-2 text-lg font-semibold">{icon} {titulo}</h2>
      <Alert>
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{detalle}</AlertDescription>
      </Alert>
      <PortalGuide
        title="Cómo obtener el set de pruebas"
        url="https://maullin.sii.cl/cvc/dte/menu_postulantes.html"
        steps={[
          { text: "Menú Postulantes → Postulación: marcar el tipo de documento", highlight: true },
          { text: "Solicitar el CAF correspondiente en el ambiente de certificación" },
          { text: "Set de Pruebas → descargar el .txt (cada descarga genera un N° de atención nuevo)" },
          { text: "Entregar el .txt a PUDU para habilitar este módulo" },
        ]}
      />
    </div>
  );
}

// ─── Página ──────────────────────────────────────────────────────────────────

const MODULOS = [
  { key: "exportacion", label: "Exportación (110/111/112)", Icon: Globe, estado: "disponible" },
  { key: "guia", label: "Guía de Despacho (52)", Icon: Truck, estado: "disponible" },
  { key: "exenta", label: "Factura Exenta (34)", Icon: FileText, estado: "requiere set" },
] as const;
type ModKey = (typeof MODULOS)[number]["key"];

function Adicionales() {
  const [shared, setShared] = useState<Shared | null>(null);
  const [mod, setMod] = useState<ModKey>("exportacion");

  return (
    <div className="min-h-screen bg-muted/30">
      <header className="border-b bg-white px-6 py-4">
        <div className="mx-auto flex max-w-6xl items-center gap-4">
          <div>
            <h1 className="text-lg font-bold text-foreground">Certificaciones adicionales</h1>
            <p className="text-xs text-muted-foreground">Sets del SII distintos del básico — Certificador DTE</p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <VersionBadge />
            <Badge variant="outline">Ambiente Certificación</Badge>
          </div>
        </div>
      </header>

      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-8 md:flex-row">
        <aside className="w-full shrink-0 md:w-60">
          <div className="sticky top-8 space-y-4">
            <Link to="/" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
              <ArrowLeft className="h-4 w-4" /> Volver al set básico
            </Link>
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Módulos</p>
            <nav className="flex flex-col gap-1" aria-label="Módulos de certificación">
              {MODULOS.map((m) => (
                <button
                  key={m.key}
                  onClick={() => setMod(m.key)}
                  aria-current={mod === m.key ? "page" : undefined}
                  className={`flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${mod === m.key ? "bg-primary/10 font-semibold text-primary" : "hover:bg-muted"}`}
                >
                  <m.Icon className="h-4 w-4 shrink-0" />
                  <span className="flex-1">{m.label}</span>
                  {m.estado === "requiere set" && <Lock className="h-3.5 w-3.5 text-muted-foreground" aria-label="Requiere set de pruebas del SII" />}
                </button>
              ))}
              <Link
                to="/"
                className="flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-muted-foreground transition-colors hover:bg-muted"
              >
                <ShoppingCart className="h-4 w-4 shrink-0" />
                <span className="flex-1">Factura de Compra (46)</span>
                <Badge variant="outline" className="text-[10px]">en wizard</Badge>
              </Link>
            </nav>
            <p className="text-xs text-muted-foreground">
              La Factura de Compra ya está en el wizard principal: CAF T46 en Etapa 1 y modo "Factura de Compra" en Etapa 2.
            </p>
          </div>
        </aside>

        <main className="min-w-0 flex-1 space-y-6">
          {!shared && <Setup onDone={setShared} />}
          {shared && mod === "exportacion" && <Exportacion shared={shared} />}
          {shared && mod === "guia" && <Guias shared={shared} />}
          {shared && mod === "exenta" && (
            <Pendiente
              icon={<FileText className="h-5 w-5 text-primary" />}
              titulo="Factura No Afecta o Exenta (34)"
              detalle="El SII entrega un SET FACTURA EXENTA junto al básico cuando se postula al tipo 34. El generador ya soporta el documento; falta el parser de ese set."
            />
          )}
        </main>
      </div>
    </div>
  );
}

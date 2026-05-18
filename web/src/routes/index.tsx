import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Loader2, AlertCircle } from "lucide-react";
import { UploadBox } from "@/components/sii/UploadBox";
import { Results, type BatchResult, type CheckResult } from "@/components/sii/Results";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "SII Certificador DTE" },
      {
        name: "description",
        content:
          "Generación y validación de muestras impresas DTE para certificación SII Chile.",
      },
    ],
  }),
  component: Index,
});

type Status =
  | { kind: "idle" }
  | { kind: "loading"; msg: string }
  | { kind: "error"; msg: string }
  | { kind: "ok-batch"; data: BatchResult; filename: string }
  | {
      kind: "ok-validate";
      archivo: string;
      aprobado: boolean;
      puntaje: string;
      checks: CheckResult[];
    };

function StatusView({ status }: { status: Status }) {
  if (status.kind === "loading") {
    return (
      <Card className="mt-4">
        <CardContent className="flex flex-col items-center gap-3 py-10 text-muted-foreground">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <span className="text-sm">{status.msg}</span>
        </CardContent>
      </Card>
    );
  }
  if (status.kind === "error") {
    return (
      <Alert variant="destructive" className="mt-4">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{status.msg}</AlertDescription>
      </Alert>
    );
  }
  if (status.kind === "ok-batch") {
    return (
      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Resultados</CardTitle>
        </CardHeader>
        <CardContent>
          <Results data={status.data} filename={status.filename} />
        </CardContent>
      </Card>
    );
  }
  if (status.kind === "ok-validate") {
    return (
      <Card className="mt-4">
        <CardHeader>
          <CardTitle>{status.archivo}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid max-w-xs grid-cols-2 gap-3">
            <div className="rounded-lg bg-muted/40 p-4 text-center">
              <div
                className={`text-3xl font-bold ${
                  status.aprobado ? "text-success" : "text-primary"
                }`}
              >
                {status.aprobado ? "✓" : "✗"}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {status.aprobado ? "Aprobado" : "Rechazado"}
              </div>
            </div>
            <div className="rounded-lg bg-muted/40 p-4 text-center">
              <div className="text-3xl font-bold text-info">{status.puntaje}</div>
              <div className="mt-1 text-xs text-muted-foreground">Checks OK</div>
            </div>
          </div>
          <div className="mt-4 space-y-1">
            {status.checks.map((c, i) => (
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
        </CardContent>
      </Card>
    );
  }
  return null;
}

async function postFormData(path: string, fd: FormData): Promise<unknown> {
  const res = await fetch(path, { method: "POST", body: fd });
  const ct = res.headers.get("content-type") ?? "";
  const data = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    const detail =
      typeof data === "object" && data && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : typeof data === "string"
          ? data
          : `Error HTTP ${res.status}`;
    throw new Error(detail);
  }
  return data;
}

function Index() {
  // Tab Certificar
  const [setF, setSetF] = useState<File | null>(null);
  const [datosF, setDatosF] = useState<File | null>(null);
  const [pfxF, setPfxF] = useState<File | null>(null);
  const [caf33, setCaf33] = useState<File | null>(null);
  const [caf61, setCaf61] = useState<File | null>(null);
  const [caf56, setCaf56] = useState<File | null>(null);
  const [caf52, setCaf52] = useState<File | null>(null);
  const [caf46, setCaf46] = useState<File | null>(null);
  const [certStatus, setCertStatus] = useState<Status>({ kind: "idle" });

  // Tab Procesar
  const [xmlF, setXmlF] = useState<File | null>(null);
  const [procStatus, setProcStatus] = useState<Status>({ kind: "idle" });

  // Tab Validar
  const [pdfF, setPdfF] = useState<File | null>(null);
  const [valStatus, setValStatus] = useState<Status>({ kind: "idle" });

  const certReady =
    !!setF &&
    !!datosF &&
    !!pfxF &&
    !!(caf33 || caf61 || caf56 || caf52 || caf46);

  async function certificar() {
    setCertStatus({ kind: "loading", msg: "Generando XMLs firmados y PDFs…" });
    try {
      const fd = new FormData();
      fd.append("set_pruebas", setF!);
      fd.append("datos", datosF!);
      fd.append("pfx", pfxF!);
      if (caf33) fd.append("caf_33", caf33);
      if (caf56) fd.append("caf_56", caf56);
      if (caf61) fd.append("caf_61", caf61);
      if (caf52) fd.append("caf_52", caf52);
      if (caf46) fd.append("caf_46", caf46);
      const data = (await postFormData("/api/sii/certificar", fd)) as BatchResult;
      setCertStatus({ kind: "ok-batch", data, filename: "certificacion.zip" });
    } catch (e) {
      setCertStatus({ kind: "error", msg: (e as Error).message });
    }
  }

  async function procesar() {
    setProcStatus({ kind: "loading", msg: "Procesando XML…" });
    try {
      const fd = new FormData();
      fd.append("file", xmlF!);
      const data = (await postFormData("/api/sii/procesar", fd)) as BatchResult;
      setProcStatus({ kind: "ok-batch", data, filename: "pdfs.zip" });
    } catch (e) {
      setProcStatus({ kind: "error", msg: (e as Error).message });
    }
  }

  async function validar() {
    setValStatus({ kind: "loading", msg: "Validando PDF…" });
    try {
      const fd = new FormData();
      fd.append("file", pdfF!);
      const data = (await postFormData("/api/sii/validar", fd)) as {
        archivo: string;
        aprobado: boolean;
        puntaje: string;
        checks: CheckResult[];
      };
      setValStatus({ kind: "ok-validate", ...data });
    } catch (e) {
      setValStatus({ kind: "error", msg: (e as Error).message });
    }
  }

  return (
    <main className="min-h-screen bg-muted/30">
      <header className="bg-header px-6 py-5 text-header-foreground sm:px-8">
        <div className="mx-auto flex max-w-5xl items-center gap-4">
          <div className="flex-1">
            <h1 className="text-xl font-semibold">SII Certificador DTE</h1>
            <p className="text-xs text-header-foreground/70">
              Generación y validación de muestras impresas para certificación electrónica
            </p>
          </div>
          <span className="rounded-full bg-primary px-3 py-1 text-xs font-bold text-primary-foreground">
            v1.0
          </span>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-4 py-8">
        <Tabs defaultValue="certificar">
          <TabsList className="mb-5">
            <TabsTrigger value="certificar">Certificar desde Set de Pruebas</TabsTrigger>
            <TabsTrigger value="procesar">Procesar XML existente</TabsTrigger>
            <TabsTrigger value="validar">Validar PDF</TabsTrigger>
          </TabsList>

          {/* ─── CERTIFICAR ─────────────────────────────── */}
          <TabsContent value="certificar">
            <Card>
              <CardHeader>
                <CardTitle>Subir archivos del Set de Pruebas SII</CardTitle>
                <CardDescription>
                  El SII entrega estos archivos al iniciar la certificación. Súbelos
                  y generamos todos los XMLs y PDFs necesarios.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-5">
                <div>
                  <div className="mb-2 text-xs font-bold uppercase tracking-wider text-muted-foreground">
                    Archivos obligatorios
                  </div>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <UploadBox
                      label="SIISetDePruebas*.txt"
                      hint="Casos de prueba del SII"
                      icon="📋"
                      accept=".txt"
                      file={setF}
                      onChange={setSetF}
                    />
                    <UploadBox
                      label="DATOS.txt"
                      hint="Línea 1: nombre rep. · 2: rut_rep · 3: razón social · 4: rut empresa · 5: clave PFX · 6: giro (opcional) · 7: acteco · 8: dirección · 9: comuna · 10: nro_resol · 11: fecha_resol"
                      icon="👤"
                      accept=".txt"
                      file={datosF}
                      onChange={setDatosF}
                    />
                    <UploadBox
                      label="Certificado .pfx / .p12"
                      hint="Firma digital del representante"
                      icon="🔑"
                      accept=".pfx,.p12"
                      file={pfxF}
                      onChange={setPfxF}
                    />
                  </div>
                </div>

                <div>
                  <div className="mb-2 text-xs font-bold uppercase tracking-wider text-muted-foreground">
                    CAFs (uno por tipo de documento a certificar)
                  </div>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <UploadBox
                      label="CAF Factura Electrónica"
                      hint="dte33d1a100.xml"
                      icon="🧾"
                      accept=".xml"
                      optionalTag="T33"
                      file={caf33}
                      onChange={setCaf33}
                    />
                    <UploadBox
                      label="CAF Nota de Crédito"
                      hint="dte61d1a100.xml"
                      icon="📉"
                      accept=".xml"
                      optionalTag="T61"
                      file={caf61}
                      onChange={setCaf61}
                    />
                    <UploadBox
                      label="CAF Nota de Débito"
                      hint="dte56d1a100.xml"
                      icon="📈"
                      accept=".xml"
                      optionalTag="T56"
                      file={caf56}
                      onChange={setCaf56}
                    />
                    <UploadBox
                      label="CAF Guía de Despacho"
                      hint="dte52d1a100.xml"
                      icon="🚚"
                      accept=".xml"
                      optionalTag="T52"
                      file={caf52}
                      onChange={setCaf52}
                    />
                    <UploadBox
                      label="CAF Factura de Compra"
                      hint="dte46d1a100.xml"
                      icon="🏭"
                      accept=".xml"
                      optionalTag="T46"
                      file={caf46}
                      onChange={setCaf46}
                    />
                  </div>
                </div>

                <Button
                  onClick={certificar}
                  disabled={!certReady || certStatus.kind === "loading"}
                  size="lg"
                >
                  Generar XMLs y PDFs
                </Button>
              </CardContent>
            </Card>
            <StatusView status={certStatus} />
          </TabsContent>

          {/* ─── PROCESAR XML ──────────────────────────── */}
          <TabsContent value="procesar">
            <Card>
              <CardHeader>
                <CardTitle>Procesar EnvioDTE XML existente</CardTitle>
                <CardDescription>
                  Si ya tienes un XML EnvioDTE firmado, súbelo para generar los PDFs y validarlos.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="max-w-sm">
                  <UploadBox
                    label="EnvioDTE_*.xml"
                    hint="Arrastra o haz clic para seleccionar"
                    icon="📄"
                    accept=".xml"
                    file={xmlF}
                    onChange={setXmlF}
                  />
                </div>
                <Button
                  onClick={procesar}
                  disabled={!xmlF || procStatus.kind === "loading"}
                  size="lg"
                >
                  Generar y Validar PDFs
                </Button>
              </CardContent>
            </Card>
            <StatusView status={procStatus} />
          </TabsContent>

          {/* ─── VALIDAR PDF ───────────────────────────── */}
          <TabsContent value="validar">
            <Card>
              <CardHeader>
                <CardTitle>Validar PDF de muestra impresa</CardTitle>
                <CardDescription>
                  Valida un PDF individual contra los requisitos del Manual de Muestras Impresas del SII.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="max-w-sm">
                  <UploadBox
                    label="*.pdf"
                    hint="Muestra impresa DTE — máx. 500 KB"
                    icon="🖨️"
                    accept=".pdf"
                    file={pdfF}
                    onChange={setPdfF}
                  />
                </div>
                <Button
                  onClick={validar}
                  disabled={!pdfF || valStatus.kind === "loading"}
                  size="lg"
                >
                  Validar PDF
                </Button>
              </CardContent>
            </Card>
            <StatusView status={valStatus} />
          </TabsContent>
        </Tabs>
      </div>
    </main>
  );
}

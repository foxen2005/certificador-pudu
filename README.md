# Certificador Pudu

Sistema de certificación DTE (Documento Tributario Electrónico) para el SII de Chile.
Genera DTEs firmados (Facturas T33, NC T61, ND T56, etc.), Libros Tributarios (Ventas/Compras),
y PDFs validados según el Manual SII 4.0.

**Empresa certificada actual:** PUDU TECNOLOGIA SPA (RUT 78392059-K)

---

## Estructura del proyecto

> Nota: el drive cambió de F: a D: tras el reformateo (jun-2026). Usar siempre `d:\PUDU\`.
> El frontend fue reescrito — ya NO vive en `web\` (esa carpeta quedó huérfana, solo con
> lockfiles de bun). El wizard actual vive en `src\` en la raíz del proyecto (TanStack Start).

```
d:\PUDU\Certificador Pudu\
├── README.md               ← este archivo
├── MEMORIES.md             ← referencia a memorias globales (lecciones SII)
├── backend\                ← código Python (generación + firma) — deploy: GCP Cloud Run
│   ├── builders\           ← módulos reutilizables (sign_via_pudu, c14n, etc.)
│   │   ├── common.py       ← helpers compartidos
│   │   ├── envio_dte.py    ← construcción y firma EnvioDTE
│   │   ├── pudu_sign.cjs   ← bridge Node.js → SII_pudu_Server/signer.js
│   │   └── __init__.py
│   ├── libro_builder.py    ← LibroVentas y LibroCompras
│   ├── dte_builder.py      ← (alias del builders/envio_dte.py - legacy)
│   ├── set_parser.py       ← parser del SIISetDePruebas*.txt
│   ├── parser.py           ← parser de EnvioDTE generado
│   ├── generator.py        ← generación de PDFs A4 con PDF417
│   ├── validator.py        ← validación de PDFs (12 checks)
│   ├── test_certificacion.py  ← script principal (genera y firma todo)
│   ├── firmar_libro_ventas.py ← script enfocado solo en libro de ventas
│   ├── main.py             ← API FastAPI (endpoints: /certificar, /procesar, /validar, /etapa2, /etapa3, /etapa4)
│   ├── Dockerfile          ← Python 3.12-slim, OPENSSL_CONF=openssl_legacy.cnf (certs SII con RC2-40/3DES+SHA1)
│   ├── docs\               ← documentación interna
│   └── legacy\             ← versiones viejas de builders (referencia)
├── verify\                 ← scripts Node.js de verificación y firma
│   ├── firmar_envio.js     ← firma EnvioDTE con xml-crypto
│   ├── firmar_libro.js     ← firma LibroCV con xml-crypto
│   ├── verify_dte.js       ← verifica firmas con xml-crypto
│   ├── compare_firma.js    ← compara firma Python vs pudu server
│   └── node_modules\
├── src\                    ← frontend actual: wizard TanStack Start + React 19 + shadcn/Radix
│   ├── routes\
│   │   ├── index.tsx       ← CertWizard — UI paso a paso (setup/etapa1-4)
│   │   └── api\sii.$.ts    ← proxy /api/sii/* → backend Cloud Run (auth OIDC service account o bearer estático)
│   ├── components\, hooks\, integrations\supabase\, lib\
├── web\                    ← OBSOLETO — solo quedan lockfiles de bun, no usar
├── frontend\               ← OBSOLETO — solo un index.html stub
├── wrangler.jsonc          ← deploy del wizard a Cloudflare Workers (name: certificador-pudu)
├── Documentacion\          ← manuales SII de referencia (formatos DTE, boleta, AEC, esquemas XML)
├── sets\                   ← sets de prueba SII
│   ├── pudu_78392059K\     ← set actual de PUDU TECNOLOGIA SPA
│   │   ├── SIISetDePruebas78392059K.txt   ← set de pruebas
│   │   ├── DATOS.txt                       ← datos del emisor
│   │   ├── 15996452-3_2025-11-14.p12      ← certificado digital
│   │   ├── 33_1-100.xml                    ← CAF Factura Electrónica
│   │   ├── 56_1-100.xml                    ← CAF Nota de Débito
│   │   └── 61_1-100.xml                    ← CAF Nota de Crédito
│   └── referencia_77314475\  ← set viejo certificado (referencia LibreDTE)
│       ├── etapa 1\ ← Set Básico (XMLs aprobados)
│       ├── etapa 2\ ← Libro de Ventas aprobado
│       ├── etapa 3\ ← Libro de Compras aprobado
│       └── etapa 4\ ← intercambio
├── output\                 ← carpetas certificacion_YYYYMMDD_HHMM\
│                             y libroventas_YYYYMMDD_HHMM\
├── legacy\                 ← scripts y outputs viejos (no usar)
│   ├── output_old\         ← PDFs sueltos viejos
│   ├── certificar.py       ← script viejo Cloud Run
│   ├── INSTRUCCIONES.txt   ← instrucciones del flujo viejo
│   └── ...
└── cloudbuild.yaml         ← config GCP (deploy del API FastAPI a Cloud Run, servicio `certificador-sii`)
```

## Despliegue (arquitectura actual)

Dos despliegues separados, conectados por un proxy:

1. **Backend Python (FastAPI)** → GCP Cloud Run, servicio `certificador-sii` (`cloudbuild.yaml` + `backend/Dockerfile`). Push a `main` dispara Cloud Build.
2. **Frontend wizard (TanStack Start)** → Cloudflare Workers (`wrangler.jsonc`, name `certificador-pudu`). Todas las llamadas a `/api/sii/*` pasan por `src/routes/api/sii.$.ts`, que firma un JWT y pide un ID token OIDC a Google (usando el service account en el secret `GCP_SA_KEY_JSON`) para autenticar contra Cloud Run — o usa `SII_BACKEND_TOKEN` como fallback estático.

```bash
# Frontend local
npm run dev        # vite dev — sirve el wizard
npm run build       # build para Cloudflare Workers
npx wrangler deploy # deploy manual si no hay CI configurado
```

---

## Estado de la certificación PUDU (78392059-K)

- ✅ **Etapa 1** — Set Básico: 8 DTEs aprobados (con 1 reparo menor en NC F1)
- ✅ **Etapa 2** — Libro de Ventas: LOK + LTC
- ✅ **Etapa 3** — Libro de Compras: LOK + LTC

**Próximo paso**: Esperar resolución administrativa del SII para emitir DTEs en producción.

### Folios ya enviados al SII

⚠️ **NO REUTILIZAR**, causaría DTE-3-100 (DTE Repetido):

| Tipo | Folios usados |
|---|---|
| T33 (Factura) | 1-24 |
| T56 (Nota Débito) | 1-6 |
| T61 (Nota Crédito) | 1-18 |

Actualizar `FOLIOS_YA_ENVIADOS` en `test_certificacion.py` y `firmar_libro_ventas.py`
tras cada envío exitoso.

---

## Cómo usar (flujo principal)

### Generar set completo (Etapas 1+2+3)

```bash
cd "f:\PUDU\Certificador Pudu\backend"
python test_certificacion.py
```

Genera carpeta `output/certificacion_YYYYMMDD_HHMM/` con:
- `EnvioDTE_78392059K.xml` ← Etapa 1
- `LibroVentas_78392059K.xml` ← Etapa 2 (nro atención 4809212)
- `LibroCompras_78392059K.xml` ← Etapa 3 (nro atención 4809213)
- PDFs con cedibles

Luego subir cada archivo al portal SII.

### Generar solo libro de ventas

```bash
cd "f:\PUDU\Certificador Pudu\backend"
python firmar_libro_ventas.py
```

Genera carpeta `output/libroventas_YYYYMMDD_HHMM/LibroVentas_78392059K.xml`.

### Verificar firmas

```bash
cd "f:\PUDU\Certificador Pudu\verify"
node verify_dte.js                   # verifica último EnvioDTE
node compare_firma.js                # compara firma Python vs pudu server
```

---

## Arquitectura de firma (CRÍTICO)

**TODO se firma vía `sign_via_pudu()`** (`backend/builders/common.py`), que internamente:
1. Llama a `pudu_sign.cjs` (Node.js)
2. Que usa `signer.js` del `f:\PUDU\SII_pudu_Server\src\signer.js` (xml-crypto)

**NO firmar XMLDsig con lxml/Python directo** — tiene bugs de C14N que el SII rechaza.

### Por qué no Python lxml directo

lxml tiene 2 bugs en C14N de subtree:
1. Agrega `xmlns=""` a elementos de profundidad ≥2 aunque estén en el mismo namespace
2. Propaga `xmlns:xsi` heredado al C14N aunque no se use en el subtree

El SII usa Java spec-compliant que NO hace eso → digest distinto → rechazo (RFR/DTE-3-505/LRF).

### Patrón productivo (igual que SII_pudu_Server/server.js:757)

1. Cada DTE se firma **standalone** (envuelto en su propio `<DTE xmlns="...">` sin EnvioDTE alrededor)
2. Los DTEs ya firmados se embeben en EnvioDTE **vía string concatenation** (no re-parsear con lxml)
3. Se firma el `<SetDTE>` outer en el contexto completo del EnvioDTE

---

## Particularidades del set PUDU

### NC con CodRef=2 (Corrige Texto)

Las NC tipo "CORRIGE GIRO DEL RECEPTOR" deben tener `MntTotal=0` por regla SII REF-2-781.
Fix en `test_certificacion.py`: si `_cod_ref(razon)=="2"` → forzar `precio_unitario=0`.

### Libros con periodo pre-RCV (2000-01)

Los libros tradicionales fueron reemplazados por RCV desde 2017-08. Para certificación
ESPECIAL usar:
- `PeriodoTributario = "2000-01"`
- `FchDoc = "2000-01-01"` (en cada Detalle)
- `FchResol/NroResol = los del EnvioDTE` (NO los defaults de LibreDTE)

### T46 (Factura de Compra) con retención total del IVA

Debe emitir tanto `MntIVA` como `IVARetTotal` (mismo valor), y `MntTotal = MntNeto + MntIVA + MntExe`.
El resumen `<ResumenPeriodo>` correspondiente debe incluir `<TotIVARetTotal>`.

---

## Para futuros Claudes / desarrolladores

**ANTES de tocar `backend/builders/`, `libro_builder.py` o firma XMLDsig**, leer:

1. **`MEMORIES.md`** (este folder) — apunta a las memorias globales en
   `C:\Users\DigitalFox\.claude\projects\f--SandBox\memory\`
2. **`sii_certificador_lessons.md`** (memoria global) — catálogo de errores SII
   y soluciones probadas
3. **`backend/REGISTRO_ENVIOS.md`** — historial de envíos al SII y sus resultados

**REGLA DE ORO:** firmar SIEMPRE con `sign_via_pudu`. NUNCA volver a firmar
con lxml/cryptography directo aunque parezca que "ya funciona localmente".
Lo que importa es que el SII (Java) acepte la firma.

---

## Dependencias externas

- **`f:\PUDU\SII_pudu_Server\`** — servidor con `signer.js` (xml-crypto). NO mover. NO modificar.
- Node.js 24.x con `xml-crypto`, `@xmldom/xmldom`, `node-forge`
- Python 3.13 con `lxml`, `cryptography`, `reportlab`, `pdf417gen`, `PyMuPDF`

## Sitios del SII

- **Certificación**: `https://maullin.sii.cl/cgi_dte/UPL/DTEUpload`
- **Producción**: `https://palena.sii.cl/cgi_dte/UPL/DTEUpload`
- **Portal certificación**: `https://www4.sii.cl/...` (login con certificado)

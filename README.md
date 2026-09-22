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
│   ├── exportacion.py      ← módulo Exportación 110/111/112 (<Exportaciones>, Aduana, OtraMoneda)
│   ├── generator_exportacion.py ← PDF de exportación
│   ├── xsd_validator.py    ← validación contra XSD oficial (schemas/)
│   ├── routers/exportacion_api.py ← /adicionales/*
│   ├── schemas/            ← DTE_v10, EnvioDTE_v10, SiiTypes_v10, xmldsignature_v10 (copia de Documentacion SII)
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

**COMPLETADA el 2026-05-18** — las 4 etapas aprobadas. Detalle, IDs de envío y folios en
[`backend/docs/RESUMEN_CERTIFICACION_78392059K.md`](backend/docs/RESUMEN_CERTIFICACION_78392059K.md).

- ✅ **Etapa 1** — Set Básico (EnvioDTE 8/8 AOK) + Libro de Ventas (LOK/LTC) + Libro de Compras (LTC)
- ✅ **Etapa 2** — Simulación (3/3 AOK)
- ✅ **Etapa 3** — Intercambio (3 XML OK)
- ✅ **Etapa 4** — Muestras impresas (16/16)

### Folios ya enviados al SII (PUDU)

⚠️ **NO REUTILIZAR**, causaría DTE-3-100 (DTE Repetido):

| Tipo | Folios consumidos | Próximo libre |
|---|---|---|
| T33 (Factura) | 1-37 | 38 |
| T56 (Nota Débito) | 1-10 | 11 |
| T61 (Nota Crédito) | 1-28 | 29 |

El wizard **no** persiste folios: por defecto arranca en el primer folio del CAF. Al
certificar cualquier RUT, indicar el folio inicial en la interfaz (Etapa 1 y Etapa 2)
después de cada envío al SII, incluso si fue rechazado. Para PUDU, actualizar también
`FOLIOS_YA_ENVIADOS` en `test_certificacion.py` / `firmar_libro_ventas.py`.

### Certificaciones adicionales (`/adicionales`)

Módulos aparte del set básico, uno por tipo de documento con set propio del SII:
- **Exportación 110/111/112** — funcional: genera T110→T112→T111 con `<Exportaciones>`, Aduana,
  `TpoMoneda`/`OtraMoneda`, valida contra el XSD oficial (`backend/schemas/`) y genera PDFs.
  Backend en `backend/exportacion.py` + `routers/exportacion_api.py`; lección 25.
- **Guía de Despacho 52** — funcional: parsea el SET GUIA DE DESPACHO (motivo → IndTraslado, traslado por →
  TipoDespacho), receptor = emisor en traslado interno, cedible solo en ventas. `backend/guias.py`; lección 26.
- **Factura Exenta 34** — visible, requiere el set de pruebas del SII.
- **Factura de Compra 46** — ya está en el wizard principal (Etapa 1 CAF + Etapa 2 modo compra).

### Certificar otra empresa

1. Preparar el `DATOS.txt` con las **11 líneas** (formato en `backend/docs/GUIA_PRUEBAS.md`;
   la web muestra el formato y valida el archivo). Las líneas 10-11 (N° y fecha de resolución)
   son las que el SII contrasta en la carátula → `CRT-3-19` si no coinciden con lo publicado
   en maullin.sii.cl. N° = `0` en certificación.
2. Subir certificado + DATOS.txt + CAFs en "Configuración" del wizard e ingresar la clave.
3. Seguir las etapas. Ver `backend/docs/LECCIONES_TECNICAS.md` antes de tocar el generador.

---

## Cómo usar (flujo principal)

### Generar set completo (Etapas 1+2+3)

```bash
cd "d:\PUDU\Certificador Pudu\backend"
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
cd "d:\PUDU\Certificador Pudu\backend"
python firmar_libro_ventas.py
```

Genera carpeta `output/libroventas_YYYYMMDD_HHMM/LibroVentas_78392059K.xml`.

### Verificar firmas

```bash
cd "d:\PUDU\Certificador Pudu\verify"
node verify_dte.js                   # verifica último EnvioDTE
node compare_firma.js                # compara firma Python vs pudu server
```

> `verify/` son herramientas locales de desarrollo: dependen de `d:\PUDU\SII_pudu_Server`.
> El runtime del backend (Cloud Run) NO las usa — todo lo que firma vive en `backend/builders/`
> (`pudu_sign.cjs`, `firmar_respuesta_dte.cjs`, `firmar_envio_recibos.cjs` + `vendor/signer.js`).

---

## Arquitectura de firma (CRÍTICO)

**TODO se firma vía `sign_via_pudu()`** (`backend/builders/common.py`), que internamente:
1. Llama a `pudu_sign.cjs` (Node.js)
2. Que usa `backend/builders/vendor/signer.js` — copia vendorizada del `signer.js` de
   `SII_pudu_Server` (xml-crypto). Si el server corrige un bug de firma, replicarlo ahí a mano.

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

## Lecciones técnicas y estado de certificación (trackeado en git)

`sets/` está en `.gitignore` (contiene certificados/CAFs privados), así que documentos de referencia que vivían ahí NO viajaban con el repo. Se movieron copias a `backend/docs/` (sí trackeado):

- `backend/docs/LECCIONES_TECNICAS.md` — catálogo completo de errores SII encontrados y sus fixes (firma XMLDsig, folios, encoding, timbre, etc.) — **leer antes de tocar firma, folios o el generador de PDFs**.
- `backend/docs/RESUMEN_CERTIFICACION_78392059K.md` — estado y folios realmente consumidos por la certificación de PUDU TECNOLOGIA SPA. Fuente de verdad para `FOLIO_START`/`FOLIOS_YA_ENVIADOS` — compararlos contra este archivo antes de generar documentos para subir de verdad al SII.

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

1. **`backend/docs/LECCIONES_TECNICAS.md`** — catálogo de errores SII y soluciones
   probadas (22 lecciones; es la fuente de verdad, las memorias globales viejas se perdieron)
2. **`backend/docs/RESUMEN_CERTIFICACION_78392059K.md`** — estado y folios de PUDU
3. **`backend/REGISTRO_ENVIOS.md`** — historial de envíos al SII y sus resultados
4. **`MEMORIES.md`** (este folder) — tablas rápidas de estados/errores SII

**Una sola implementación por XML**: el wizard (`main.py`) y los scripts
(`test_certificacion.py`, `firmar_libro_*.py`) deben llamar a las mismas funciones de
`builders/` y `libro_builder.py`. Tener dos copias fue lo que produjo el LRH de la lección 20.

**REGLA DE ORO:** firmar SIEMPRE con `sign_via_pudu`. NUNCA volver a firmar
con lxml/cryptography directo aunque parezca que "ya funciona localmente".
Lo que importa es que el SII (Java) acepte la firma.

---

## Dependencias externas

- **`d:\PUDU\SII_pudu_Server\`** — origen del `signer.js` vendorizado; solo lo usan los
  scripts de `verify/`. NO modificar desde aquí.
- Node.js 20+ con `xml-crypto@2`, `@xmldom/xmldom@0.8`, `node-forge` (`backend/package.json`)
- Python 3.12 con `lxml`, `cryptography`, `reportlab`, `pdf417gen`, `PyMuPDF` (`backend/requirements.txt`)

## Sitios del SII

- **Certificación**: `https://maullin.sii.cl/cgi_dte/UPL/DTEUpload`
- **Producción**: `https://palena.sii.cl/cgi_dte/UPL/DTEUpload`
- **Portal certificación**: `https://www4.sii.cl/...` (login con certificado)

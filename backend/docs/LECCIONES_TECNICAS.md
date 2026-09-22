# Lecciones Técnicas — Certificación SII 78392059-K

Todo lo que salió mal y cómo se resolvió. Base para el certificador automático.

---

## 1. Firma XMLDsig — RFR (firma rechazada)

**Error**: EnvioDTE rechazado con RFR — firma outer SetDTE inválida.

**Causa**: `c14n_for_sii` removía `xmlns:xsi` del XML antes de firmar. El SII Java SÍ incluye `xmlns:xsi` en su C14N del SetDTE outer.

**Fix**: En C14N, solo remover `xmlns=""` (namespace vacío). Dejar `xmlns:xsi` intacto.

---

## 2. Firma XMLDsig inner — DTE-3-505

**Error**: Outer OK pero los 8 DTEs internos rechazados con DTE-3-505 (firma inner inválida).

**Causa**: Al firmar los DTEs dentro del EnvioDTE con lxml, el namespace `xmlns:xsi` del EnvioDTE padre se propaga al subtree. El digest computado incluye `xmlns:xsi`, pero el SII no lo espera en el inner DTE.

**Fix (crítico)**: Flujo standalone + string concat:
1. Firmar cada `<DTE xmlns="...sii.cl/SiiDte">` de forma INDEPENDIENTE (sin EnvioDTE alrededor)
2. Guardar los bytes firmados exactos
3. Construir el EnvioDTE con STRING CONCAT (no con lxml — re-serializar rompe los digests)
4. Firmar el outer SetDTE al final

Fuente: `SII_pudu_Server/server.js:757`

---

## 3. Folios repetidos — DTE-3-100/101

**Error**: Todos los DTEs rechazados con "DTE Repetido" o "Folio ya recibido".

**Causa**: Después de un EPR (aunque los DTEs fueran RCH/RPR), los folios quedan registrados en el SII. Reenviar los mismos folios siempre falla.

**Fix**: Después de CUALQUIER EPR, usar folios nuevos para el siguiente intento.

---

## 4. NC CodRef=2 con montos — REF-2-781

**Error**: T61 RPR con REF-2-781 "Modifica Texto no debe tener montos [2] <> [3]".

**Causa**: NC "CORRIGE GIRO DEL RECEPTOR" (CodRef=2) copiaba los items de la factura referenciada → MntTotal > 0.

**Fix**: NC con CodRef=2 debe tener:
- `MntTotal = 0`
- Un solo item placeholder (NmbItem con descripción, sin precio/cantidad)
- NO copiar items del DTE referenciado

---

## 5. NC devolución sin descuento heredado

**Error**: NC de devolución parcial (CodRef=3) RPR porque montos no cuadraban con la factura.

**Causa**: La factura tenía `DescuentoPct` en los items, pero la NC no lo heredaba.

**Fix**: Al generar NC CodRef=3, copiar el `DescuentoPct` y `DescuentoMonto` de cada item de la factura referenciada.

---

## 6. LibroVentas descuadrado — LBR-2/LBR-3

**Error**: LibroVentas rechazado con LBR-2 (montos negativos) y LBR-3 (descuadre T61).

**Causas**:
- T61 aparece como TpoDoc con TotMntTotal negativo en el resumen → LBR-2 no admite negativo en TpoDoc
- TotMntExe/Neto/IVA/Total del ResumenPeriodo descuadrado cuando se suman T61 con negativos

**Fix**: En el LibroCV **todos** los montos van en POSITIVO, también los de las NC (T61): el `TpoDoc=61` ya indica que restan. Los negativos solo se admiten en liquidaciones (TpoDoc 40/43/103). Evidencia: `output/certificacion_20260517_2009/LibroVentas_78392059K.xml` (LOK/LTC) tiene los `Detalle` T61 con `MntNeto`/`MntIVA`/`MntTotal` positivos y el resumen T61 cuadra con esa suma.

> ⚠️ Una versión anterior de esta lección decía lo contrario ("las NC deben ir NEGATIVAS") y `build_libro_ventas()` en `libro_builder.py` lo implementaba así → ver lección 20.

---

## 7. PDF417 barcode — encoding UTF-8 vs ISO-8859-1

**Error**: Portal SII mostraba "RS PUDU TECNOLOGÃA SPA" en el TED del barcode. Ted? ✗.

**Causa**: `pdf417gen.encode()` recibía un string Unicode → lo codificaba como UTF-8. El byte `Í` (U+00CD) en UTF-8 es 2 bytes (0xC3 0x8D). El SII lee el barcode como ISO-8859-1 → `0xC3` = "Ã", `0x8D` = carácter de control.

**Fix**: 
```python
pdf417gen.encode(ted_xml.encode('iso-8859-1', errors='replace'), ...)
```

---

## 8. TED con namespace xmlns en barcode

**Error**: Portal SII mostraba Caf? ✗, Ted? ✗ aunque el encoding era correcto.

**Causa**: El TED extraído con `etree.tostring()` incluía `xmlns="http://www.sii.cl/SiiDte"` y otros namespaces que no estaban en el TED original del SII.

**Fix**: Extraer el TED como string crudo del XML (ISO-8859-1), sin pasar por lxml:
```python
raw_str = xml_bytes.decode('iso-8859-1', errors='replace')
ted_blocks = re.findall(r'<TED\b[^>]*>.*?</TED>', raw_str, re.DOTALL)
```

---

## 9. FRMA/FRMT inválidos — Node.js whitespace

**Error**: Portal SII: "Ha habido alguna alteración en el CAF" + "TED - Firma inválida". Incluso después de fixes anteriores.

**Causa**: Node.js XMLSerializer (usado por `signInPlace` al re-firmar) expande elementos con múltiples hijos agregando saltos de línea:
- `<RNG><D>1</D><H>100</H></RNG>` → `<RNG>\n<D>1</D>\n<H>100</H>\n</RNG>`
- `<RSAPK><M>...</M><E>Aw==</E></RSAPK>` → `<RSAPK>\n<M>...</M>\n<E>Aw==</E>\n</RSAPK>`

El SII verifica FRMA y FRMT sobre DA/DD **compactos** (sin whitespace inter-tag). El whitespace extra cambia el C14N → verificación falla.

**Evidencia**: TED aprobado de otra empresa (PUMA SERVICIOS SPA) confirmó que el SII espera todo compacto.

**Fix** en `generator.py` antes del barcode:
```python
def _compact_ted(ted_xml: str) -> str:
    return re.sub(r'>\s+<', '><', ted_xml)
```

Solo afecta whitespace entre tags, no el contenido de texto.

---

## 10. Etapa 3 — contenido no coincide con SET

**Error**: Portal SII rechazaba los 3 XML de intercambio: "Los siguientes valores no coinciden" (folios y montos).

**Causa**: El portal SII registra solo el ÚLTIMO SET descargado. El usuario había descargado el SET dos veces, generando dos N° de Atención diferentes (4832678 y 4832681). Los XMLs se generaron con el primer SET (folios F52769/F52770), pero el SII validaba contra el segundo (F52727/F52728).

**Fix**: Siempre usar el archivo de SET más reciente. Verificar el N° en el nombre del archivo.

**Regla**: cada descarga del SET desde el portal genera un NUEVO N° de Atención y los datos cambian.

---

## 11. CAF files — encoding ISO-8859-1

**Error**: Caracteres del RS en el TED aparecían corruptos incluso antes de la codificación del barcode.

**Causa**: Los archivos CAF (.xml) contienen "PUDU TECNOLOGÍA SPA" en ISO-8859-1. Si se leen sin especificar encoding, Python usa UTF-8 por defecto y corrompe el byte 0xED (Í).

**Fix** en `dte_builder.py`:
```python
root = etree.fromstring(xml_bytes, etree.XMLParser(encoding="iso-8859-1"))
```

---

## 12. Cloud Run backend no podía firmar — Node.js ausente + dependencia de carpeta vecina

**Error**: `/certificar` devolvía 500 en producción: `[Errno 2] No such file or directory: 'node'`.

**Causa**: El `Dockerfile` del backend (`python:3.12-slim`) nunca instaló Node.js, pero `sign_via_pudu()` necesita ejecutar `node builders/pudu_sign.cjs` como subproceso. Peor: aunque se instalara Node, `pudu_sign.cjs` apuntaba a `SII_pudu_Server/src/signer.js` como carpeta vecina (`path.resolve(__dirname, '../../../SII_pudu_Server')`) — el build de Cloud Run (`cloudbuild.yaml`) usa como contexto solo `backend/`, así que esa carpeta ni existe dentro del contenedor.

**Fix**: Vendorizar (copiar, no referenciar) `signer.js` dentro de `backend/builders/vendor/signer.js`. Agregar `backend/package.json` con `xml-crypto`/`node-forge` (mismas versiones que `SII_pudu_Server`). Instalar Node.js 20 en el `Dockerfile` (`deb.nodesource.com/setup_20.x`) y correr `npm install` en el build. `pudu_sign.cjs` ahora hace `require('./vendor/signer.js')` en vez de la ruta vecina. Certificador Pudu queda sin ninguna dependencia de `SII_pudu_Server` en runtime — solo llamarlo (nunca modificarlo) sigue siendo aceptable, pero ni eso hace falta ya.

---

## 13. Proxy online 403 — service account key corrupta

**Error**: El wizard online (`/api/sii/*`) devolvía siempre el 403 de Google Frontend, como si la petición nunca llevara autenticación, aunque el secret `GCP_SA_KEY_JSON` existía en el hosting del frontend.

**Causa**: La private key guardada en el secret fallaba con `Invalid PKCS8 input` al intentar `crypto.subtle.importKey` — la key en sí estaba corrupta/mal codificada (nunca se determinó el byte exacto de corrupción, no valía la pena depurarlo).

**Fix**: Generar una key NUEVA para el mismo service account (`gcloud iam service-accounts keys create`, service account ya tenía `roles/run.invoker` correcto), base64 del JSON crudo, reemplazar el secret. Diagnóstico usado: endpoint de debug temporal en el proxy que reportaba `gcpSaKeyFound`, `saClientEmail`, y el error exacto de `getGCPIdentityToken()` (revertido después de confirmar el fix).

---

## 14. Folios: el código quedó desactualizado respecto a la certificación real

**Error**: Ninguno visible todavía — se detectó ANTES de subir nada al SII, comparando el código contra `RESUMEN_CERTIFICACION.md`.

**Causa**: `FOLIO_START` en `main.py` y `FOLIOS_YA_ENVIADOS` en `test_certificacion.py`/`firmar_libro_ventas.py` tenían 3 valores distintos entre sí, y los 3 estaban por debajo de los folios realmente consumidos y aceptados por el SII (`T33` hasta F37, `T56` hasta F10, `T61` hasta F28 según `RESUMEN_CERTIFICACION.md` del 2026-05-18). Generar un nuevo EnvioDTE con esos offsets viejos habría reusado folios ya enviados → `DTE-3-100`.

**Fix**: Actualizar los 3 archivos a los valores reales del resumen. **Regla permanente**: antes de generar cualquier documento para subir de verdad, comparar `FOLIO_START`/`FOLIOS_YA_ENVIADOS` contra `RESUMEN_CERTIFICACION.md` (si existe) — no asumir que el código está al día.

---

## 15. Timbre Electrónico a 1cm del margen (debía ser 2cm)

**Error**: Ninguno reportado por el SII todavía — encontrado en auditoría de cumplimiento contra el Manual de Muestras Impresas.

**Causa**: `generator.py` usaba `margin = 1.0 * cm` para `SimpleDocTemplate`. El manual exige que el Timbre Electrónico esté a mínimo 2cm del borde izquierdo. Como el timbre se agrega al `story` en el flujo normal del documento (sin coordenadas x/y propias), hereda el margen general — a 1cm quedaba fuera de norma.

**Fix**: `margin = 2.0 * cm`. Como `usable_w` y el resto de las tablas derivan de esa misma variable, todo el layout se realineó solo, sin tocar cada tabla individualmente.

---

## 16. Validador de PDFs no detectaba el problema anterior

**Error**: El check "Imagen barcode embebida" pasaba con `passed=True` incluso con el timbre a 1cm — solo contaba `len(images) >= 1`.

**Fix**: Usar `page.get_image_info()` (PyMuPDF) para medir posición real (bbox) y tamaño del timbre, no solo su existencia. Umbral usado: margen izquierdo ≥1.8cm (tolerancia sobre los 2cm exigidos) y dimensiones dentro de ~2x5cm a ~4x9cm.

---

## 17. `RznSocRecep`/`GiroRecep`/`DirRecep` sin truncar al límite del XSD

**Error**: Ninguno con el set de pruebas actual (los datos son cortos) — riesgo latente para cualquier RUT futuro con receptor de nombre/giro/dirección largos.

**Causa**: Solo `GiroEmis` se truncaba (`[:80]`) en `builders/envio_dte.py`/`dte_builder.py`; los 3 campos del receptor no, violando el `maxLength` del XSD (`RznSocRecep` 100, `GiroRecep` 40, `DirRecep` 70) si el dato real excede esos límites.

**Fix**: Truncar los 3 campos con el mismo patrón que `GiroEmis`.

---

## 18. Regla CodRef=2 duplicada en 3 lugares

**Causa**: `main.py`, `test_certificacion.py` y `firmar_libro_ventas.py` reimplementaban cada uno su propia versión de "si CodRef=2, forzar MntTotal=0" — con pequeñas diferencias entre copias (una vaciaba los items a `[]`, otra preservaba nombre/cantidad y solo zeroeaba el precio).

**Fix**: Centralizada en `aplicar_regla_corrige_texto()` dentro de `builders/envio_dte.py`. Los 3 archivos ahora la importan de ahí. Se adoptó el comportamiento de `test_certificacion.py`/`firmar_libro_ventas.py` (preservar items, zerear precio) por ser el que corresponde al flujo ya validado con el SII real.

---

## 19. Validador: falso positivo de "IVA con tasa explícita" en NC que referencia una Factura

**Error**: `validator.py` marcaba `FALLA` el check "IVA con tasa explícita" en una Nota de Crédito (T61) con CodRef=2 ("Corrige Giro del Receptor"), aunque el documento era correcto (Monto Total=0, sin línea de IVA por diseño — regla REF-2-781).

**Causa**: `is_afecta` buscaba la substring `"FACTURA ELECTRÓNICA"` en TODO el texto del PDF, no solo en el recuadro de tipo propio del documento. Una NC que referencia una Factura la menciona en su tabla "Referencias a otros documentos" (`FACTURA ELECTRÓNICA  38  ...`), lo cual matcheaba igual y activaba el check en un documento que en realidad es una Nota de Crédito de monto cero, sin ninguna línea de IVA que mostrar.

**Fix** en `validator.py`:
1. Restringir la búsqueda de `"FACTURA ELECTRÓNICA"` al texto ANTES de `"REFERENCIAS A OTROS DOCUMENTOS"` (el encabezado propio del documento, no las referencias).
2. Excluir además cualquier documento con `Monto Total: $0` — una NC/ND con CodRef=2 nunca debe llevar tasa de IVA explícita, sin importar el tipo de documento referenciado.

**Cómo se encontró**: probando `/certificar` end-to-end contra el set real después de un merge grande — bajó de 12/12 a 11/12 aprobados. Sirve de recordatorio: cualquier cambio a `validator.py` debe probarse contra el set completo (incluye casos CodRef=2), no solo contra un DTE con montos simples.

---

## 20. LibroVentas LRH desde el wizard — `main.py` usaba un builder distinto al certificado

**Error** (RUT 78460465-9, envío 258773014, 2026-09-14): `LRH - Envio de Libro Rechazado - Descuadrado` con
`LBR-3 Resumen No Cuadra Con Informacion de Detalle [Tipo Doc:61 - TotMntExe/TotMntIVA/TotMntTotal/TotMntNeto]`
y `LBR-2 Reparo en Calculo de [TpoDoc] debe ser [40, 43, 103] T:[61]`.

**Causa**: `libro_builder.py` tenía DOS implementaciones del libro de ventas:
- `build_unsigned_libro_ventas()` — montos positivos, usada por `test_certificacion.py` → la que produjo el libro LOK de PUDU.
- `build_libro_ventas()` — copia con las NC en NEGATIVO en el `Detalle` (resumen en positivo), usada por **`main.py` (el wizard)**. Nunca se probó contra el SII porque la certificación de PUDU se corrió con el script, no con la web.

El descuadre es exactamente eso: resumen T61 positivo vs. detalles T61 negativos; y los negativos disparan el LBR-2 de liquidaciones.

**Fix**: `build_libro_ventas()` y `build_libro_compras()` ahora delegan en las funciones `build_unsigned_*` (única fuente) con `fecha_doc="2000-01-01"` para el periodo pre-RCV. De paso se corrigió `build_libro_compras()`, que pasaba el timestamp actual (periodo = mes actual, no `2000-01`) — camino a un `CRT-3 Periodo invalido`.

**Regla**: cualquier función que genere XML para el SII debe tener UNA implementación; los scripts de prueba y el wizard llaman a la misma.

---

## 21. DATOS.txt de 5 líneas → CRT-3-19 "Fecha/Numero Resolucion Invalido"

**Error** (RUT 78460465-9, 2026-09-14): EnvioDTE rechazado con `CRT-3-19`.

**Causa**: `main.py` aceptaba un DATOS.txt de 5 líneas y rellenaba en silencio `NroResol=0` y `FchResol=<hoy>`. La propia web decía "5 líneas". El SII exige en la carátula el N° y fecha de resolución **publicados en los datos de la empresa en el ambiente de certificación** (Manual SII, sección "Envío del Set de Pruebas"): N° = 0 en certificación, fecha ≠ hoy.

**Fix**: `_parse_datos()` en `main.py` exige las 11 líneas y valida RUT/número/fecha (422 con el nombre de la línea que falta); la web muestra el formato completo, valida el archivo al cargarlo y ofrece una plantilla. El archivo se decodifica como UTF-8 si es válido y como ISO-8859-1 si no (antes un DATOS.txt en UTF-8 con acentos salía con mojibake en el XML).

---

## 22. Etapa 3 daba 500 en Cloud Run — scripts fuera del contexto Docker

**Causa**: `/etapa3` invocaba `<raíz>/verify/firmar_respuesta_dte.js` y `firmar_envio_recibos.js`, que además hacían `require('d:/PUDU/SII_pudu_Server/src/signer')`. El Dockerfile empaqueta solo `backend/`, así que en producción no existían ni los scripts ni el signer. La Etapa 3 de PUDU pasó porque se corrió local.

**Fix**: copias en `backend/builders/firmar_*.cjs` usando `./vendor/signer.js` (misma lógica de firma aprobada el 2026-05-18) y `@xmldom/xmldom` agregado a `backend/package.json`.

---

## 23. Muestras impresas: "Firma TED del timbre no coincide con firma TED del XML"

**Error** (78460465-9, 2026-09-15): al subir los PDF de Etapa 1 al portal de Muestras Impresas, el SII crea la fila (Caso/Doc. de prueba) pero la deja **sin archivo** y al subir uno solo responde ese mensaje. Los 4 de simulación sí pasaban.

**Causa**: cada "Generar" del wizard vuelve a firmar el TED con `TSTED` = hora actual → `FRMT` distinto aunque folios y montos sean iguales. El Set Básico aprobado (envío 258771808) salió de una corrida; los PDF, de otra posterior. El SII compara el `FRMT` del PDF417 con el del DTE que recibió.

**Fix operativo**: los PDF de Etapa 4 deben generarse desde el **mismo** `EnvioDTE` que se subió (mismo ZIP). El wizard ahora lo avisa en Etapa 1 y Etapa 4. Si el ZIP se perdió, no hay forma de reconstruir la firma: hay que reenviar un Set Básico nuevo con folios nuevos y usar esa corrida para libros y PDF.

**Mejora pendiente**: persistir cada corrida en un bucket (GCS) por RUT/fecha — el Cloud Run tiene disco efímero y cada deploy lo borra.

**Además**, en la misma pantalla: *Rut Proveedor* = proveedor del software (78392059-K PUDU), no el receptor ficticio C&C SPA. Y las filas que quedan bajo SIMULACIÓN sin "Caso de Prueba" (Validación ✗) son duplicados de una fila PRUEBA ya existente: eliminar la fila sin archivo y resubir el PDF.

---

## 24. Alineación con el Manual de Muestras Impresas (revisión 2026-09-15)

Contrastado `generator.py` con `Documentacion/manual_muestras_impresas.pdf` (§1.1–1.5) y `main.py /etapa3` con los XSD `RespuestaEnvioDTE_v10` / `EnvioRecibos_v10`:

- §1.5: el rótulo "Timbre Electrónico SII" va **bajo** el timbre (el lector del SII lo usa para localizar el barcode) → antes iba al costado. Leyenda literal "Res. N de AAAA – Verifique documento: www.sii.cl".
- §1.1.4: letras del recuadro ≥ 10 pt en negrita → la línea R.U.T. iba en 8 pt. Unidad SII ("S.I.I. – …") **bajo el recuadro**, no en la línea de la fecha.
- XSD `ResultadoDTE/CodEnvio` = código del envío en que se recibió el DTE (el mismo `1` de `RecepcionEnvio`), no un correlativo por documento.
- `MailContacto` es opcional en ambos esquemas: ahora sale de la línea 12 del DATOS.txt (opcional) y si no está, se omite (antes iba `contacto@empresa.cl` inventado).

Ninguno de estos puntos fue rechazado por el SII en la certificación de PUDU (aprobó 16/16 y los 3 XML de intercambio), pero el manual es explícito y el revisor humano ("Rev. Func.") puede objetarlos.

---

## 25. Exportación (110/111/112): módulo aparte + validación XSD (v1.7.0, 2026-09-21)

**Fuente**: `D:\PUDU\Documentacion SII\` — Formato DTE v2.5 (2026-02), XSD oficiales (`XML/schema_dte/`, copiados a `backend/schemas/`), y los EnvioDTE reales `exportartaciony doc nuevos/dte110f202.xml` / `dte112f102.xml` (validan contra el XSD).

**Qué es distinto en exportación** (y por qué NO se reutiliza `build_dte_xml`):
- El cuerpo del DTE es `<Exportaciones ID>` en vez de `<Documento ID>` (el XSD separa las familias Documento / Liquidacion / Exportaciones). `build_envio_dte` busca `Documento` → habría fallado.
- Receptor = `55555555-5` siempre; `Extranjero/Nacionalidad` opcional.
- `Totales` = `TpoMoneda` (enum TipMonType: "DOLAR USA", "EURO", "PESO CL"…) + `MntExe` + `MntTotal`, ambos `xs:decimal`. Sin `MntNeto`/`IVA`; cada ítem `IndExe=1`.
- `OtraMoneda` ("PESO CL", `TpoCambio`, `MntExeOtrMnda`, `MntTotOtrMnda`) — el XSD lo marca opcional, la bitácora del Formato (2017) lo exige en exportación.
- `Transporte/Aduana`: `CodModVenta` obligatorio salvo IndServicio 3/4/5; el resto según mercadería. Códigos = tablas de Aduana (aduana.cl), no del SII. **Orden de elementos estricto** (ver `build_exportacion_dte`).
- NC/ND 111/112 deben referenciar la 110 (`TpoDocRef=110`, `CodRef` 1/2/3).
- TED: `MNT` es `ValorType` (decimal) en Exportaciones, no `unsignedLong` como en Documento.

**Implementación**: `backend/exportacion.py` (modelo + builder + envío + parser), `backend/generator_exportacion.py` (PDF sin cedible, con moneda/país/puertos/bultos que exige el Manual de Muestras §"Documentos de Exportación"), `backend/routers/exportacion_api.py` (`/adicionales/exportacion/simulacion`, `/adicionales/exportacion/muestras`, `/adicionales/validar-xsd`), `src/routes/adicionales.tsx`. Solo se tocó del set básico: `main.py` (include_router) y `validator.py` (3 nombres en `TIPO_NOMBRE`).

**Validación XSD**: `xsd_validator.validar_envio_dte()` corre sobre cada EnvioDTE de exportación antes de devolverlo. De paso se comprobó que el EnvioDTE aprobado de PUDU (set básico) también valida — el endpoint `/adicionales/validar-xsd` sirve para cualquier tipo.

**Pendiente**: parser del `SIISetDePruebas` de exportación (el SII lo genera por contribuyente; La Repostería 77334712-3 ya tiene CAF 110/111/112 del 2026-08-26 y puede bajarlo en maullin), tablas de Aduana completas, libro de ventas con 110/111/112.

**Actualización 2026-09-22 — par 110/112 ACEPTADO por el SII**: `backend/docs/referencia_exportacion/dte110f202.xml` y `dte112f102.xml` (Siganet/Bicom, 76326028-3, ambiente certificación) fueron aceptados según quien los entregó. Lo que eso confirma para la validación automática del SII:
- Aduana mínima = solo `CodModVenta` (sin cláusula, vía, país, puertos ni bultos).
- `TpoMoneda` cualquiera del enum ("CHELIN") y `OtraMoneda` PESO CL con `TpoCambio=1`: el SII no cruza el tipo de cambio contra el Banco Central.
- NC 112 `CodRef=1` → 110 aceptada como anulación.
- Carátula con `RutReceptor 55555555-5`: eran envíos normales, no el set reportado (el set sigue con 60803000-K + referencia SET/CASO).
Lo que NO confirma: los reparos del revisor humano en Muestras Impresas (el Manual pide puertos, bultos, país y moneda cuando hay mercadería) ni los casos del set de exportación.

---

## 26. Guía de Despacho (52): SET GUIA DE DESPACHO (v1.8.0, 2026-09-22)

**Set real**: PUDU 78392059-K, N° atención 5089739 (`backend/docs/SetGuias_ejemplo_78392059K.txt`). Formato distinto al set básico: `DOCUMENTO GUIA DE DESPACHO` (sin "ELECTRONICA"), `MOTIVO:` y `TRASLADO POR:` en texto, ítems con cantidad y (solo en venta) precio. No trae libro de guías.

**Mapeo** (`guias.py`, Formato DTE v2.5):
- MOTIVO → `IndTraslado`: "TRASLADO … ENTRE BODEGAS" → 5 (interno); "VENTA" → 1; devolución 7; consignación 3; gratuita 4; por efectuar 2; exportación 8/9; otro 6.
- TRASLADO POR → `TipoDespacho`: "CLIENTE" → 1 (por cuenta del receptor); "EMISOR … AL LOCAL DEL CLIENTE" → 2; interno → 3 (emisor a otras instalaciones).
- Traslado interno: receptor = emisor (instrucción literal del set), `MontoItem 0`, `MntTotal 0`, sin `PrcItem`, **sin cedible** ("inoficioso").
- Venta: `MntNeto/TasaIVA/IVA/MntTotal` como factura; PDF tributario + cedible "CEDIBLE CON SU FACTURA" con acuse de recibo (Manual de Muestras §1.4).
- Referencia `SET` / `CASO n-n` en línea 1, igual que el set básico.

**Reutilizado del set básico** (sin modificarlo): `CAF`, `build_ted`, `calc_totales` y `build_envio_dte` (la guía usa `<Documento>`, así que el empaquetado/firma es el mismo). Módulo propio: `guias.py`, `generator_guias.py`, `routers/guias_api.py` (`/adicionales/guias/set`, `/adicionales/guias/muestras`), UI en `/adicionales`.

**Respuesta del SII (77334712-3, set 5089806, envío 259729604, 2026-09-22)**: SRH con un solo reparo, caso 1 (traslado interno): *"Los Indicadores (Despacho/Traslado) No Corresponden"*. Los casos de venta con `TipoDespacho` 1 y 2 pasaron. → Con `IndTraslado=5` **no se emite `TipoDespacho`** (corregido: solo se emite cuando el set trae "TRASLADO POR"). `SII_pudu_Server` nunca emite `TipoDespacho`, consistente con esto.

**Simulación (Etapa 2) de guías** — `/adicionales/guias/simulacion`: mismos tipos de traslado que el set pero con productos y cliente reales (Manual de Certificación §6.2: "documentos … con datos representativos, paralelos de la operación real"). Usa el MISMO `build_guia_dte` con `referencia_set=False` (la referencia SET/CASO es exclusiva del set de pruebas), de modo que las reglas ya aceptadas por el SII se aplican igual: receptor = emisor y montos 0 en interno, `TipoDespacho` solo en venta, cedible solo en venta.

---

## 27. Exportación: SET BASICO DOCUMENTOS DE EXPORTACION (1) y (2) (v1.9.0, 2026-09-22)

**Set real**: PUDU 78392059-K, N° atención 5089803 y 5089804 (`backend/docs/SetExportacion_ejemplo_78392059K.txt`). Dos sets en un archivo, **se envían por separado** (instrucción 4 del set). Formato: `DOCUMENTO FACTURA DE EXPORTACION ELECTRONICA`, tabla de ítems (`CANTIDAD / UNIDAD MEDIDA / PRECIO UNITARIO` o `VALOR LINEA` para servicios), y un bloque `CLAVE: valor` con moneda, forma de pago, modalidad, cláusula, total cláusula, vía, puertos, unidades de tara/peso, tipo y total de bultos, flete, seguro, país. NC solo con cantidades ("el precio unitario debe ser el mismo de la factura"); ND anula la NC.

**Mapeo texto → código** (`aduana_tablas.py`, generado desde los seeds oficiales de Aduana en pos-matic_no): ARGENTINA 224, JAPON 331, ARICA 901, PUNTA ARENAS 912, BUENOS AIRES 262, YOKOHAMA 444, AEREO 4, MARITIMA 1, FOB 5, S/CL 6, A FIRME 1, CONSIGNACION CON MINIMO A FIRME 4, CONTENEDOR REFRIGERADO 75, ROLLOS 13, U 10, KN 6, PAR 17, LT 24, ACRED 2, SIN PAGO 21. `MIC` → TpoDocRef 810, `RESOLUCION SNA` → 812, `DUS` → 807, `AWB` → 809 (folio/fecha de esas referencias se inventan: "agregue otros datos que estime necesarios").

**Reglas que impuso el XSD/Formato al construirlo** (todas descubiertas por la validación XSD local, no por el SII):
- `MntTotal = 0` cuando `FmaPagExp = 21` (SIN PAGO) — Formato DTE, campo 124. `MntExe` y `MntExeOtrMnda` sí llevan el monto.
- `TotClauVenta` ≥ 0.01: nunca usar `MntTotal` como default (sería 0 con SIN PAGO); usar el valor del set o `MntExe`.
- `DescuentoMonto` / `RecargoMonto` de línea son `MntImpType` = **entero**, aunque los montos de exportación sean decimales. Se redondean y `MontoItem` se calcula con el entero.
- Flete y seguro van en `MntFlete`/`MntSeguro` **y además** como dos `DscRcgGlobal` tipo R en `$` con `ValorDROtrMnda` (instrucción (**) del set). Las "comisiones en el extranjero 11% del total de la cláusula" son un tercer recargo global.
- `IndServicio`: 3 cuando los ítems son "VALOR LINEA" (servicios; con eso `CodModVenta` deja de ser obligatorio y no se emite), 4 hotelería (caso con NACIONALIDAD y sin puertos: sin bloque Aduana, `Extranjero/Nacionalidad`).
- Tara/pesos: el set solo da unidades; se informan valores por defecto (50 / 1000 / 950) en esas unidades.

**Implementación**: `exportacion.py` (`parse_set_exportacion`, `docs_desde_set`, modelo con `valor_linea`, descuentos/recargos de línea y `RecargoGlobal`), `routers/exportacion_api.py` `/adicionales/exportacion/set` (un EnvioDTE por set, folios correlativos por tipo entre sets, ZIP con carpeta por set), UI "A · Set de pruebas del SII" en `/adicionales`.

**Pendiente hasta la respuesta del SII**: `IndServicio 3/4`, `TipoDespacho`-like interpretaciones y los folios inventados de DUS/AWB/MIC/SNA son lectura del Formato; si el SII repara, ajustar y anotar aquí.

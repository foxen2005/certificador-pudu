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

**Fix**: En el Libro, las NCs (T61) deben tener sus montos como NEGATIVOS en los campos de monto, pero el campo TpoDoc del resumen debe mostrar el tipo con el valor absoluto (o con la estructura correcta que el SII espera).

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

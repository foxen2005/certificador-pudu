# Registro de Envíos al SII — Certificación 78392059-K

Bitácora de envíos generados y enviados al SII durante el proceso de
certificación de PUDU TECNOLOGIA SPA.

## Datos del contribuyente

- **RUT Empresa**: 78392059-K
- **Razón Social**: PUDU TECNOLOGIA SPA
- **RUT Envía**: 15996452-3 (VICTOR MANUEL BARRIENTOS ARZOLA)
- **Fecha Resolución**: 2026-05-05
- **Número Resolución**: 0
- **Set Básico Nº Atención**: 4809211
- **Libro Ventas Nº Atención**: 4809212
- **Libro Compras Nº Atención**: 4809213

## Convenciones

| Estado | Significado |
|---|---|
| EPR | Envío Procesado |
| RCT | Rechazado por Error en Caratula |
| RCH | DTE Rechazado |
| LOK | Libro Aceptado - Cuadrado |
| LRC | Carátula de Libro Inválida |
| LRH | Libro Rechazado - Descuadrado |
| LRF | Libro Rechazado por Firma |
| LTC | Libro Cerrado - Información Cuadrada |
| AOK | Aceptado sin reparos |
| AOR | Aceptado con reparos |
| SRH | Set de Prueba Rechazado |

---

## Bitácora cronológica

### 2026-05-14 ~17:34 — Intento con builders/ separados (envio_dte.py)

**Folios usados:**
| Tipo | Folios |
|---|---|
| 33 (Factura Electrónica) | 17, 18, 19, 20 |
| 56 (Nota de Débito Electrónica) | 5 |
| 61 (Nota de Crédito Electrónica) | 13, 14, 15 |

**Archivos generados**: `output/certificacion_20260514_215842/`

**Envíos al SII**:
| Documento | Identificador | Fecha | Estado |
|---|---|---|---|
| EnvioDTE | 248918068 | 14/05/2026 22:15 | **RFR** — firma outer SetDTE rechazada |

**Causa raíz identificada**: `c14n_for_sii` removía `xmlns:xsi`. El SII Java SÍ
incluye `xmlns:xsi` en su C14N (verificado contra LibreDTE certificado, que
explícitamente lo declara en `<SignedInfo>` outer). Fix: solo eliminar
`xmlns=""` en C14N, dejar `xmlns:xsi` tal cual.

### 2026-05-14 ~22:42 — Fix C14N: conservar xmlns:xsi (intento 2 con lxml)

Mismos folios. Solo corrección en `builders/common.py` (no remover xmlns:xsi).

**Archivos generados**: `output/certificacion_20260514_224237/`

**Envíos al SII**:
| Documento | Identificador | Fecha | Estado |
|---|---|---|---|
| EnvioDTE | 248918996 | 14/05/2026 22:43 | **EPR** envío procesado, pero los 8 DTEs internos rechazados con DTE-3-505 |

Outer ahora pasa, pero los inner siguen fallando. Hipótesis: lxml propaga
xmlns:xsi al subtree del Documento aunque el SII no lo incluya en su C14N
de subtree.

### 2026-05-17 ~20:09 — EnvioDTE ACEPTADO (8/8 sin reparos) — set 4832493

**Folios usados:** T33 33-36, T56 9, T61 25-27 (set SIISetDePruebas78392059K-1705.txt)

**Archivos generados**: `output/certificacion_20260517_2009/`

**Fix aplicado**: NC de devolución ahora hereda `descuento_pct` de los ítems de la factura referenciada.

**Envíos al SII:**
| Documento | Identificador | Fecha | Estado |
|---|---|---|---|
| EnvioDTE | **249112164** | 17/05/2026 | **EPR — 8/8 aceptados sin reparos ✓** |
| LibroVentas | **249112356** | 17/05/2026 | **LOK / LTC — Aceptado ✓** |
| LibroCompras | 249112586 / 249113280 | 17/05/2026 | LNC — Libro ya LTC desde set 4809213 (periodo 2000-01 cerrado) |
| LibroCompras | **249113598** | 17/05/2026 | **LTC — Aceptado sin reparos ✓** (periodo 2000-02, carpeta certificacion_20260517_2114) |

---

### 2026-05-17 ~23:19 — ETAPA 2 (Simulación) ACEPTADA — 3/3 sin reparos ✓

**Folios usados:** T33 F37, T61 F28, T56 F10

**Archivos generados**: `output/etapa2_20260517_2318/`

**Descripción**: EnvioDTE de Simulación con 3 DTEs a C&C SPA (77221286-0).
- T33 F37: Factura — 2× Ubiquiti Loco M5 @ 35.000 → $83.300
- T61 F28: NC devolución — 1× Ubiquiti Loco M5 @ 35.000 → $41.650 (CodRef=3, ref T33F37)
- T56 F10: ND anula NC — 1× Ubiquiti Loco M2 @ 35.000 → $41.650 (CodRef=1, ref T61F28)

**Caratula**: RutReceptor=60803000-K (SII portal), RutEmisor=78392059-K

**Envíos al SII:**
| Documento | Identificador | Fecha | Estado |
|---|---|---|---|
| EnvioDTE Etapa 2 | **249115582** | 17/05/2026 23:19 | **EPR — 3/3 aceptados sin reparos ✓** |

**Script**: `backend/test_etapa2.py`

---

### 2026-05-17 ~19:56 — EnvioDTE RECHAZADO (folios ya consumidos)

**Folios usados:** T33 25-28, T56 7, T61 19-21 (set SIISetDePruebas78392059K-1705.txt)

**Envíos al SII:**
| Documento | Identificador | Fecha | Estado |
|---|---|---|---|
| EnvioDTE | 249111818 | 17/05/2026 19:56 | **EPR — 8/8 RCH** (DTE-3-100/101 folios ya recibidos) |

**Causa**: Folios T33F25-28, T56F7, T61F19-21 ya habían sido enviados en intento anterior (certificacion_20260517_1949). El SII los rechaza aunque el envío anterior no fuera aceptado. Fix: avanzar a T33F29-32, T56F8, T61F22-24.

---

### 2026-05-14 ~23:37 — EnvioDTE ACEPTADO (8/8 sin reparos)

**Folios usados**: T33 21-24, T56 6, T61 16-18

**Cambios respecto al intento anterior**:
- Folios nuevos (después de EPR los folios anteriores quedaron consumidos por
  el SII aunque hubieran sido RCH/RPR → DTE-3-100/3-101 si se reusan).
- Fix REF-2-781: NCs con CodRef=2 ("CORRIGE GIRO/RUBRO/TEXTO") generadas con
  MntTotal=0 y un item placeholder sin precio (no se copian items del DTE
  referenciado).

**Archivos generados**: `output/certificacion_20260514_233650/`

**Envíos al SII**:
| Documento | Identificador | Fecha | Estado |
|---|---|---|---|
| EnvioDTE | 248925118 | 14/05/2026 23:37 | **EPR — 8/8 aceptados sin reparos ✓** |
| LibroVentas | 248930314 | 15/05/2026 | LRH — Rechazado (TotMntExe/Neto/IVA/Total T61 descuadrado + LBR-2 montos negativos) |
| LibroVentas | 249048504 | 15/05/2026 | LRH — Rechazado (LBR-3 cuadre T61 + LBR-2 TpoDoc negativo) |
| LibroVentas | **249048540** | 15/05/2026 | **LOK / LTC — Aceptado ✓** |
| LibroVentas | 249110212 | 17/05/2026 | SRH — Rechazado (reenvío a Nº Atención ya aceptado — irrelevante) |
| LibroCompras | **249110784** | 17/05/2026 18:52 | **LTC — Libro Cerrado Cuadrado ✓** (LNC en envío — libro ya estaba aceptado previamente) |

### 2026-05-14 ~23:32 — Reuso de folios después de EPR → DTE-3-100/101

Reusamos folios 17/5/13 tras EPR con reparo del intento anterior → SII
rechaza todos con "DTE Repetido" o "Folio ya recibido". Lección: después de
un EPR (aunque sea con reparos), saltar a folios nuevos. Documentado en la
memoria.

### 2026-05-14 ~23:22 — EnvioDTE con reparo en CASO 5 (REF-2-781)

Las firmas finalmente pasaron (8 DTEs procesados, 1 outer SetDTE aceptado),
pero el T61F13 quedó RPR con REF-2-781: "Modifica Texto no debe tener montos
[2] <> [3]". Causa: la NC "CORRIGE GIRO DEL RECEPTOR" (CodRef=2) copiaba los
items del DTE referenciado → tenía MntTotal > 0 incompatible con CodRef=2.

### 2026-05-14 ~23:15 — Standalone DTE signing + string-concat embedding

Después de detectar DTE-3-505 con xml-crypto firmando inner DTEs dentro del
EnvioDTE, revisamos `SII_pudu_Server/server.js:757` y descubrimos que el flujo
productivo del PUDU server es:

  1. Construir cada `<DTE>` con `<Documento>` dentro (sin EnvioDTE alrededor)
  2. Firmar el `<DTE>` en CONTEXTO STANDALONE (xmlns:xsi del EnvioDTE no contamina)
  3. Embeber los `<DTE>` ya firmados en el EnvioDTE usando STRING CONCAT
     (NO con lxml — re-serializar con lxml cambia whitespace y rompe los digests
     ya firmados)
  4. Firmar el `<SetDTE>` outer

Refactor de `builders/envio_dte.py` aplicando esta estrategia:
- Cada DTE se envuelve standalone con `<DTE xmlns="...sii.cl/SiiDte">`
- `sign_via_pudu` firma cada DTE individualmente
- Los bytes del DTE firmado se preservan EXACTAMENTE al embeber (string concat)
- `sign_via_pudu` firma el outer SetDTE al final

**Archivos generados**: `output/certificacion_20260514_231532/`

**Verificación local**: xml-crypto re-verifica las firmas inner como inválidas
(por una quirk: incluye xmlns:xsi heredado al computar C14N de subtree). PERO
el SII Java spec-compliant DEBE excluir xmlns:xsi cuando no es visibly utilized
→ debería aceptar los digests standalone.

**Estado**: pendiente subir.

### 2026-05-14 ~23:04 — Migración a PUDU server (xml-crypto)

Decisión: dejar de firmar en Python con lxml. Usar `signer.js` del
`SII_pudu_Server` (xml-crypto, probado en producción).

**Cambios**:
- `builders/pudu_sign.cjs`: script Node.js que carga `signer.js` del PUDU
  server vía `require()`. Lee JSON de stdin con XML+pfx+lista de firmas, las
  aplica con `signInPlace`, devuelve XML firmado por stdout.
- `builders/common.py`: nueva función `sign_via_pudu()` que invoca el script
  vía `subprocess.run(["node", ...])`.
- `builders/envio_dte.py`: ya no firma en Python; serializa XML sin firma y
  llama `sign_via_pudu` con la lista de 9 firmas (8 DTEs + 1 outer SetDTE).

**Folios**: T33 17-20, T56 5, T61 13-15 (mismos).

**Archivos generados**: `output/certificacion_20260514_230408/`

**Estado**: pendiente subir.

---

### 2026-05-18 ~01:02 — ETAPA 4 (Muestras Impresas) APROBADA — 16/16 ✓

**PDFs generados**: `output/muestras_20260518_0102/`

**Script**: `backend/gen_muestras.py` (lee EnvioDTE de certificacion_20260517_2009 + etapa2_20260517_2318)

**Fix aplicado**: `generator.py` ahora compacta el TED antes de codificar el barcode PDF417
(`re.sub(r'>\s+<', '><', ted_xml)`). Node.js XMLSerializer expandía `<RNG>` y `<RSAPK>`
con saltos de línea al re-firmar, rompiendo la verificación FRMA (C14N sobre DA compacto)
y FRMT. El TED aprobado de referencia (PUMA SERVICIOS SPA) confirmó que el SII
valida sobre DA/DD sin whitespace inter-tag.

**Resultado SII:**
| Tipo | Items | Timbre | Caf | Ted | Rev. Func. | Validación |
|---|---|---|---|---|---|---|
| PRUEBA | 12 | ✓ | ✓ | ✓ | ✓ | ✓ |
| SIMULACION | 4 | ✓ | ✓ | ✓ | ✓ | ✓ |

**Estado**: Enviado al SII. 16/16 aprobados sin reparos.

---

### 2026-05-18 ~00:10 — ETAPA 3 (Intercambio) ACEPTADA — 3/3 OK ✓

**SET de Intercambio recibido**: `etapa3_ENVIO_DTE_4832681_1805.xml` (N° Atención 4832681)

| DTE en el SET | RUTRecep | MntTotal | Nuesto/Ajeno |
|---|---|---|---|
| T33 F52727 | 78392059-K | $23.015 | NUESTRO |
| T33 F52728 | 69507000-4 | $31.345 | AJENO |

**Archivos generados**: `output/etapa3_20260518_0010/`

**Envíos al SII:**
| Archivo | Resultado |
|---|---|
| 1_RecepcionDTE.xml | **OK — cargado exitosamente ✓** |
| 2_EnvioRecibos.xml | **OK — cargado exitosamente ✓** |
| 3_ResultadoDTE.xml | **OK — Validación Resultado Aprobación Comercial de Documento OK ✓** |

**Causa raíz del error anterior**: se descargó el SET dos veces — el SII registra el ÚLTIMO SET generado, por lo que el archivo anterior (N° 4832678, folios 52769/52770) ya no era válido.

**Script**: `backend/test_etapa3.py`

---

## Plantilla para próximos envíos

```
### YYYY-MM-DD HH:MM — <descripción intento>

**Folios usados:**
| Tipo | Folios |
|---|---|
| 33 | x, y, z |
| 56 | a |
| 61 | b, c, d |

**Envíos al SII:**

| Documento | Identificador de Envío | Fecha SII | Estado | Notas |
|---|---|---|---|---|
| EnvioDTE | | | | |
| LibroVentas | | | | |
| LibroCompras | | | | |

**Resumen del resultado**: ...
```

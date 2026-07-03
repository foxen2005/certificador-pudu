# Referencia a memorias globales

Las memorias globales del agente (Claude) están en:

```
C:\Users\DigitalFox\.claude\projects\d--SandBox\memory\
```

> ⚠️ Tras el reformateo (drive F: → D:, jun-2026) la carpeta de memoria quedó en un
> namespace nuevo (`d--SandBox`, antes `f--SandBox`, que ya no existe). Los 4 archivos
> listados abajo **no existen hoy** en `d--SandBox/memory/` — se perdieron en la migración
> y nunca se recrearon. En particular `sii_certificador_lessons.md` (el catálogo de errores
> SII) es información valiosa que se debería reconstruir a partir de lo que se recuerde o
> de `backend/REGISTRO_ENVIOS.md` y los comentarios en `test_certificacion.py`.

## Memorias relevantes para este proyecto (histórico — verificar si existen antes de asumir)

| Archivo | Propósito |
|---|---|
| **`sii_certificador_lessons.md`** | ⭐ Catálogo completo de errores SII y soluciones. **LEER ANTES** de tocar firma XMLDsig o libros |
| `sii_certificador_firma_fix.md` | Bugs históricos de firma XML corregidos (lxml C14N) |
| `project_sii_certificador.md` | Descripción del proyecto SaaS |
| `dtex_auth_token.md` | Token auth para dtex-proxy ↔ SII_pudu_Server |

## Regla de oro de firma

> **NUNCA firmar XMLDsig en Python con lxml. SIEMPRE delegar al `signer.js` del
> `SII_pudu_Server` (xml-crypto), invocándolo desde Python vía
> `sign_via_pudu()` en `backend/builders/common.py`.**

Script puente: `backend/builders/pudu_sign.cjs` (lee JSON de stdin, devuelve XML
firmado por stdout).

## Códigos de tipo de documento (libros)

| Doc | Electrónico | Papel |
|---|---|---|
| Factura | 33 | 30 |
| Factura de Compra | 46 | 45 |
| Nota de Crédito | 61 | 60 |
| Nota de Débito | 56 | 55 |
| Guía de Despacho | 52 | 50 |
| Liquidación | 43 | 40 |
| Factura Exenta | 34 | — |

## Tabla rápida de estados SII

| Estado | Capa | Significado |
|---|---|---|
| EPR | Envío DTE | Envío procesado (puede tener DTEs RCH/RPR/AOK adentro) |
| RFR | Envío DTE | Rechazado por error en firma outer del SetDTE |
| RCT | Envío DTE | Rechazado por error en carátula |
| RCH | DTE individual | DTE rechazado |
| RPR | DTE individual | DTE aceptado con reparos |
| AOK | DTE individual | Aceptado sin reparos |
| LOK | Libro | Libro aceptado, cuadrado |
| LRC | Libro | Carátula del libro inválida |
| LRH | Libro | Libro rechazado, descuadrado |
| LRF | Libro | Rechazado por firma |
| LTC | Libro | Libro cerrado, info cuadrada |

## Errores comunes y links a la solución

- **DTE-3-505 "Firma DTE Incorrecta"** → `sii_certificador_lessons.md` § Errores de firma
- **RFR "Rechazado por Error en Firma"** → `sii_certificador_lessons.md` § Errores de firma
- **CRT-3 "Periodo invalido"** → `sii_certificador_lessons.md` § Libros pre-RCV (usar 2000-01)
- **LBR-3 "Falta MntNeto/MntExe/MntIVA"** → siempre emitir `MntExe` aunque sea 0
- **REF-2-781 "Modifica Texto no debe tener montos"** → NC `CodRef=2` con `MntTotal=0`
- **DTE-3-100 "DTE Repetido"** → no reusar folios ya enviados, actualizar `FOLIOS_YA_ENVIADOS`

# Guía de Pruebas — SII Certificador

## Archivos que necesitas

| Archivo | Obligatorio | Descripción |
|---|---|---|
| `SIISetDePruebas*.txt` | ✅ | Lo entrega el SII al iniciar certificación |
| `DATOS.txt` | ✅ | Datos del emisor y representante legal |
| `certificado.pfx` o `.p12` | ✅ | Certificado digital del representante legal |
| `CAF_T33.xml` | Según set | Código de autorización de folios Factura Electrónica |
| `CAF_T34.xml` | Según set | CAF Factura No Afecta o Exenta |
| `CAF_T52.xml` | Según set | CAF Guía de Despacho |
| `CAF_T56.xml` | Según set | CAF Nota de Débito |
| `CAF_T61.xml` | Según set | CAF Nota de Crédito |

---

## Formato DATOS.txt

El archivo debe tener **exactamente estas líneas en este orden** (una por línea):

```
Nombre del Representante Legal        ← Línea 1
RUT del Representante (con guión)     ← Línea 2
Razón Social de la Empresa            ← Línea 3
RUT de la Empresa (con guión)         ← Línea 4
Contraseña del certificado .pfx       ← Línea 5
Giro Comercial                        ← Línea 6
Código Actividad Económica (Acteco)   ← Línea 7
Dirección de Origen                   ← Línea 8
Comuna de Origen                      ← Línea 9
Número de Resolución SII              ← Línea 10
Fecha de Resolución (YYYY-MM-DD)      ← Línea 11
```

**Ejemplo** (`docs/DATOS_ejemplo.txt`):

```
Juan Pérez González
12345678-9
EMPRESA TEST LTDA
76543210-K
clave_pfx_aqui
VENTA AL POR MENOR DE COMPUTADORES Y EQUIPOS
471001
Av. Providencia 1234 Of. 501
Providencia
100
2018-01-18
```

> **Nota:** La Fecha y Número de Resolución son los que entregó el SII cuando autorizó tu empresa para facturar electrónicamente. Si tienes resolución tipo "Exento" usa `0` como número y la fecha correspondiente.

---

## Cómo obtener los CAF

1. Ingresa al portal SII → **Facturación Electrónica → Código Autorización Folios (CAF)**
2. Solicita folios para cada tipo de documento que aparezca en tu Set de Pruebas
3. Descarga el archivo XML de cada CAF
4. El nombre del archivo no importa, el sistema lee el tipo de documento desde adentro

---

## Levantar el backend localmente

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Verifica que esté corriendo:
```bash
curl http://localhost:8000/
# → {"status":"ok","service":"SII Certificador"}
```

---

## Endpoint 1: Certificación completa

**`POST /certificar`**

Recibe el Set de Pruebas + CAFs + certificado PFX y genera todos los XMLs, PDFs y libros firmados.

### Con curl:

```bash
curl -X POST http://localhost:8000/certificar \
  -F "set_pruebas=@SIISetDePruebas_1234567.txt" \
  -F "datos=@DATOS.txt" \
  -F "pfx=@certificado.pfx" \
  -F "caf_33=@CAF_T33.xml" \
  -F "caf_56=@CAF_T56.xml" \
  -F "caf_61=@CAF_T61.xml" \
  -o resultado.json
```

Agrega solo los CAF que necesites según los tipos de documentos de tu set:

```bash
# Set con T33 + T34 + T52 + T56 + T61:
curl -X POST http://localhost:8000/certificar \
  -F "set_pruebas=@SIISetDePruebas_1234567.txt" \
  -F "datos=@DATOS.txt" \
  -F "pfx=@certificado.pfx" \
  -F "caf_33=@CAF_T33.xml" \
  -F "caf_34=@CAF_T34.xml" \
  -F "caf_52=@CAF_T52.xml" \
  -F "caf_56=@CAF_T56.xml" \
  -F "caf_61=@CAF_T61.xml" \
  -o resultado.json
```

### Respuesta:

```json
{
  "nro_atencion": "1234567",
  "nro_atencion_ventas": "1234568",
  "nro_atencion_compras": "1234569",
  "libro_ventas_generado": true,
  "libro_compras_generado": true,
  "documentos": 6,
  "pdfs_generados": 9,
  "aprobados": 9,
  "rechazados": 0,
  "resultados": [
    {
      "folio": 1,
      "tipo": 33,
      "tipo_nombre": "Factura Electrónica",
      "cedible": false,
      "archivo": "DTE_T33F1.pdf",
      "validacion": {
        "aprobado": true,
        "puntaje": 100,
        "checks": [...]
      }
    }
  ],
  "zip_base64": "UEsDBBQA..."
}
```

### Extraer el ZIP con Python:

```python
import base64, json

with open("resultado.json") as f:
    data = json.load(f)

zip_bytes = base64.b64decode(data["zip_base64"])
with open("documentos_certificacion.zip", "wb") as f:
    f.write(zip_bytes)
```

### Contenido del ZIP generado:

```
documentos_certificacion.zip
├── EnvioDTE_76543210K.xml      ← Sube este al SII (Set Básico)
├── DTE_T33F1.pdf
├── DTE_T33F1_CEDIBLE.pdf       ← Solo para T33, T34, T61
├── DTE_T33F2.pdf
├── DTE_T33F2_CEDIBLE.pdf
├── DTE_T34F1.pdf
├── DTE_T34F1_CEDIBLE.pdf
├── DTE_T52F1.pdf               ← Guía de Despacho (sin cedible)
├── DTE_T56F1.pdf               ← Nota de Débito (sin cedible)
├── DTE_T61F1.pdf
├── DTE_T61F1_CEDIBLE.pdf
├── LibroVentas_76543210K.xml   ← Sube este al SII (Set Libros Ventas)
└── LibroCompras_76543210K.xml  ← Sube este al SII (Set Libros Compras)
```

---

## Endpoint 2: Re-procesar un XML existente → PDFs

**`POST /procesar`**

Si ya tienes el EnvioDTE.xml generado y solo necesitas regenerar los PDFs:

```bash
curl -X POST http://localhost:8000/procesar \
  -F "file=@EnvioDTE_76543210K.xml" \
  -o resultado_procesar.json
```

---

## Endpoint 3: Validar un PDF existente

**`POST /validar`**

Valida un PDF ya generado con los 12 checks del SII:

```bash
curl -X POST http://localhost:8000/validar \
  -F "file=@DTE_T33F1.pdf" \
  | python -m json.tool
```

### Respuesta:

```json
{
  "archivo": "DTE_T33F1.pdf",
  "aprobado": true,
  "puntaje": 100,
  "checks": [
    {"nombre": "Tamaño A4", "ok": true, "detalle": "216x279mm"},
    {"nombre": "Tipo documento PDF", "ok": true, "detalle": "ok"},
    {"nombre": "RUT emisor presente", "ok": true, "detalle": "76.543.210-K"},
    {"nombre": "Folio presente", "ok": true, "detalle": "1"},
    {"nombre": "Timbre presente (PDF417)", "ok": true, "detalle": "ok"},
    {"nombre": "Cedible impreso", "ok": false, "detalle": "N/A - no es cedible"},
    ...
  ]
}
```

---

## Swagger UI

Con el servidor corriendo, accede a la documentación interactiva:

```
http://localhost:8000/docs
```

Desde ahí puedes subir archivos y probar los 3 endpoints directamente en el navegador.

---

## Checklist antes de subir al SII

Cuando el endpoint `/certificar` retorne `"rechazados": 0`, verifica:

- [ ] `EnvioDTE_*.xml` generado y en el ZIP
- [ ] Todos los PDFs tienen `"aprobado": true`
- [ ] `libro_ventas_generado: true` (si el set lo pide)
- [ ] `libro_compras_generado: true` (si el set lo pide)
- [ ] El `nro_atencion` en la respuesta coincide con el del Set de Pruebas

### Orden de subida al SII (certificación manual):

1. Subir `EnvioDTE_*.xml` en **SII → Facturación Electrónica → Set de Pruebas → Set Básico**
2. Anotar el TrackID que devuelve el SII
3. Esperar confirmación (puede tardar minutos)
4. Subir `LibroVentas_*.xml` en **Set Libro de Ventas**
5. Subir `LibroCompras_*.xml` en **Set Libro de Compras**

---

## Errores comunes

| Error | Causa | Solución |
|---|---|---|
| `Faltan CAFs para tipos de documento: [56]` | No subiste el CAF para Nota de Débito | Agrega `-F "caf_56=@CAF_T56.xml"` |
| `Error al leer archivos subidos` | El .pfx tiene encoding incorrecto | Verifica que el archivo no esté corrupto |
| `Error al parsear SIISetDePruebas` | Formato de set inesperado | Abre el set en un editor y verifica que tenga la estructura de CASOS |
| `CAF para tipo 33 sin folios disponibles` | El CAF solo tiene 1 folio y el set pide 2 T33 | Solicita un CAF con más folios |
| PDF con `"aprobado": false` | PDF no cumple algún check | Revisa el detalle de `checks` en la respuesta |
| `422` en `/certificar` | Archivo faltante o formato incorrecto | Lee el mensaje de error en el campo `detail` |

---

## Ejemplo de Set de Pruebas

Ver `docs/SetPruebas_ejemplo.txt` para un set completo de ejemplo con:
- 2× Factura Electrónica (T33), una con descuento global
- 1× Factura Exenta (T34)
- 1× Nota de Crédito (T61) referenciando T33
- 1× Nota de Débito (T56) referenciando T33
- 1× Guía de Despacho (T52) con IndTraslado=1
- Libro de Ventas y Libro de Compras

> **Importante:** El Set de Pruebas real lo entrega el SII al registrarte en el proceso de certificación. El archivo de ejemplo es solo para validar que el sistema parsea y genera correctamente antes de usar el set real.

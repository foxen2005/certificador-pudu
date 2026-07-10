"""
API FastAPI: recibe SIISetDePruebas + CAFs + PFX, genera XMLs firmados, PDFs y los valida.
También acepta XMLs ya generados para re-procesar.
"""
import os
import zipfile
import io
import re as _re
import subprocess
import tempfile
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from parser import parse_envio_dte, TIPO_NOMBRE, CEDIBLE_TIPOS
from generator import generate_pdf
from validator import validate_pdf
from set_parser import parse_set_pruebas, CasoSet, ItemSet
from builders.envio_dte import CAF, build_dte_xml, build_envio_dte, aplicar_regla_corrige_texto
from libro_builder import build_libro_ventas, build_libro_compras
from timestamped_output import get_timestamped_output_dir

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_BASE_DIR = os.path.join(_PROJECT_ROOT, "output")
_FIRMA_RESP  = os.path.join(_PROJECT_ROOT, "verify", "firmar_respuesta_dte.js")
_FIRMA_RECIB = os.path.join(_PROJECT_ROOT, "verify", "firmar_envio_recibos.js")

app = FastAPI(title="SII Certificador", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


RECEPTOR_PRUEBA = {
    "rut": "77221286-0",
    "razon_social": "C&C SPA",
    "giro": "VENTA AL POR MENOR DE ALIMENTOS EN COMER",
    "dir": "AVDA AUSTRAL 1780 JARDIN ORIENTE II",
    "cmna": "Puerto Montt",
}


@app.get("/")
def root():
    return {"status": "ok", "service": "SII Certificador"}


@app.post("/certificar")
async def certificar(
    set_pruebas: UploadFile = File(..., description="SIISetDePruebas*.txt"),
    datos: UploadFile = File(..., description="DATOS.txt"),
    pfx: UploadFile = File(..., description="Certificado .pfx"),
    caf_33: UploadFile = File(None, description="CAF Factura Electrónica (T33)"),
    caf_56: UploadFile = File(None, description="CAF Nota de Débito (T56)"),
    caf_61: UploadFile = File(None, description="CAF Nota de Crédito (T61)"),
    caf_52: UploadFile = File(None, description="CAF Guía de Despacho (T52)"),
    caf_46: UploadFile = File(None, description="CAF Factura de Compra (T46)"),
    folio_inicial_33: int = Form(None, description="Folio inicial T33 (opcional)"),
    folio_inicial_56: int = Form(None, description="Folio inicial T56 (opcional)"),
    folio_inicial_61: int = Form(None, description="Folio inicial T61 (opcional)"),
    folio_inicial_52: int = Form(None, description="Folio inicial T52 (opcional)"),
    folio_inicial_46: int = Form(None, description="Folio inicial T46 (opcional)"),
):
    """
    Flujo completo: recibe SIISetDePruebas + CAFs + certificado PFX,
    genera XMLs firmados, PDFs e informe de validación.
    """
    # Leer archivos
    try:
        set_txt = (await set_pruebas.read()).decode("iso-8859-1")
        datos_txt = (await datos.read()).decode("iso-8859-1")
        pfx_bytes = await pfx.read()
    except Exception as e:
        raise HTTPException(422, f"Error al leer archivos subidos: {e}")

    # Parsear DATOS.txt
    dat_lines = [l.strip() for l in datos_txt.splitlines() if l.strip()]
    if len(dat_lines) < 5:
        raise HTTPException(422, "DATOS.txt debe tener al menos 5 líneas: nombre, rut_rep, razon_social, rut_empresa, password_pfx [giro] [acteco] [dir_origen] [cmna_origen] [nro_resol] [fch_resol]")

    emisor_data = {
        "rut": dat_lines[3],
        "rut_envia": dat_lines[1],
        "razon_social": dat_lines[2],
        "giro": dat_lines[5] if len(dat_lines) > 5 else "ACTIVIDADES DE SERVICIOS",
        "acteco": dat_lines[6] if len(dat_lines) > 6 else "999999",
        "dir_origen": dat_lines[7] if len(dat_lines) > 7 else "",
        "cmna_origen": dat_lines[8] if len(dat_lines) > 8 else "",
        "unidad_sii": "",
        "nro_resol": dat_lines[9] if len(dat_lines) > 9 else "0",
        "fch_resol": dat_lines[10] if len(dat_lines) > 10 else datetime.now().strftime("%Y-%m-%d"),
    }
    pfx_password = dat_lines[4]

    # Cargar CAFs disponibles
    cafs: dict[int, CAF] = {}
    for tipo, upload in [(33, caf_33), (56, caf_56), (61, caf_61), (52, caf_52), (46, caf_46)]:
        if upload is not None:
            raw = await upload.read()
            if raw:
                try:
                    cafs[tipo] = CAF(raw)
                except Exception as e:
                    raise HTTPException(422, f"Error al leer CAF tipo {tipo}: {e}")
                if not emisor_data["rut"]:
                    emisor_data["rut"] = cafs[tipo].rut_emisor

    if not cafs:
        raise HTTPException(422, "Debe subir al menos un archivo CAF")

    # Parsear set de pruebas
    try:
        sp = parse_set_pruebas(set_txt)
    except Exception as e:
        raise HTTPException(422, f"Error al parsear SIISetDePruebas: {e}")

    # Verificar que tenemos CAF para cada tipo de documento requerido
    tipos_requeridos = {c.tipo_doc for c in sp.casos}
    faltantes = tipos_requeridos - set(cafs.keys())
    if faltantes:
        raise HTTPException(422, f"Faltan CAFs para tipos de documento: {sorted(faltantes)}")

    # Resolver items para NC/ND: copiar del caso referenciado o resolver precios
    import copy as _copy
    caso_by_num = {c.numero: c for c in sp.casos}

    # Retención total del IVA (cambio de sujeto): la lleva la Factura de Compra
    # (T46) y, por herencia, toda NC/ND que referencie (transitivamente) un T46.
    def _tiene_retencion(caso: CasoSet, _visto: set | None = None) -> bool:
        if caso.tipo_doc == 46:
            return True
        _visto = _visto or set()
        if not caso.referencia_caso or caso.referencia_caso in _visto:
            return False
        _visto.add(caso.referencia_caso)
        ref = caso_by_num.get(caso.referencia_caso)
        return _tiene_retencion(ref, _visto) if ref else False

    for caso in sp.casos:
        caso.con_retencion = _tiene_retencion(caso)

    for caso in sp.casos:
        if not caso.referencia_caso:
            continue
        ref = caso_by_num.get(caso.referencia_caso)
        if not ref:
            continue
        # NC tipo "Corrige Texto" (CodRef=2): NO debe tener montos — regla SII
        # REF-2-781. Fuerza precio_unitario=0 en los items del caso.
        if aplicar_regla_corrige_texto(caso):
            continue
        if not caso.items:
            # Sin items: copiar todos los items del caso referenciado
            caso.items = _copy.deepcopy(ref.items)
        else:
            # Items parciales con precio=0: resolver precio + descuento + exento
            # desde el caso referenciado. Sin esto, una NC que devuelve items de
            # una factura con descuento por línea (5%, 7%, ...) no aplica ese
            # descuento → "Los Valores de la Línea N No Cuadran" en el SII.
            ref_by_nombre = {it.nombre.upper(): it for it in ref.items}
            for item in caso.items:
                ref_it = ref_by_nombre.get(item.nombre.upper())
                if not ref_it:
                    continue
                if item.precio_unitario == 0:
                    item.precio_unitario = ref_it.precio_unitario
                if not item.descuento_pct and ref_it.descuento_pct:
                    item.descuento_pct = ref_it.descuento_pct
                if not item.es_exento and ref_it.es_exento:
                    item.es_exento = ref_it.es_exento
            # Heredar descuento global si el caso referenciado lo tenía
            if not caso.descuento_global_pct and ref.descuento_global_pct:
                caso.descuento_global_pct = ref.descuento_global_pct
        # Fallback final: si sigue sin items, crear item genérico
        if not caso.items:
            from set_parser import ItemSet as _ItemSet
            razon = caso.razon_referencia or "REFERENCIA"
            caso.items = [_ItemSet(nombre=razon[:80], cantidad=1, precio_unitario=0)]

    # Generar DTEs firmados
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    # Folio inicial por tipo. Pre-popula folios_usados con todos los previos
    # para saltarlos y arrancar desde el offset configurado.
    # Fuente de verdad: sets/pudu_78392059K/certificacion_final/RESUMEN_CERTIFICACION.md
    # (última certificación real aceptada por el SII, 2026-05-18). Actualizar este
    # valor manualmente después de cada envío real aceptado — no hay persistencia
    # automática de folios todavía (ver auditoría: esto es solo para RUT 78392059-K).
    FOLIO_START = {33: 38, 56: 11, 61: 29}
    # Override por request: permite fijar el folio inicial desde la interfaz
    # (ej. cuando un folio ya se usó en un envío previo y hay que saltarlo).
    _folio_overrides = {33: folio_inicial_33, 56: folio_inicial_56,
                        61: folio_inicial_61, 52: folio_inicial_52,
                        46: folio_inicial_46}
    for _t, _v in _folio_overrides.items():
        if _v is not None:
            FOLIO_START[_t] = _v
    # Validar que el folio inicial esté dentro del rango autorizado del CAF
    for _t in cafs:
        _start = FOLIO_START.get(_t, cafs[_t].desde)
        if not (cafs[_t].desde <= _start <= cafs[_t].hasta):
            raise HTTPException(
                422,
                f"Folio inicial {_start} para T{_t} fuera del rango autorizado "
                f"del CAF ({cafs[_t].desde}-{cafs[_t].hasta})."
            )
    folios_usados: dict[int, set] = {
        t: set(range(cafs[t].desde, FOLIO_START.get(t, cafs[t].desde)))
        for t in cafs
    }
    folios_ref: dict[str, int] = {}
    tipos_ref: dict[str, int] = {c.numero: c.tipo_doc for c in sp.casos}
    dtes_xml = []

    try:
        for caso in sp.casos:
            caf = cafs[caso.tipo_doc]
            folio = caf.next_folio(folios_usados[caso.tipo_doc])
            folios_usados[caso.tipo_doc].add(folio)
            folios_ref[caso.numero] = folio
            dte = build_dte_xml(caso, folio, emisor_data, RECEPTOR_PRUEBA,
                                caf, timestamp, folios_ref, tipos_ref)
            dtes_xml.append(dte)
    except Exception as e:
        raise HTTPException(500, f"Error generando DTEs: {e}")

    # Construir EnvioDTE firmado
    try:
        envio_xml = build_envio_dte(dtes_xml, emisor_data, pfx_bytes, pfx_password, timestamp)
    except Exception as e:
        raise HTTPException(500, f"Error firmando EnvioDTE: {e}")

    # Parsear el XML generado y producir PDFs
    try:
        dtes_parsed = parse_envio_dte(envio_xml)
    except Exception as e:
        raise HTTPException(500, f"Error releyendo XML generado: {e}")

    resultados = []
    zip_buf = io.BytesIO()

    rut_clean = emisor_data["rut"].replace("-", "")
    libro_ventas_ok = False
    libro_compras_ok = False

    out_dir = get_timestamped_output_dir(OUTPUT_BASE_DIR)

    def _save(filename: str, data) -> None:
        path = os.path.join(out_dir, filename)
        mode = "w" if isinstance(data, str) else "wb"
        enc = {"encoding": "utf-8"} if isinstance(data, str) else {}
        with open(path, mode, **enc) as fh:
            fh.write(data)

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # EnvioDTE XML
        zf.writestr(f"EnvioDTE_{rut_clean}.xml", envio_xml)
        _save(f"EnvioDTE_{rut_clean}.xml", envio_xml)

        # PDFs por cada DTE
        for dte in dtes_parsed:
            for cedible in ([False, True] if dte.tipo in CEDIBLE_TIPOS else [False]):
                suffix = "_CEDIBLE" if cedible else ""
                pdf_name = f"DTE_T{dte.tipo}F{dte.folio}{suffix}.pdf"
                pdf_bytes = generate_pdf(dte, cedible=cedible)
                zf.writestr(pdf_name, pdf_bytes)
                _save(pdf_name, pdf_bytes)

                val = validate_pdf(pdf_bytes, pdf_name)
                resultados.append({
                    "folio": dte.folio,
                    "tipo": dte.tipo,
                    "tipo_nombre": TIPO_NOMBRE.get(dte.tipo, f"Tipo {dte.tipo}"),
                    "cedible": cedible,
                    "archivo": pdf_name,
                    "validacion": {
                        "aprobado": val.passed,
                        "puntaje": val.score,
                        "checks": [{"nombre": c.name, "ok": c.passed, "detalle": c.detail}
                                   for c in val.checks],
                    },
                })

        # Libro de Ventas
        if sp.nro_atencion_ventas:
            try:
                lv_xml = build_libro_ventas(
                    sp.casos, folios_ref, RECEPTOR_PRUEBA, emisor_data,
                    pfx_bytes, pfx_password, timestamp, sp.nro_atencion_ventas,
                )
                zf.writestr(f"LibroVentas_{rut_clean}.xml", lv_xml)
                _save(f"LibroVentas_{rut_clean}.xml", lv_xml)
                libro_ventas_ok = True
            except Exception as e:
                raise HTTPException(500, f"Error generando Libro de Ventas: {e}")

        # Libro de Compras
        if sp.nro_atencion_compras and sp.libro_compras:
            try:
                lc_xml = build_libro_compras(
                    sp.libro_compras, emisor_data,
                    pfx_bytes, pfx_password, timestamp, sp.nro_atencion_compras,
                )
                zf.writestr(f"LibroCompras_{rut_clean}.xml", lc_xml)
                _save(f"LibroCompras_{rut_clean}.xml", lc_xml)
                libro_compras_ok = True
            except Exception as e:
                raise HTTPException(500, f"Error generando Libro de Compras: {e}")

    zip_buf.seek(0)
    zip_b64 = __import__("base64").b64encode(zip_buf.getvalue()).decode()

    aprobados = sum(1 for r in resultados if r["validacion"]["aprobado"])
    return JSONResponse({
        "nro_atencion": sp.nro_atencion_basico,
        "nro_atencion_ventas": sp.nro_atencion_ventas,
        "nro_atencion_compras": sp.nro_atencion_compras,
        "libro_ventas_generado": libro_ventas_ok,
        "libro_compras_generado": libro_compras_ok,
        "documentos": len(dtes_xml),
        "pdfs_generados": len(resultados),
        "aprobados": aprobados,
        "rechazados": len(resultados) - aprobados,
        "resultados": resultados,
        "zip_base64": zip_b64,
    })


@app.post("/procesar")
async def procesar_xml(file: UploadFile = File(...)):
    """
    Recibe un XML EnvioDTE, genera PDFs de cada DTE (con y sin cedible),
    los valida y retorna el resultado + un ZIP con los PDFs.
    """
    if not file.filename.lower().endswith(".xml"):
        raise HTTPException(400, "Solo se aceptan archivos XML")

    xml_bytes = await file.read()

    try:
        dtes = parse_envio_dte(xml_bytes)
    except Exception as e:
        raise HTTPException(422, f"Error al parsear XML: {str(e)}")

    if not dtes:
        raise HTTPException(422, "No se encontraron DTEs en el XML")

    resultados = []
    zip_buf = io.BytesIO()

    out_dir = get_timestamped_output_dir(OUTPUT_BASE_DIR)

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for dte in dtes:
            tipo_str = f"T{dte.tipo}"
            folio_str = f"F{dte.folio}"
            nombre_base = f"DTE_{tipo_str}{folio_str}"

            # Generar PDF tributario
            pdf_bytes = generate_pdf(dte, cedible=False)
            pdf_name = f"{nombre_base}.pdf"
            zf.writestr(pdf_name, pdf_bytes)
            with open(os.path.join(out_dir, pdf_name), "wb") as fh:
                fh.write(pdf_bytes)

            val = validate_pdf(pdf_bytes, pdf_name)
            doc_result = {
                "folio": dte.folio,
                "tipo": dte.tipo,
                "tipo_nombre": TIPO_NOMBRE.get(dte.tipo, f"Tipo {dte.tipo}"),
                "cedible": False,
                "archivo": pdf_name,
                "validacion": {
                    "aprobado": val.passed,
                    "puntaje": val.score,
                    "checks": [
                        {"nombre": c.name, "ok": c.passed, "detalle": c.detail}
                        for c in val.checks
                    ]
                }
            }
            resultados.append(doc_result)

            # Generar copia cedible si corresponde
            if dte.tipo in CEDIBLE_TIPOS:
                pdf_cedible = generate_pdf(dte, cedible=True)
                pdf_cedible_name = f"{nombre_base}_CEDIBLE.pdf"
                zf.writestr(pdf_cedible_name, pdf_cedible)
                with open(os.path.join(out_dir, pdf_cedible_name), "wb") as fh:
                    fh.write(pdf_cedible)

                val_ced = validate_pdf(pdf_cedible, pdf_cedible_name)
                resultados.append({
                    "folio": dte.folio,
                    "tipo": dte.tipo,
                    "tipo_nombre": TIPO_NOMBRE.get(dte.tipo, f"Tipo {dte.tipo}"),
                    "cedible": True,
                    "archivo": pdf_cedible_name,
                    "validacion": {
                        "aprobado": val_ced.passed,
                        "puntaje": val_ced.score,
                        "checks": [
                            {"nombre": c.name, "ok": c.passed, "detalle": c.detail}
                            for c in val_ced.checks
                        ]
                    }
                })

    zip_buf.seek(0)
    zip_b64 = __import__("base64").b64encode(zip_buf.getvalue()).decode()

    total = len(resultados)
    aprobados = sum(1 for r in resultados if r["validacion"]["aprobado"])

    return JSONResponse({
        "archivo_origen": file.filename,
        "documentos": len(dtes),
        "pdfs_generados": total,
        "aprobados": aprobados,
        "rechazados": total - aprobados,
        "resultados": resultados,
        "zip_base64": zip_b64,
    })


@app.post("/validar")
async def solo_validar(file: UploadFile = File(...)):
    """Valida un PDF ya existente sin regenerarlo."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Solo se aceptan archivos PDF")

    pdf_bytes = await file.read()
    val = validate_pdf(pdf_bytes, file.filename)

    return {
        "archivo": file.filename,
        "aprobado": val.passed,
        "puntaje": val.score,
        "checks": [
            {"nombre": c.name, "ok": c.passed, "detalle": c.detail}
            for c in val.checks
        ]
    }


# ─── ETAPA 2 — Simulación ────────────────────────────────────────────────────

@app.post("/etapa2")
async def etapa2_simulacion(
    datos:  UploadFile = File(..., description="DATOS.txt"),
    pfx:    UploadFile = File(..., description="Certificado .pfx/.p12"),
    caf_33: UploadFile = File(None, description="CAF Factura T33"),
    caf_61: UploadFile = File(None, description="CAF Nota de Crédito T61"),
    caf_56: UploadFile = File(None, description="CAF Nota de Débito T56"),
    caf_46: UploadFile = File(None, description="CAF Factura de Compra T46"),
    folio_33: int = Form(None, description="Folio T33 (opcional, usa el siguiente disponible)"),
    folio_61: int = Form(None, description="Folio T61 (opcional)"),
    folio_56: int = Form(None, description="Folio T56 (opcional)"),
    folio_46: int = Form(None, description="Folio T46 (opcional)"),
    producto: str = Form("Servicio tecnológico", description="Nombre del producto/servicio"),
    precio:   int = Form(35000, description="Precio unitario (sin IVA)"),
    modo:     str = Form("basico", description="Tipo de simulación: 'basico' (T33/T61/T56) o 'compra' (T46)"),
):
    """
    Etapa 2 — Genera EnvioDTE de Simulación según el modo:
      modo='basico' → T33 Factura, T61 NC (ref T33), T56 ND (anula NC)
      modo='compra' → T46 Factura de Compra con retención total del IVA
    """
    dat_lines = [(await datos.read()).decode("iso-8859-1", errors="replace").splitlines()]
    dat_lines = [l.strip() for l in dat_lines[0] if l.strip()]
    if len(dat_lines) < 5:
        raise HTTPException(422, "DATOS.txt debe tener al menos 5 líneas")

    emisor_data = {
        "rut":         dat_lines[3],
        "rut_envia":   dat_lines[1],
        "razon_social":dat_lines[2],
        "giro":        dat_lines[5] if len(dat_lines) > 5 else "ACTIVIDADES DE SERVICIOS",
        "acteco":      dat_lines[6] if len(dat_lines) > 6 else "999999",
        "dir_origen":  dat_lines[7] if len(dat_lines) > 7 else "",
        "cmna_origen": dat_lines[8] if len(dat_lines) > 8 else "",
        "nro_resol":   dat_lines[9] if len(dat_lines) > 9 else "0",
        "fch_resol":   dat_lines[10] if len(dat_lines) > 10 else datetime.now().strftime("%Y-%m-%d"),
    }
    pfx_password = dat_lines[4]
    pfx_bytes    = await pfx.read()

    async def _leer_caf(upload, etiqueta):
        raw = await upload.read() if upload is not None else None
        if not raw:
            return None
        try:
            return CAF(raw)
        except Exception as e:
            raise HTTPException(422, f"Error leyendo {etiqueta}: {e}")

    modo = (modo or "basico").lower()
    if modo not in ("basico", "compra"):
        raise HTTPException(422, f"Modo de simulación inválido: '{modo}' (usar 'basico' o 'compra')")

    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    folios_resp: dict[str, int] = {}

    if modo == "compra":
        # ── Simulación de Factura de Compra (T46) ──────────────────────────────
        caf46 = await _leer_caf(caf_46, "CAF T46")
        if not caf46:
            raise HTTPException(422, "La simulación de Factura de Compra requiere el CAF de T46.")
        f46 = folio_46 or caf46.desde

        caso_t46 = CasoSet(numero="SIM-1", tipo_doc=46,
                           items=[ItemSet(nombre=producto, cantidad=2, precio_unitario=precio)])
        caso_t46.con_retencion = True
        try:
            dte46 = build_dte_xml(caso_t46, f46, emisor_data, RECEPTOR_PRUEBA, caf46,
                                  timestamp, {"SIM-1": f46}, {"SIM-1": 46})
        except Exception as e:
            raise HTTPException(500, f"Error generando DTE de Factura de Compra: {e}")
        dtes_sim = [dte46]
        folios_resp = {"T46": f46}
    else:
        # ── Simulación Set Básico (T33 → T61 → T56) ────────────────────────────
        caf33 = await _leer_caf(caf_33, "CAF T33")
        caf61 = await _leer_caf(caf_61, "CAF T61")
        caf56 = await _leer_caf(caf_56, "CAF T56")
        faltan = [f"T{t}" for t, c in [(33, caf33), (61, caf61), (56, caf56)] if not c]
        if faltan:
            raise HTTPException(422, f"La simulación de Set Básico requiere los CAF: {', '.join(faltan)}.")
        f33 = folio_33 or caf33.desde
        f61 = folio_61 or caf61.desde
        f56 = folio_56 or caf56.desde

        caso_t33 = CasoSet(numero="SIM-1", tipo_doc=33,
                           items=[ItemSet(nombre=producto, cantidad=2, precio_unitario=precio)])
        caso_t61 = CasoSet(numero="SIM-2", tipo_doc=61,
                           items=[ItemSet(nombre=producto, cantidad=1, precio_unitario=precio)],
                           referencia_caso="SIM-1", razon_referencia="Devolucion mercaderia")
        caso_t56 = CasoSet(numero="SIM-3", tipo_doc=56,
                           items=[ItemSet(nombre=producto, cantidad=1, precio_unitario=precio)],
                           referencia_caso="SIM-2", razon_referencia="Anula nota de credito electronica")

        # Regla SII REF-2-781 (CodRef=2 "Corrige Texto" no debe tener montos), por
        # si alguna razón de referencia llegara a caer en ese código a futuro.
        aplicar_regla_corrige_texto(caso_t61)
        aplicar_regla_corrige_texto(caso_t56)

        folios_ref = {"SIM-1": f33, "SIM-2": f61}
        tipos_ref  = {"SIM-1": 33, "SIM-2": 61, "SIM-3": 56}
        try:
            dte33 = build_dte_xml(caso_t33, f33, emisor_data, RECEPTOR_PRUEBA, caf33, timestamp, folios_ref, tipos_ref)
            dte61 = build_dte_xml(caso_t61, f61, emisor_data, RECEPTOR_PRUEBA, caf61, timestamp, folios_ref, tipos_ref)
            dte56 = build_dte_xml(caso_t56, f56, emisor_data, RECEPTOR_PRUEBA, caf56, timestamp, folios_ref, tipos_ref)
        except Exception as e:
            raise HTTPException(500, f"Error generando DTEs simulación: {e}")
        dtes_sim = [dte33, dte61, dte56]
        folios_resp = {"T33": f33, "T61": f61, "T56": f56}

    try:
        envio_xml = build_envio_dte(dtes_sim, emisor_data, pfx_bytes, pfx_password, timestamp)
    except Exception as e:
        raise HTTPException(500, f"Error firmando EnvioDTE simulación: {e}")

    dtes_parsed = parse_envio_dte(envio_xml)
    rut_clean   = emisor_data["rut"].replace("-", "")
    out_dir     = get_timestamped_output_dir(OUTPUT_BASE_DIR, prefix="etapa2")
    resultados  = []
    zip_buf     = io.BytesIO()

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"EnvioDTE_{rut_clean}.xml", envio_xml)
        with open(os.path.join(out_dir, f"EnvioDTE_{rut_clean}.xml"), "wb") as fh:
            fh.write(envio_xml if isinstance(envio_xml, bytes) else envio_xml.encode())

        for dte in dtes_parsed:
            for cedible in ([False, True] if dte.tipo in CEDIBLE_TIPOS else [False]):
                suffix   = "_CEDIBLE" if cedible else ""
                pdf_name = f"DTE_T{dte.tipo}F{dte.folio}{suffix}.pdf"
                pdf_b    = generate_pdf(dte, cedible=cedible)
                zf.writestr(pdf_name, pdf_b)
                with open(os.path.join(out_dir, pdf_name), "wb") as fh:
                    fh.write(pdf_b)
                val = validate_pdf(pdf_b, pdf_name)
                resultados.append({
                    "folio": dte.folio, "tipo": dte.tipo,
                    "tipo_nombre": TIPO_NOMBRE.get(dte.tipo, f"Tipo {dte.tipo}"),
                    "cedible": cedible, "archivo": pdf_name,
                    "validacion": {"aprobado": val.passed, "puntaje": val.score,
                                   "checks": [{"nombre": c.name, "ok": c.passed, "detalle": c.detail} for c in val.checks]},
                })

    zip_buf.seek(0)
    zip_b64   = __import__("base64").b64encode(zip_buf.getvalue()).decode()
    aprobados = sum(1 for r in resultados if r["validacion"]["aprobado"])
    return JSONResponse({
        "modo": modo,
        "folios": folios_resp,
        "documentos": len(dtes_sim), "pdfs_generados": len(resultados),
        "aprobados": aprobados, "rechazados": len(resultados) - aprobados,
        "resultados": resultados, "zip_base64": zip_b64,
    })


# ─── ETAPA 3 — Intercambio ───────────────────────────────────────────────────

@app.post("/etapa3")
async def etapa3_intercambio(
    set_intercambio: UploadFile = File(..., description="ENVIO_DTE_*.xml recibido del SII"),
    pfx:             UploadFile = File(..., description="Certificado .pfx/.p12"),
    datos:           UploadFile = File(..., description="DATOS.txt"),
):
    """
    Etapa 3 — Genera los 3 XML de respuesta al SET de Intercambio del SII:
      1_RecepcionDTE.xml   — acuse de recepción
      2_EnvioRecibos.xml   — acuse de recibo de mercaderías
      3_ResultadoDTE.xml   — resultado comercial (acepta los nuestros, rechaza los ajenos)
    """
    from lxml import etree as _etree

    dat_lines = [(await datos.read()).decode("iso-8859-1", errors="replace").splitlines()]
    dat_lines = [l.strip() for l in dat_lines[0] if l.strip()]
    if len(dat_lines) < 5:
        raise HTTPException(422, "DATOS.txt debe tener al menos 5 líneas")

    dat = {
        "rut":       dat_lines[3],
        "rut_envia": dat_lines[1],
        "nombre":    dat_lines[0],
        "email":     "contacto@empresa.cl",
        "_pfx_pass": dat_lines[4],
    }
    pfx_bytes   = await pfx.read()
    set_xml_raw = await set_intercambio.read()
    orig_fname  = set_intercambio.filename or "ENVIO_DTE.xml"

    # Parsear el SET
    NS_SII = "http://www.sii.cl/SiiDte"
    NS_DS  = "http://www.w3.org/2000/09/xmldsig#"
    try:
        tree    = _etree.fromstring(set_xml_raw)
        set_dte = tree.find(f"{{{NS_SII}}}SetDTE")
        set_id  = set_dte.get("ID")

        digest = None
        for sig in tree.findall(f"{{{NS_DS}}}Signature"):
            for ref in sig.findall(f".//{{{NS_DS}}}Reference"):
                if ref.get("URI") == f"#{set_id}":
                    dv = ref.find(f"{{{NS_DS}}}DigestValue")
                    if dv is not None:
                        digest = dv.text.strip()

        dtes_set = []
        for dte_el in set_dte.findall(f"{{{NS_SII}}}DTE"):
            doc  = dte_el.find(f"{{{NS_SII}}}Documento")
            enc  = doc.find(f"{{{NS_SII}}}Encabezado")
            iddoc = enc.find(f"{{{NS_SII}}}IdDoc")
            tots  = enc.find(f"{{{NS_SII}}}Totales")
            rec   = enc.find(f"{{{NS_SII}}}Receptor")
            dtes_set.append({
                "tipo":       iddoc.findtext(f"{{{NS_SII}}}TipoDTE"),
                "folio":      iddoc.findtext(f"{{{NS_SII}}}Folio"),
                "fch_emis":   iddoc.findtext(f"{{{NS_SII}}}FchEmis"),
                "rut_emisor": enc.find(f"{{{NS_SII}}}Emisor").findtext(f"{{{NS_SII}}}RUTEmisor"),
                "rut_recep":  rec.findtext(f"{{{NS_SII}}}RUTRecep"),
                "mnt_total":  tots.findtext(f"{{{NS_SII}}}MntTotal"),
            })
    except Exception as e:
        raise HTTPException(422, f"Error al parsear SET de intercambio: {e}")

    m = _re.search(r'ENVIO_DTE_(\d+)', orig_fname, _re.IGNORECASE)
    nmbenvio    = f"ENVIO_DTE_{m.group(1)}.xml" if m else orig_fname
    rut_emisor_set = dtes_set[0]["rut_emisor"]
    ts          = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    def _build_recepcion():
        R = _etree.Element("RespuestaDTE", xmlns=NS_SII,
                           attrib={"{http://www.w3.org/2001/XMLSchema-instance}schemaLocation":
                                   "http://www.sii.cl/SiiDte RespuestaEnvioDTE_v10.xsd", "version": "1.0"})
        RES = _etree.SubElement(R, "Resultado", ID="LibreDTE_ResultadoEnvio")
        CAR = _etree.SubElement(RES, "Caratula", version="1.0")
        _etree.SubElement(CAR, "RutResponde").text  = dat["rut"]
        _etree.SubElement(CAR, "RutRecibe").text    = rut_emisor_set
        _etree.SubElement(CAR, "IdRespuesta").text  = "1"
        _etree.SubElement(CAR, "NroDetalles").text  = "1"
        _etree.SubElement(CAR, "NmbContacto").text  = dat["nombre"]
        _etree.SubElement(CAR, "MailContacto").text = dat["email"]
        _etree.SubElement(CAR, "TmstFirmaResp").text= ts
        RE = _etree.SubElement(RES, "RecepcionEnvio")
        _etree.SubElement(RE, "NmbEnvio").text      = nmbenvio
        _etree.SubElement(RE, "FchRecep").text      = ts
        _etree.SubElement(RE, "CodEnvio").text      = "1"
        _etree.SubElement(RE, "EnvioDTEID").text    = set_id
        _etree.SubElement(RE, "Digest").text        = digest or ""
        _etree.SubElement(RE, "RutEmisor").text     = rut_emisor_set
        _etree.SubElement(RE, "RutReceptor").text   = dat["rut"]
        _etree.SubElement(RE, "EstadoRecepEnv").text= "0"
        _etree.SubElement(RE, "RecepEnvGlosa").text = "Envio Recibido Conforme"
        _etree.SubElement(RE, "NroDTE").text        = str(len(dtes_set))
        for d in dtes_set:
            es_nuestro = d["rut_recep"] == dat["rut"]
            RD = _etree.SubElement(RE, "RecepcionDTE")
            _etree.SubElement(RD, "TipoDTE").text  = d["tipo"]
            _etree.SubElement(RD, "Folio").text    = d["folio"]
            _etree.SubElement(RD, "FchEmis").text  = d["fch_emis"]
            _etree.SubElement(RD, "RUTEmisor").text= d["rut_emisor"]
            _etree.SubElement(RD, "RUTRecep").text = d["rut_recep"]
            _etree.SubElement(RD, "MntTotal").text = d["mnt_total"]
            _etree.SubElement(RD, "EstadoRecepDTE").text = "0" if es_nuestro else "3"
            _etree.SubElement(RD, "RecepDTEGlosa").text  = "DTE Recibido OK" if es_nuestro else "DTE No Recibido - Error en RUT Receptor"
        return _etree.tostring(R, xml_declaration=True, encoding="ISO-8859-1", pretty_print=True)

    def _build_recibos():
        R = _etree.Element("EnvioRecibos", xmlns=NS_SII,
                           attrib={"{http://www.w3.org/2001/XMLSchema-instance}schemaLocation":
                                   "http://www.sii.cl/SiiDte EnvioRecibos_v10.xsd", "version": "1.0"})
        SET = _etree.SubElement(R, "SetRecibos", ID="LibreDTE_SetDteRecibidos")
        CAR = _etree.SubElement(SET, "Caratula", version="1.0")
        _etree.SubElement(CAR, "RutResponde").text  = dat["rut"]
        _etree.SubElement(CAR, "RutRecibe").text    = rut_emisor_set
        _etree.SubElement(CAR, "NmbContacto").text  = dat["nombre"]
        _etree.SubElement(CAR, "MailContacto").text = dat["email"]
        _etree.SubElement(CAR, "TmstFirmaEnv").text = ts
        decl = ("El acuse de recibo que se declara en este acto, de acuerdo a lo dispuesto "
                "en la letra b) del Art. 4, y la letra c) del Art. 5 de la Ley 19.983, "
                "acredita que la entrega de mercaderias o servicio(s) prestado(s) ha(n) sido recibido(s).")
        for d in dtes_set:
            REC = _etree.SubElement(SET, "Recibo", version="1.0")
            DR  = _etree.SubElement(REC, "DocumentoRecibo", ID=f"LibreDTE_T{d['tipo']}F{d['folio']}")
            _etree.SubElement(DR, "TipoDoc").text          = d["tipo"]
            _etree.SubElement(DR, "Folio").text            = d["folio"]
            _etree.SubElement(DR, "FchEmis").text          = d["fch_emis"]
            _etree.SubElement(DR, "RUTEmisor").text        = d["rut_emisor"]
            _etree.SubElement(DR, "RUTRecep").text         = d["rut_recep"]
            _etree.SubElement(DR, "MntTotal").text         = d["mnt_total"]
            _etree.SubElement(DR, "Recinto").text          = "Oficina central"
            _etree.SubElement(DR, "RutFirma").text         = dat["rut_envia"]
            _etree.SubElement(DR, "Declaracion").text      = decl
            _etree.SubElement(DR, "TmstFirmaRecibo").text  = ts
        return _etree.tostring(R, xml_declaration=True, encoding="ISO-8859-1", pretty_print=True)

    def _build_resultado():
        R = _etree.Element("RespuestaDTE", xmlns=NS_SII,
                           attrib={"{http://www.w3.org/2001/XMLSchema-instance}schemaLocation":
                                   "http://www.sii.cl/SiiDte RespuestaEnvioDTE_v10.xsd", "version": "1.0"})
        RES = _etree.SubElement(R, "Resultado", ID="LibreDTE_ResultadoEnvio")
        CAR = _etree.SubElement(RES, "Caratula", version="1.0")
        _etree.SubElement(CAR, "RutResponde").text  = dat["rut"]
        _etree.SubElement(CAR, "RutRecibe").text    = rut_emisor_set
        _etree.SubElement(CAR, "IdRespuesta").text  = "1"
        _etree.SubElement(CAR, "NroDetalles").text  = str(len(dtes_set))
        _etree.SubElement(CAR, "NmbContacto").text  = dat["nombre"]
        _etree.SubElement(CAR, "MailContacto").text = dat["email"]
        _etree.SubElement(CAR, "TmstFirmaResp").text= ts
        for i, d in enumerate(dtes_set, 1):
            es_nuestro = d["rut_recep"] == dat["rut"]
            RD = _etree.SubElement(RES, "ResultadoDTE")
            _etree.SubElement(RD, "TipoDTE").text      = d["tipo"]
            _etree.SubElement(RD, "Folio").text        = d["folio"]
            _etree.SubElement(RD, "FchEmis").text      = d["fch_emis"]
            _etree.SubElement(RD, "RUTEmisor").text    = d["rut_emisor"]
            _etree.SubElement(RD, "RUTRecep").text     = d["rut_recep"]
            _etree.SubElement(RD, "MntTotal").text     = d["mnt_total"]
            _etree.SubElement(RD, "CodEnvio").text     = str(i)
            _etree.SubElement(RD, "EstadoDTE").text    = "0" if es_nuestro else "2"
            _etree.SubElement(RD, "EstadoDTEGlosa").text = "ACEPTADO OK" if es_nuestro else "RECHAZADO"
        return _etree.tostring(R, xml_declaration=True, encoding="ISO-8859-1", pretty_print=True)

    def _firmar(js_script: str, xml_bytes: bytes, tmpdir: str, name: str) -> bytes:
        unsigned = os.path.join(tmpdir, f"{name}.unsigned.xml")
        signed   = os.path.join(tmpdir, f"{name}.xml")
        pfx_tmp  = os.path.join(tmpdir, "cert.pfx")
        with open(unsigned, "wb") as f: f.write(xml_bytes)
        with open(pfx_tmp,  "wb") as f: f.write(pfx_bytes)
        r = subprocess.run(
            ["node", js_script, unsigned, signed, pfx_tmp, dat["_pfx_pass"]],
            capture_output=True, text=True
        )
        if r.returncode != 0:
            raise RuntimeError(f"Firma fallida ({name}): {r.stderr}")
        with open(signed, "rb") as f:
            return f.read()

    out_dir = get_timestamped_output_dir(OUTPUT_BASE_DIR, prefix="etapa3")
    zip_buf = io.BytesIO()

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            xml1 = _firmar(_FIRMA_RESP,  _build_recepcion(), tmpdir, "1_RecepcionDTE")
            xml2 = _firmar(_FIRMA_RECIB, _build_recibos(),   tmpdir, "2_EnvioRecibos")
            xml3 = _firmar(_FIRMA_RESP,  _build_resultado(), tmpdir, "3_ResultadoDTE")
    except Exception as e:
        raise HTTPException(500, f"Error firmando respuestas: {e}")

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in [
            ("1_RecepcionDTE.xml", xml1),
            ("2_EnvioRecibos.xml", xml2),
            ("3_ResultadoDTE.xml", xml3),
        ]:
            zf.writestr(name, content)
            with open(os.path.join(out_dir, name), "wb") as fh:
                fh.write(content)

    zip_buf.seek(0)
    zip_b64 = __import__("base64").b64encode(zip_buf.getvalue()).decode()

    dte_info = [{"tipo": d["tipo"], "folio": d["folio"], "rut_recep": d["rut_recep"],
                 "monto": d["mnt_total"], "nuestro": d["rut_recep"] == dat["rut"]}
                for d in dtes_set]

    return JSONResponse({
        "set_id": set_id, "nmbenvio": nmbenvio,
        "dtes_en_set": len(dtes_set), "dte_info": dte_info,
        "archivos": ["1_RecepcionDTE.xml", "2_EnvioRecibos.xml", "3_ResultadoDTE.xml"],
        "zip_base64": zip_b64,
    })


# ─── ETAPA 4 — Muestras Impresas ─────────────────────────────────────────────

@app.post("/etapa4")
async def etapa4_muestras(
    envio_basico:      UploadFile = File(None, description="EnvioDTE Etapa 1 (Set Básico)"),
    envio_simulacion:  UploadFile = File(None, description="EnvioDTE Etapa 2 (Simulación)"),
):
    """
    Etapa 4 — Genera los PDFs de muestras impresas desde los EnvioDTE de Etapas 1 y 2.
    Sube los XML firmados y devuelve un ZIP con todos los PDFs listos para el portal SII.
    """
    sources = []
    for upload in [envio_basico, envio_simulacion]:
        if upload is not None:
            raw = await upload.read()
            if raw:
                sources.append((upload.filename or "envio.xml", raw))

    if not sources:
        raise HTTPException(422, "Sube al menos un EnvioDTE XML (Etapa 1 o Etapa 2)")

    out_dir    = get_timestamped_output_dir(OUTPUT_BASE_DIR, prefix="etapa4")
    resultados = []
    zip_buf    = io.BytesIO()

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, xml_bytes in sources:
            try:
                dtes = parse_envio_dte(xml_bytes)
            except Exception as e:
                raise HTTPException(422, f"Error al parsear {fname}: {e}")

            for dte in dtes:
                for cedible in ([False, True] if dte.tipo in CEDIBLE_TIPOS else [False]):
                    suffix   = "_CEDIBLE" if cedible else ""
                    pdf_name = f"DTE_T{dte.tipo}F{dte.folio}{suffix}.pdf"
                    pdf_b    = generate_pdf(dte, cedible=cedible)
                    zf.writestr(pdf_name, pdf_b)
                    with open(os.path.join(out_dir, pdf_name), "wb") as fh:
                        fh.write(pdf_b)
                    val = validate_pdf(pdf_b, pdf_name)
                    resultados.append({
                        "folio": dte.folio, "tipo": dte.tipo,
                        "tipo_nombre": TIPO_NOMBRE.get(dte.tipo, f"Tipo {dte.tipo}"),
                        "cedible": cedible, "archivo": pdf_name,
                        "origen": fname,
                        "validacion": {"aprobado": val.passed, "puntaje": val.score,
                                       "checks": [{"nombre": c.name, "ok": c.passed, "detalle": c.detail} for c in val.checks]},
                    })

    zip_buf.seek(0)
    zip_b64   = __import__("base64").b64encode(zip_buf.getvalue()).decode()
    aprobados = sum(1 for r in resultados if r["validacion"]["aprobado"])

    return JSONResponse({
        "xmls_procesados": len(sources),
        "pdfs_generados": len(resultados),
        "aprobados": aprobados,
        "rechazados": len(resultados) - aprobados,
        "resultados": resultados,
        "zip_base64": zip_b64,
    })

"""
API FastAPI: recibe SIISetDePruebas + CAFs + PFX, genera XMLs firmados, PDFs y los valida.
También acepta XMLs ya generados para re-procesar.
"""
import os
import zipfile
import io
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from parser import parse_envio_dte, TIPO_NOMBRE, CEDIBLE_TIPOS
from generator import generate_pdf
from validator import validate_pdf
from set_parser import parse_set_pruebas
from builders.envio_dte import CAF, build_dte_xml, build_envio_dte
from libro_builder import build_libro_ventas, build_libro_compras
from timestamped_output import get_timestamped_output_dir

OUTPUT_BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")

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
    for caso in sp.casos:
        if not caso.referencia_caso:
            continue
        ref = caso_by_num.get(caso.referencia_caso)
        if not ref:
            continue
        # NC tipo "Corrige Texto" (CodRef=2): NO copiar items con montos.
        # El SII rechaza con REF-2-781 si una NC con CodRef=2 tiene MntTotal>0.
        razon_upper = (caso.razon_referencia or "").upper()
        es_corrige_texto = (
            "CORRIGE" in razon_upper
            or "GIRO" in razon_upper
            or "RUBRO" in razon_upper
        ) and "ANULA" not in razon_upper and "DEVOLUCION" not in razon_upper and "DEVOLUCIÓN" not in razon_upper
        if es_corrige_texto:
            # Fuerza item único con monto cero (cae al fallback final)
            caso.items = []
        elif not caso.items:
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
    FOLIO_START = {33: 21, 56: 6, 61: 16}
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

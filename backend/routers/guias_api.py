"""Endpoints de Certificaciones Adicionales — Guía de Despacho (52).

  POST /adicionales/guias/set       Set de pruebas de guías → EnvioDTE firmado + PDFs (tributario y cedible según caso)
  POST /adicionales/guias/muestras  PDFs desde un EnvioDTE de guías ya aprobado
"""
import base64
import io
import os
import zipfile
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from builders.envio_dte import CAF, build_envio_dte
from generator_guias import generate_pdf_guia
from guias import build_guia_dte, parse_envio_guias, parse_set_guias
from timestamped_output import get_timestamped_output_dir
from validator import validate_pdf
from xsd_validator import validar_envio_dte

router = APIRouter(prefix="/adicionales/guias", tags=["adicionales"])


def _pdfs_y_zip(envio_xml: bytes, rut_clean: str, prefix: str):
    from main import OUTPUT_BASE_DIR
    out_dir = get_timestamped_output_dir(OUTPUT_BASE_DIR, prefix=prefix)
    resultados, zip_buf = [], io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"EnvioDTE_GUIAS_{rut_clean}.xml", envio_xml)
        with open(os.path.join(out_dir, f"EnvioDTE_GUIAS_{rut_clean}.xml"), "wb") as fh:
            fh.write(envio_xml)
        for g in parse_envio_guias(envio_xml):
            # Cedible solo si la operación constituye venta (instrucción del set del SII)
            for cedible in ([False, True] if g.es_venta else [False]):
                pdf_name = f"DTE_T52F{g.folio}{'_CEDIBLE' if cedible else ''}.pdf"
                pdf_b = generate_pdf_guia(g, cedible=cedible)
                zf.writestr(pdf_name, pdf_b)
                with open(os.path.join(out_dir, pdf_name), "wb") as fh:
                    fh.write(pdf_b)
                val = validate_pdf(pdf_b, pdf_name)
                resultados.append({
                    "folio": g.folio, "tipo": 52, "tipo_nombre": "GUÍA DE DESPACHO ELECTRÓNICA",
                    "cedible": cedible, "archivo": pdf_name, "caso": g.caso, "ind_traslado": g.ind_traslado,
                    "validacion": {"aprobado": val.passed, "puntaje": val.score,
                                   "checks": [{"nombre": c.name, "ok": c.passed, "detalle": c.detail} for c in val.checks]},
                })
    zip_buf.seek(0)
    return resultados, base64.b64encode(zip_buf.getvalue()).decode()


@router.post("/set")
async def guias_set(
    set_pruebas: UploadFile = File(..., description="SIISetDePruebas*.txt con SET GUIA DE DESPACHO"),
    datos: UploadFile = File(...),
    pfx: UploadFile = File(...),
    caf_52: UploadFile = File(...),
    folio_inicial_52: int = Form(None),
):
    from main import RECEPTOR_PRUEBA, _parse_datos
    emisor = _parse_datos(await datos.read())
    pfx_bytes = await pfx.read()
    try:
        sp = parse_set_guias((await set_pruebas.read()).decode("iso-8859-1"))
    except ValueError as e:
        raise HTTPException(422, str(e))
    raw = await caf_52.read()
    try:
        caf = CAF(raw)
    except Exception as e:
        raise HTTPException(422, f"Error leyendo CAF T52: {e}")
    if caf.tipo_doc != 52:
        raise HTTPException(422, f"El CAF subido es tipo {caf.tipo_doc}, se necesita 52")
    if caf.rut_emisor.upper() != emisor["rut"]:
        raise HTTPException(422, f"El CAF T52 pertenece al RUT {caf.rut_emisor}, DATOS.txt dice {emisor['rut']}")

    folio = folio_inicial_52 or caf.desde
    if not (caf.desde <= folio and folio + len(sp.casos) - 1 <= caf.hasta):
        raise HTTPException(422, f"Se necesitan {len(sp.casos)} folios desde {folio}; el CAF cubre {caf.desde}-{caf.hasta}")

    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    try:
        dtes = [build_guia_dte(c, folio + i, emisor, RECEPTOR_PRUEBA, caf, timestamp) for i, c in enumerate(sp.casos)]
        envio_xml = build_envio_dte(dtes, emisor, pfx_bytes, emisor["pfx_password"], timestamp)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(500, f"Error generando guías: {e}")
    errores = validar_envio_dte(envio_xml)
    if errores:
        raise HTTPException(500, "EnvioDTE de guías no cumple el XSD: " + " | ".join(errores[:5]))

    resultados, zip_b64 = _pdfs_y_zip(envio_xml, emisor["rut"].replace("-", ""), "guias")
    aprobados = sum(1 for r in resultados if r["validacion"]["aprobado"])
    return JSONResponse({
        "nro_atencion": sp.nro_atencion,
        "casos": [{"numero": c.numero, "folio": folio + i, "motivo": c.motivo, "ind_traslado": c.ind_traslado,
                   "tipo_despacho": c.tipo_despacho, "cedible": c.lleva_cedible} for i, c in enumerate(sp.casos)],
        "xsd_valido": True,
        "documentos": len(dtes), "pdfs_generados": len(resultados),
        "aprobados": aprobados, "rechazados": len(resultados) - aprobados,
        "resultados": resultados, "zip_base64": zip_b64,
    })


@router.post("/muestras")
async def guias_muestras(envio: UploadFile = File(...)):
    raw = await envio.read()
    try:
        docs = parse_envio_guias(raw)
    except Exception as e:
        raise HTTPException(422, f"No se pudo leer el EnvioDTE: {e}")
    if not docs:
        raise HTTPException(422, "El XML no contiene Guías de Despacho (52)")
    resultados, zip_b64 = _pdfs_y_zip(raw, docs[0].rut_emisor.replace("-", ""), "guias_muestras")
    aprobados = sum(1 for r in resultados if r["validacion"]["aprobado"])
    return JSONResponse({"documentos": len(docs), "pdfs_generados": len(resultados), "aprobados": aprobados,
                         "rechazados": len(resultados) - aprobados, "resultados": resultados, "zip_base64": zip_b64})

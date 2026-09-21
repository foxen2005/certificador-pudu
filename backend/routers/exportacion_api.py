"""Endpoints de Certificaciones Adicionales — Exportación (110/111/112).

Router independiente: no toca /certificar ni /etapa2-4. Comparte con ellos
solo `_parse_datos` (formato del DATOS.txt) y la carpeta de salida.

  POST /adicionales/exportacion/simulacion
      Genera T110 → T112 (anula) → T111 (anula NC) con datos de Aduana
      indicados por el usuario, firma el EnvioDTE, lo valida contra el XSD
      oficial y devuelve XML + PDFs (ZIP base64), igual que /etapa2.

  POST /adicionales/exportacion/muestras
      PDFs de muestra desde un EnvioDTE de exportación ya subido al SII.

  POST /adicionales/validar-xsd
      Valida cualquier EnvioDTE contra EnvioDTE_v10.xsd (útil para todos los tipos).
"""
import base64
import io
import os
import zipfile
from datetime import datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from builders.envio_dte import CAF
from exportacion import (
    MONEDAS, TIPO_NOMBRE_EXP, AduanaExp, ReceptorExp,
    build_envio_exportacion, build_exportacion_dte, docs_simulacion, parse_envio_exportacion,
)
from generator_exportacion import generate_pdf_exportacion
from timestamped_output import get_timestamped_output_dir
from validator import validate_pdf
from xsd_validator import validar_envio_dte

router = APIRouter(prefix="/adicionales", tags=["adicionales"])


def _dec(v: str | None, nombre: str, obligatorio: bool = False) -> Decimal | None:
    if v is None or str(v).strip() == "":
        if obligatorio:
            raise HTTPException(422, f"Falta {nombre}")
        return None
    try:
        return Decimal(str(v).replace(",", "."))
    except InvalidOperation:
        raise HTTPException(422, f"{nombre}: '{v}' no es un número")


async def _leer_caf(upload: UploadFile | None, tipo: int, rut_emisor: str) -> CAF:
    raw = await upload.read() if upload is not None else None
    if not raw:
        raise HTTPException(422, f"Falta el CAF T{tipo}")
    try:
        caf = CAF(raw)
    except Exception as e:
        raise HTTPException(422, f"Error leyendo CAF T{tipo}: {e}")
    if caf.tipo_doc != tipo:
        raise HTTPException(422, f"El archivo subido como CAF T{tipo} es tipo {caf.tipo_doc}")
    if caf.rut_emisor.upper() != rut_emisor:
        raise HTTPException(422, f"El CAF T{tipo} pertenece al RUT {caf.rut_emisor}, DATOS.txt dice {rut_emisor}")
    return caf


def _pdfs_y_zip(envio_xml: bytes, rut_clean: str, prefix: str):
    out_dir = get_timestamped_output_dir(_output_base(), prefix=prefix)
    resultados, zip_buf = [], io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"EnvioDTE_EXP_{rut_clean}.xml", envio_xml)
        with open(os.path.join(out_dir, f"EnvioDTE_EXP_{rut_clean}.xml"), "wb") as fh:
            fh.write(envio_xml)
        for dte in parse_envio_exportacion(envio_xml):
            pdf_name = f"DTE_T{dte.tipo}F{dte.folio}.pdf"
            pdf_b = generate_pdf_exportacion(dte)
            zf.writestr(pdf_name, pdf_b)
            with open(os.path.join(out_dir, pdf_name), "wb") as fh:
                fh.write(pdf_b)
            val = validate_pdf(pdf_b, pdf_name)
            resultados.append({
                "folio": dte.folio, "tipo": dte.tipo, "tipo_nombre": TIPO_NOMBRE_EXP.get(dte.tipo, f"Tipo {dte.tipo}"),
                "cedible": False, "archivo": pdf_name,
                "validacion": {"aprobado": val.passed, "puntaje": val.score,
                               "checks": [{"nombre": c.name, "ok": c.passed, "detalle": c.detail} for c in val.checks]},
            })
    zip_buf.seek(0)
    return resultados, base64.b64encode(zip_buf.getvalue()).decode()


def _output_base() -> str:
    from main import OUTPUT_BASE_DIR  # import tardío: evita ciclo main ↔ router
    return OUTPUT_BASE_DIR


@router.post("/exportacion/simulacion")
async def exportacion_simulacion(
    datos: UploadFile = File(...),
    pfx: UploadFile = File(...),
    caf_110: UploadFile = File(None),
    caf_111: UploadFile = File(None),
    caf_112: UploadFile = File(None),
    folio_110: int = Form(None),
    folio_111: int = Form(None),
    folio_112: int = Form(None),
    producto: str = Form("Producto de exportación"),
    cantidad: int = Form(100),
    precio: str = Form("10"),
    moneda: str = Form("DOLAR USA"),
    tipo_cambio: str = Form(...),
    receptor_razon: str = Form("IMPORTADOR EXTRANJERO"),
    receptor_direccion: str = Form(""),
    receptor_ciudad: str = Form(""),
    receptor_giro: str = Form(""),
    cod_pais_recep: str = Form(""),
    cod_mod_venta: str = Form("1"),
    cod_clau_venta: str = Form(""),
    cod_via_transp: str = Form(""),
    cod_pto_embarque: str = Form(""),
    cod_pto_desemb: str = Form(""),
    tot_bultos: str = Form(""),
    cod_tpo_bultos: str = Form(""),
    peso_bruto: str = Form(""),
    cod_unid_peso: str = Form("6"),
):
    from main import _parse_datos  # misma validación de DATOS.txt que el set básico
    emisor = _parse_datos(await datos.read())
    pfx_bytes = await pfx.read()
    if moneda not in MONEDAS:
        raise HTTPException(422, f"Moneda '{moneda}' no está en la tabla del SII. Válidas: {', '.join(MONEDAS)}")

    cafs = {t: await _leer_caf(u, t, emisor["rut"]) for t, u in [(110, caf_110), (111, caf_111), (112, caf_112)]}
    folios = {}
    for t, f in [(110, folio_110), (111, folio_111), (112, folio_112)]:
        folios[t] = f or cafs[t].desde
        if not (cafs[t].desde <= folios[t] <= cafs[t].hasta):
            raise HTTPException(422, f"Folio {folios[t]} para T{t} fuera del rango del CAF ({cafs[t].desde}-{cafs[t].hasta})")

    receptor = ReceptorExp(receptor_razon, receptor_direccion, receptor_ciudad, receptor_giro,
                           nacionalidad=cod_pais_recep)
    bultos = None
    if tot_bultos.strip():
        # XSD: TotBultos es xs:positiveInteger
        if not tot_bultos.strip().isdigit() or int(tot_bultos) < 1:
            raise HTTPException(422, f"Total de bultos: '{tot_bultos}' debe ser un entero ≥ 1")
        bultos = int(tot_bultos)
    aduana = AduanaExp(
        cod_mod_venta=cod_mod_venta, cod_clau_venta=cod_clau_venta, cod_via_transp=cod_via_transp,
        cod_pto_embarque=cod_pto_embarque, cod_pto_desemb=cod_pto_desemb,
        tot_bultos=bultos, cod_tpo_bultos=cod_tpo_bultos,
        peso_bruto=_dec(peso_bruto, "peso bruto"), cod_unid_peso=cod_unid_peso,
        cod_pais_recep=cod_pais_recep, cod_pais_destin=cod_pais_recep,
    )
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    docs = docs_simulacion(timestamp[:10], folios, producto, cantidad,
                           _dec(precio, "precio", True), moneda, _dec(tipo_cambio, "tipo de cambio", True),
                           receptor, aduana)
    try:
        dtes = [build_exportacion_dte(d, emisor, cafs[d.tipo], timestamp) for d in docs]
        envio_xml = build_envio_exportacion(dtes, emisor, pfx_bytes, emisor["pfx_password"], timestamp)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(500, f"Error generando exportación: {e}")

    resultados, zip_b64 = _pdfs_y_zip(envio_xml, emisor["rut"].replace("-", ""), "exportacion")
    aprobados = sum(1 for r in resultados if r["validacion"]["aprobado"])
    return JSONResponse({
        "folios": {f"T{t}": f for t, f in folios.items()},
        "xsd_valido": True,
        "documentos": len(dtes), "pdfs_generados": len(resultados),
        "aprobados": aprobados, "rechazados": len(resultados) - aprobados,
        "resultados": resultados, "zip_base64": zip_b64,
    })


@router.post("/exportacion/muestras")
async def exportacion_muestras(envio: UploadFile = File(...)):
    raw = await envio.read()
    if not raw:
        raise HTTPException(422, "Sube el EnvioDTE de exportación")
    try:
        docs = parse_envio_exportacion(raw)
    except Exception as e:
        raise HTTPException(422, f"No se pudo leer el EnvioDTE: {e}")
    if not docs:
        raise HTTPException(422, "El XML no contiene documentos <Exportaciones> (110/111/112)")
    rut_clean = docs[0].rut_emisor.replace("-", "")
    resultados, zip_b64 = _pdfs_y_zip(raw, rut_clean, "exportacion_muestras")
    aprobados = sum(1 for r in resultados if r["validacion"]["aprobado"])
    return JSONResponse({
        "documentos": len(docs), "pdfs_generados": len(resultados),
        "aprobados": aprobados, "rechazados": len(resultados) - aprobados,
        "resultados": resultados, "zip_base64": zip_b64,
    })


@router.post("/validar-xsd")
async def validar_xsd(envio: UploadFile = File(...)):
    raw = await envio.read()
    errores = validar_envio_dte(raw)
    return {"archivo": envio.filename, "valido": not errores, "errores": errores}

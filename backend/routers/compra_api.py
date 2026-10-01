"""Endpoints de Certificaciones Adicionales — Factura de Compra (T46).

Antes la Factura de Compra vivía dentro del wizard principal (CAF T46 en la
configuración, casos T46 mezclados en el EnvioDTE del set básico y modo
"compra" en la Etapa 2). Se separa porque el SII la certifica con su propio set
y en su propio envío. NO hay lógica nueva de DTE: los dos endpoints delegan en
el mismo código de main.py que ya generaba el T46 (retención total del IVA,
NC/ND encadenadas, PDFs).

  POST /adicionales/compra/set
      Del SIISetDePruebas*.txt genera SOLO la cadena de Factura de Compra
      (T46 + NC/ND que la referencian), en un EnvioDTE aparte, con PDFs y ZIP.
      Sin libros: el Libro de Compras es parte del set básico.

  POST /adicionales/compra/simulacion
      Etapa 2 de la Factura de Compra: T46 → NC T61 → ND T56 con retención
      total del IVA (lo mismo que /etapa2 con modo="compra").
"""
from fastapi import APIRouter, File, Form, UploadFile

router = APIRouter(prefix="/adicionales", tags=["adicionales"])


@router.post("/compra/set")
async def compra_set(
    set_pruebas: UploadFile = File(..., description="SIISetDePruebas*.txt con los casos de Factura de Compra"),
    datos: UploadFile = File(...),
    pfx: UploadFile = File(...),
    caf_46: UploadFile = File(None, description="CAF Factura de Compra (T46)"),
    caf_61: UploadFile = File(None, description="CAF Nota de Crédito (T61)"),
    caf_56: UploadFile = File(None, description="CAF Nota de Débito (T56)"),
    folio_46: int = Form(None),
    folio_61: int = Form(None),
    folio_56: int = Form(None),
):
    from fastapi import HTTPException
    from main import _certificar_core  # import tardío: evita ciclo main ↔ router
    # Los CAF T61/T56 son los mismos del set básico, que ya consumió sus primeros
    # folios: sin folio explícito el SII rechazaría con DTE-3-100 (folio repetido).
    faltan = [f"T{t}" for t, folio in ((61, folio_61), (56, folio_56)) if folio is None]
    if faltan:
        raise HTTPException(422, f"Indica el folio inicial de {' y '.join(faltan)}: esos CAF son los del set básico "
                                 "y sus primeros folios ya se usaron ahí.")
    return await _certificar_core(
        set_pruebas, datos, pfx,
        {46: caf_46, 61: caf_61, 56: caf_56},
        {46: folio_46, 61: folio_61, 56: folio_56},
        solo="compra",
    )


@router.post("/compra/simulacion")
async def compra_simulacion(
    datos: UploadFile = File(...),
    pfx: UploadFile = File(...),
    caf_46: UploadFile = File(None),
    caf_61: UploadFile = File(None),
    caf_56: UploadFile = File(None),
    folio_46: int = Form(None),
    folio_61: int = Form(None),
    folio_56: int = Form(None),
    producto: str = Form(None),
    precio: int = Form(None),
):
    from main import SIM_PRECIO_DEFECTO, SIM_PRODUCTO_DEFECTO, etapa2_simulacion
    return await etapa2_simulacion(
        datos=datos, pfx=pfx,
        caf_33=None, caf_61=caf_61, caf_56=caf_56, caf_46=caf_46,
        folio_33=None, folio_61=folio_61, folio_56=folio_56, folio_46=folio_46,
        producto=producto or SIM_PRODUCTO_DEFECTO, precio=precio or SIM_PRECIO_DEFECTO, modo="compra",
    )


@router.get("/compra/simulacion/defaults")
def compra_simulacion_defaults():
    """Datos precargados de la simulación (los mismos de la Etapa 2 básica) y el
    receptor de prueba, para que la web no los duplique."""
    from main import RECEPTOR_PRUEBA, SIM_CANTIDAD_DEFECTO, SIM_PRECIO_DEFECTO, SIM_PRODUCTO_DEFECTO, TASA_IVA
    return {"producto": SIM_PRODUCTO_DEFECTO, "precio": SIM_PRECIO_DEFECTO, "cantidad": SIM_CANTIDAD_DEFECTO,
            "tasa_iva": TASA_IVA, "receptor": RECEPTOR_PRUEBA}

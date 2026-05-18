"""
Genera XMLs de Libro Electrónico de Ventas y Compras para el Set de Pruebas SII.
Esquema: LibroCV_v10.xsd  (http://www.sii.cl/SiiDte)
"""
from collections import defaultdict
from lxml import etree

from set_parser import CasoSet, LibroCompraItem
from dte_builder import calc_totales
from builders.common import sign_via_pudu

NS_LCV = "http://www.sii.cl/SiiDte"

# Tipos que van en libro de ventas
_VENTAS_TIPOS = {33, 34, 52, 56, 61, 43, 46}
# Notas de Crédito invierten el signo en el libro
_NC_TIPOS = {61}

# Para libros ESPECIAL de certificación: usar periodo pre-RCV (RCV reemplaza
# libros a partir de 2017-08). Si se usa periodo actual, el SII rechaza con
# "CRT-3 Periodo invalido". FchResol/NroResol también deben ser pre-RCV.
LIBRO_PERIODO_VENTAS = "2000-01"
LIBRO_PERIODO_COMPRAS = "2000-01"
LIBRO_FCHDOC_VENTAS = "2000-01-01"
LIBRO_FCHDOC_COMPRAS = "2000-01-01"
LIBRO_FCHRESOL = "2014-08-22"
LIBRO_NRORESOL = "0"


# ─── Formateo del árbol ───────────────────────────────────────────────────────

def _add_newlines(el: etree._Element) -> None:
    """Agrega \\n entre elementos hijos antes de calcular C14N."""
    if len(el) > 0:
        el.text = "\n"
        for child in el:
            child.tail = "\n"
            _add_newlines(child)


def _sign_libro_via_pudu(unsigned_xml: bytes, envio_id: str,
                         pfx_bytes: bytes, pfx_password: str) -> bytes:
    """Firma un libro usando sign_via_pudu (Node.js / xml-crypto del PUDU server)."""
    return sign_via_pudu(
        unsigned_xml, pfx_bytes, pfx_password,
        [{
            "ref_id": envio_id,
            "location_xpath": "//*[local-name()='LibroCompraVenta']",
        }],
    )


def _make_root(envio_id: str, schema_file: str) -> tuple[etree._Element, etree._Element]:
    """Crea la raíz LibroCompraVenta y el EnvioLibro. Retorna (root, envio)."""
    ROOT = etree.Element(
        "LibroCompraVenta",
        xmlns=NS_LCV,
        attrib={
            "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation":
                f"http://www.sii.cl/SiiDte {schema_file}",
            "version": "1.0",
        },
    )
    ENVIO = etree.SubElement(ROOT, "EnvioLibro", ID=envio_id)
    return ROOT, ENVIO


def _add_caratula(envio_el: etree._Element, emisor_data: dict, tipo_op: str,
                  periodo: str, nro_atencion: str) -> None:
    CAR = etree.SubElement(envio_el, "Caratula")
    etree.SubElement(CAR, "RutEmisorLibro").text = emisor_data["rut"]
    etree.SubElement(CAR, "RutEnvia").text = emisor_data["rut_envia"]
    etree.SubElement(CAR, "PeriodoTributario").text = periodo
    # FchResol/NroResol DEBEN coincidir con lo que el SII tiene registrado para
    # este contribuyente (mismos valores que el EnvioDTE, ya aceptado).
    # Defaults pre-RCV (102006/2006, 0/2014-08-22) fueron rechazados por SII.
    etree.SubElement(CAR, "FchResol").text = emisor_data.get("fch_resol", "2014-08-22")
    etree.SubElement(CAR, "NroResol").text = emisor_data.get("nro_resol", "0")
    etree.SubElement(CAR, "TipoOperacion").text = tipo_op
    etree.SubElement(CAR, "TipoLibro").text = "ESPECIAL"
    etree.SubElement(CAR, "TipoEnvio").text = "TOTAL"
    etree.SubElement(CAR, "FolioNotificacion").text = nro_atencion


def _add_resumen(envio_el: etree._Element,
                 totales: dict[int, dict]) -> None:
    RESUMEN = etree.SubElement(envio_el, "ResumenPeriodo")
    for tipo, t in sorted(totales.items()):
        TOT = etree.SubElement(RESUMEN, "TotalesPeriodo")
        etree.SubElement(TOT, "TpoDoc").text = str(tipo)
        etree.SubElement(TOT, "TotDoc").text = str(t["count"])
        # El schema LibroCV_v10 exige TotMntExe → TotMntNeto → TotMntIVA siempre
        # presentes (aunque sean 0) antes de TotMntTotal.
        etree.SubElement(TOT, "TotMntExe").text = str(t["exento"])
        etree.SubElement(TOT, "TotMntNeto").text = str(t["neto"])
        etree.SubElement(TOT, "TotMntIVA").text = str(t["iva"])
        # IVA Uso Común (ej. T30 "FACTURA CON IVA USO COMUN")
        if t.get("iva_uso_comun"):
            etree.SubElement(TOT, "TotIVAUsoComun").text = str(t["iva_uso_comun"])
            fct = t.get("fct_prop")
            if fct is not None:
                etree.SubElement(TOT, "FctProp").text = str(fct)
                etree.SubElement(TOT, "TotCredIVAUsoComun").text = str(round(t["iva_uso_comun"] * fct))
        # IVA No Recuperable (ej. T33 "ENTREGA GRATUITA DEL PROVEEDOR")
        if t.get("iva_no_rec_mnt"):
            IVANR = etree.SubElement(TOT, "TotIVANoRec")
            etree.SubElement(IVANR, "CodIVANoRec").text = str(t["iva_no_rec_cod"])
            etree.SubElement(IVANR, "TotOpIVANoRec").text = str(t["iva_no_rec_ops"])
            etree.SubElement(IVANR, "TotMntIVANoRec").text = str(t["iva_no_rec_mnt"])
        # Otros Impuestos (T46: CodImp=15 retención total IVA)
        if t.get("otros_imp_mnt"):
            OTRIMP = etree.SubElement(TOT, "TotOtrosImp")
            etree.SubElement(OTRIMP, "CodImp").text = str(t["otros_imp_cod"])
            etree.SubElement(OTRIMP, "TotMntImp").text = str(t["otros_imp_mnt"])
        # TotIVARetTotal: T46 retención total del IVA
        if t.get("iva_ret"):
            etree.SubElement(TOT, "TotIVARetTotal").text = str(t["iva_ret"])
        etree.SubElement(TOT, "TotMntTotal").text = str(t["total"])


def _add_detalle(envio_el: etree._Element, d: dict) -> None:
    iva_uso_comun = d.get("iva_uso_comun", 0)
    iva_no_rec    = d.get("iva_no_rec")    # (cod, mnt) o None
    otros_imp     = d.get("otros_imp")     # (cod_imp, tasa_imp, mnt_imp) o None
    iva_val       = d.get("iva") or 0
    # IVARetTotal: explícito en el dict o implícito para T46 con IVA (backward compat)
    iva_ret_total = d.get("iva_ret_total") or (d["tipo"] == 46 and iva_val) or 0
    mnt_total     = d["total"]

    DET = etree.SubElement(envio_el, "Detalle")
    etree.SubElement(DET, "TpoDoc").text = str(d["tipo"])
    etree.SubElement(DET, "NroDoc").text = str(d["folio"])
    etree.SubElement(DET, "TpoImp").text = "1"
    etree.SubElement(DET, "TasaImp").text = "19" if (d.get("neto") or iva_uso_comun or iva_no_rec or iva_val) else "0"
    etree.SubElement(DET, "FchDoc").text = d["fecha"]
    etree.SubElement(DET, "RUTDoc").text = d["rut_doc"]
    if d.get("razon_social"):
        etree.SubElement(DET, "RznSoc").text = d["razon_social"][:50]
    etree.SubElement(DET, "MntExe").text = str(d.get("exento") or 0)
    if d.get("neto"):
        etree.SubElement(DET, "MntNeto").text = str(d["neto"])
    # MntIVA + campos especiales de IVA (mutuamente excluyentes)
    if iva_uso_comun:
        # IVA Uso Común: MntIVA=0 explícito, luego IVAUsoComun con el monto real
        etree.SubElement(DET, "MntIVA").text = "0"
        etree.SubElement(DET, "IVAUsoComun").text = str(iva_uso_comun)
    elif iva_no_rec:
        # IVA No Recuperable: MntIVA=0 explícito, luego bloque IVANoRec
        etree.SubElement(DET, "MntIVA").text = "0"
        IVA_NR = etree.SubElement(DET, "IVANoRec")
        etree.SubElement(IVA_NR, "CodIVANoRec").text = str(iva_no_rec[0])
        etree.SubElement(IVA_NR, "MntIVANoRec").text = str(iva_no_rec[1])
    elif iva_val:
        etree.SubElement(DET, "MntIVA").text = str(iva_val)
    # OtrosImp (T46 CodImp=15) va ANTES de IVARetTotal
    if otros_imp:
        OI = etree.SubElement(DET, "OtrosImp")
        etree.SubElement(OI, "CodImp").text = str(otros_imp[0])
        etree.SubElement(OI, "TasaImp").text = str(otros_imp[1])
        etree.SubElement(OI, "MntImp").text = str(otros_imp[2])
    if iva_ret_total:
        etree.SubElement(DET, "IVARetTotal").text = str(iva_ret_total)
    etree.SubElement(DET, "MntTotal").text = str(mnt_total)


# ─── Libro de Ventas ──────────────────────────────────────────────────────────

def build_unsigned_libro_ventas(
    casos: list[CasoSet],
    folios_ref: dict[str, int],
    receptor: dict,
    emisor_data: dict,
    timestamp: str,
    nro_atencion: str,
) -> bytes:
    """Genera LibroVentas XML SIN firma. El firmado lo hace Node.js/signer.js."""
    fecha = timestamp[:10]
    periodo = fecha[:7]
    envio_id = "LibroVentas"

    ROOT, ENVIO = _make_root(envio_id, "LibroCV_v10.xsd")
    _add_caratula(ENVIO, emisor_data, "VENTA", periodo, nro_atencion)

    totales: dict[int, dict] = defaultdict(lambda: {"count": 0, "neto": 0, "iva": 0, "exento": 0, "total": 0})
    detalles = []

    for caso in casos:
        if caso.tipo_doc not in _VENTAS_TIPOS:
            continue
        folio = folios_ref.get(caso.numero, 1)
        tots = calc_totales(caso.items, caso.descuento_global_pct)

        neto = tots["neto"] or 0
        iva = tots["iva"] or 0
        exento = tots["exento"] or 0
        total = tots["total"] or 0

        # En LibroVentas todos los Detalle usan montos positivos — el TpoDoc
        # indica si es crédito (61) o débito (56). Montos negativos en Detalle
        # solo son válidos para Liquidaciones (TpoDoc 40/43/103) → LBR-2.
        t = totales[caso.tipo_doc]
        t["count"] += 1
        t["neto"] += neto
        t["iva"] += iva
        t["exento"] += exento
        t["total"] += total

        detalles.append({
            "tipo": caso.tipo_doc, "folio": folio, "fecha": fecha,
            "rut_doc": receptor["rut"], "razon_social": receptor["razon_social"],
            "neto": neto, "iva": iva, "exento": exento, "total": total,
        })

    _add_resumen(ENVIO, totales)
    for d in detalles:
        _add_detalle(ENVIO, d)
    etree.SubElement(ENVIO, "TmstFirma").text = timestamp

    _add_newlines(ROOT)
    xml_bytes = etree.tostring(ROOT, xml_declaration=True, encoding="ISO-8859-1")
    return xml_bytes.replace(
        b"<?xml version='1.0' encoding='ISO-8859-1'?>",
        b'<?xml version="1.0" encoding="ISO-8859-1"?>'
    )


def build_unsigned_libro_compras(
    items: list[LibroCompraItem],
    emisor_data: dict,
    timestamp: str,
    nro_atencion: str,
    fct_prop: float = 0.6,
) -> bytes:
    """Genera LibroCompras XML SIN firma. El firmado lo hace Node.js/signer.js."""
    fecha = timestamp[:10]
    periodo = fecha[:7]
    envio_id = "LibroCompras"

    ROOT, ENVIO = _make_root(envio_id, "LibroCV_v10.xsd")
    _add_caratula(ENVIO, emisor_data, "COMPRA", periodo, nro_atencion)

    totales: dict[int, dict] = defaultdict(lambda: {
        "count": 0, "neto": 0, "iva": 0, "exento": 0, "total": 0,
        "iva_ret": 0,
        "iva_uso_comun": 0, "fct_prop": None,
        "iva_no_rec_cod": None, "iva_no_rec_ops": 0, "iva_no_rec_mnt": 0,
        "otros_imp_cod": None, "otros_imp_mnt": 0,
    })
    detalles = []

    for item in items:
        tipo_cod = _TIPO_NOMBRE_COD.get(item.tipo_doc.upper())
        if tipo_cod is None:
            continue

        neto    = item.monto_afecto or 0
        exento  = item.monto_exento or 0
        iva_raw = item.monto_iva if item.monto_iva is not None else round(neto * 0.19)

        obs = (item.observacion or "").upper()
        iva_uso_comun = 0
        iva_no_rec    = None   # (cod, mnt)
        otros_imp     = None   # (cod_imp, tasa_imp, mnt_imp)
        iva_ret_total = 0
        iva = iva_raw  # valor que irá a MntIVA (0 para casos especiales)

        if "IVA USO COMUN" in obs or "USO COMUN" in obs:
            # IVA uso común: MntIVA=0, IVAUsoComun lleva el monto real
            iva_uso_comun = iva_raw
            iva = 0
        elif "ENTREGA GRATUITA" in obs:
            # IVA no recuperable CodRef=4 (actividad exenta/gratuita del proveedor)
            iva_no_rec = (4, iva_raw)
            iva = 0
        elif tipo_cod == 46:
            # Factura de Compra con retención total: OtrosImp CodImp=15 + IVARetTotal
            otros_imp     = (15, 19, iva_raw)
            iva_ret_total = iva_raw

        # T46: el proveedor solo recibe el neto (comprador retiene y paga el IVA al SII)
        if tipo_cod == 46:
            total = neto
        elif item.monto_total is not None:
            total = item.monto_total
        else:
            total = neto + iva_raw + exento

        t = totales[tipo_cod]
        t["count"] += 1
        t["neto"]   += neto
        t["iva"]    += iva         # solo IVA regular (0 para uso_comun/no_rec)
        t["exento"] += exento
        t["total"]  += total

        if iva_uso_comun:
            t["iva_uso_comun"] += iva_uso_comun
            t["fct_prop"] = fct_prop
        if iva_no_rec:
            t["iva_no_rec_cod"] = iva_no_rec[0]
            t["iva_no_rec_ops"] += 1
            t["iva_no_rec_mnt"] += iva_no_rec[1]
        if otros_imp:
            t["otros_imp_cod"] = otros_imp[0]
            t["otros_imp_mnt"] += otros_imp[2]
        if iva_ret_total:
            t["iva_ret"] = t.get("iva_ret", 0) + iva_ret_total

        detalles.append({
            "tipo": tipo_cod, "folio": item.folio,
            "fecha": item.fecha or fecha,
            "rut_doc": item.rut_emisor or "00000000-0",
            "razon_social": item.razon_social or "",
            "neto": neto, "iva": iva, "exento": exento, "total": total,
            "iva_uso_comun": iva_uso_comun,
            "iva_no_rec":    iva_no_rec,
            "otros_imp":     otros_imp,
            "iva_ret_total": iva_ret_total,
        })

    _add_resumen(ENVIO, totales)
    for d in detalles:
        _add_detalle(ENVIO, d)
    etree.SubElement(ENVIO, "TmstFirma").text = timestamp

    _add_newlines(ROOT)
    xml_bytes = etree.tostring(ROOT, xml_declaration=True, encoding="ISO-8859-1")
    return xml_bytes.replace(
        b"<?xml version='1.0' encoding='ISO-8859-1'?>",
        b'<?xml version="1.0" encoding="ISO-8859-1"?>'
    )


_TIPO_NOMBRE_COD = {
    # Documentos electrónicos
    "FACTURA ELECTRONICA": 33,
    "FACTURA DE COMPRA ELECTRONICA": 46,
    "NOTA DE CREDITO ELECTRONICA": 61,
    "NOTA DE DEBITO ELECTRONICA": 56,
    "GUIA DE DESPACHO ELECTRONICA": 52,
    "LIQUIDACION FACTURA ELECTRONICA": 43,
    # Documentos en papel (sin ELECTRONICA) — códigos diferentes según SII
    "FACTURA": 30,
    "FACTURA DE COMPRA": 45,
    "NOTA DE CREDITO": 60,
    "NOTA DE DEBITO": 55,
    "GUIA DE DESPACHO": 50,
}


def build_libro_ventas(
    casos: list[CasoSet],
    folios_ref: dict[str, int],
    receptor: dict,
    emisor_data: dict,
    pfx_bytes: bytes,
    pfx_password: str,
    timestamp: str,
    nro_atencion: str,
) -> bytes:
    """Genera LibroVentas XML firmado para el Set de Pruebas SII."""
    fecha = LIBRO_FCHDOC_VENTAS  # FchDoc en detalles debe estar dentro del periodo
    periodo = LIBRO_PERIODO_VENTAS
    envio_id = "LibroVentas"

    ROOT, ENVIO = _make_root(envio_id, "LibroCV_v10.xsd")
    _add_caratula(ENVIO, emisor_data, "VENTA", periodo, nro_atencion)

    totales: dict[int, dict] = defaultdict(lambda: {"count": 0, "neto": 0, "iva": 0, "exento": 0, "total": 0})
    detalles = []

    for caso in casos:
        if caso.tipo_doc not in _VENTAS_TIPOS:
            continue
        folio = folios_ref.get(caso.numero, 1)
        tots = calc_totales(caso.items, caso.descuento_global_pct)

        neto = tots["neto"] or 0
        iva = tots["iva"] or 0
        exento = tots["exento"] or 0
        total = tots["total"] or 0

        # ResumenPeriodo acumula valores absolutos (positivos) para todos los tipos,
        # incluidas NCs. El SII espera positivos en TotalesPeriodo.
        t = totales[caso.tipo_doc]
        t["count"] += 1
        t["neto"] += neto
        t["iva"] += iva
        t["exento"] += exento
        t["total"] += total

        # Detalle usa signo negativo para NC (representa reducción de débito fiscal)
        if caso.tipo_doc in _NC_TIPOS:
            neto, iva, exento, total = -neto, -iva, -exento, -total

        detalles.append({
            "tipo": caso.tipo_doc,
            "folio": folio,
            "fecha": fecha,
            "rut_doc": receptor["rut"],
            "razon_social": receptor["razon_social"],
            "neto": neto,
            "iva": iva,
            "exento": exento,
            "total": total,
        })

    _add_resumen(ENVIO, totales)
    for d in detalles:
        _add_detalle(ENVIO, d)

    etree.SubElement(ENVIO, "TmstFirma").text = timestamp

    _add_newlines(ROOT)
    unsigned_xml = etree.tostring(ROOT, xml_declaration=True, encoding="ISO-8859-1")
    unsigned_xml = unsigned_xml.replace(
        b"<?xml version='1.0' encoding='ISO-8859-1'?>",
        b'<?xml version="1.0" encoding="ISO-8859-1"?>'
    )

    return _sign_libro_via_pudu(unsigned_xml, envio_id, pfx_bytes, pfx_password)


# ─── Libro de Compras ─────────────────────────────────────────────────────────


def build_libro_compras(
    items: list[LibroCompraItem],
    emisor_data: dict,
    pfx_bytes: bytes,
    pfx_password: str,
    timestamp: str,
    nro_atencion: str,
    fct_prop: float = 0.6,
) -> bytes:
    """Genera LibroCompras XML firmado para el Set de Pruebas SII."""
    fecha = LIBRO_FCHDOC_COMPRAS
    periodo = LIBRO_PERIODO_COMPRAS
    envio_id = "LibroCompras"

    unsigned_xml = build_unsigned_libro_compras(
        items, emisor_data, timestamp, nro_atencion, fct_prop=fct_prop
    )
    return _sign_libro_via_pudu(unsigned_xml, envio_id, pfx_bytes, pfx_password)

"""
Parsea XMLs EnvioDTE del SII y extrae los DTEs individuales.
Formato: ISO-8859-1, namespace http://www.sii.cl/SiiDte
"""
from lxml import etree
from dataclasses import dataclass, field
from typing import Optional

NS = "http://www.sii.cl/SiiDte"
NS2 = "http://www.w3.org/2000/09/xmldsig#"

def tag(name):
    return f"{{{NS}}}{name}"


@dataclass
class Item:
    nro: int
    nombre: str
    cantidad: Optional[float]
    precio_unitario: Optional[float]
    descuento_pct: Optional[float]
    descuento_monto: Optional[float]
    monto: int


@dataclass
class Referencia:
    nro: int
    tipo_doc: str
    folio: str
    fecha: str
    razon: Optional[str]


@dataclass
class Totales:
    monto_neto: Optional[int]
    tasa_iva: Optional[float]
    iva: Optional[int]
    monto_exento: Optional[int]
    monto_total: int
    descuento_global_pct: Optional[float] = None
    descuento_global_monto: Optional[int] = None


@dataclass
class DTE:
    tipo: int          # 33=Factura, 56=NDebito, 61=NCredito, etc.
    folio: int
    fecha_emision: str
    # Emisor
    rut_emisor: str
    razon_social: str
    giro: str
    dir_origen: str
    cmna_origen: str
    unidad_sii: Optional[str]
    # Receptor
    rut_receptor: str
    razon_social_receptor: str
    giro_receptor: Optional[str]
    dir_receptor: Optional[str]
    cmna_receptor: Optional[str]
    # Cuerpo
    items: list[Item] = field(default_factory=list)
    referencias: list[Referencia] = field(default_factory=list)
    totales: Optional[Totales] = None
    # TED (timbre) como string XML crudo para el barcode
    ted_xml: Optional[str] = None
    nro_resol: Optional[str] = None
    fch_resol: Optional[str] = None
    # Tipo de traslado para GD
    tipo_traslado: Optional[int] = None


TIPO_NOMBRE = {
    33: "FACTURA ELECTRÓNICA",
    34: "FACTURA NO AFECTA O EXENTA ELECTRÓNICA",
    52: "GUÍA DE DESPACHO ELECTRÓNICA",
    56: "NOTA DE DÉBITO ELECTRÓNICA",
    61: "NOTA DE CRÉDITO ELECTRÓNICA",
    46: "FACTURA DE COMPRA ELECTRÓNICA",
    43: "LIQUIDACIÓN FACTURA ELECTRÓNICA",
    110: "FACTURA DE EXPORTACIÓN ELECTRÓNICA",
    111: "NOTA DE DÉBITO DE EXPORTACIÓN ELECTRÓNICA",
    112: "NOTA DE CRÉDITO DE EXPORTACIÓN ELECTRÓNICA",
}

CEDIBLE_TIPOS = {33, 34, 52, 46, 43}


def _text(el, *path):
    """Navega path desde el, retorna texto o None."""
    cur = el
    for p in path:
        if cur is None:
            return None
        cur = cur.find(tag(p))
    return cur.text.strip() if cur is not None and cur.text else None


def _int(el, *path):
    v = _text(el, *path)
    return int(v) if v else None


def _float(el, *path):
    v = _text(el, *path)
    return float(v) if v else None


def parse_envio_dte(xml_bytes: bytes) -> list[DTE]:
    import re as _re
    root = etree.fromstring(xml_bytes)
    # Extraer TEDs crudos (ISO-8859-1, sin procesar por lxml) para preservar firmas
    raw_str = xml_bytes.decode('iso-8859-1', errors='replace')
    _ted_blocks = _re.findall(r'<TED\b[^>]*>.*?</TED>', raw_str, _re.DOTALL)
    _ted_index = [0]  # índice mutable para consumir en orden
    dtes = []

    # Caratula para nro_resol y fch_resol
    caratula = root.find(f".//{tag('Caratula')}")
    nro_resol = _text(caratula, "NroResol") if caratula is not None else None
    fch_resol = _text(caratula, "FchResol") if caratula is not None else None

    for dte_el in root.findall(f".//{tag('DTE')}"):
        doc = dte_el.find(tag("Documento"))
        if doc is None:
            continue

        enc = doc.find(tag("Encabezado"))
        id_doc = enc.find(tag("IdDoc"))
        emisor = enc.find(tag("Emisor"))
        receptor = enc.find(tag("Receptor"))
        totales_el = enc.find(tag("Totales"))

        tipo = _int(id_doc, "TipoDTE")
        folio = _int(id_doc, "Folio")
        fecha = _text(id_doc, "FchEmis")

        # Items
        items = []
        for det in doc.findall(tag("Detalle")):
            items.append(Item(
                nro=_int(det, "NroLinDet") or 0,
                nombre=_text(det, "NmbItem") or "",
                cantidad=_float(det, "QtyItem"),
                precio_unitario=_float(det, "PrcItem"),
                descuento_pct=_float(det, "DescuentoPct"),
                descuento_monto=_float(det, "DescuentoMonto"),
                monto=_int(det, "MontoItem") or 0,
            ))

        # Referencias
        refs = []
        for ref in doc.findall(tag("Referencia")):
            refs.append(Referencia(
                nro=_int(ref, "NroLinRef") or 0,
                tipo_doc=_text(ref, "TpoDocRef") or "",
                folio=_text(ref, "FolioRef") or "",
                fecha=_text(ref, "FchRef") or "",
                razon=_text(ref, "RazonRef"),
            ))

        # Totales
        tot = None
        if totales_el is not None:
            dscto_gbl_el = doc.find(tag("DscRcgGlobal"))
            dscto_pct = None
            dscto_monto = None
            if dscto_gbl_el is not None:
                dscto_pct = _float(dscto_gbl_el, "PctDR") or _float(dscto_gbl_el, "ValDR")
                dscto_monto = None

            tot = Totales(
                monto_neto=_int(totales_el, "MntNeto"),
                tasa_iva=_float(totales_el, "TasaIVA"),
                iva=_int(totales_el, "IVA"),
                monto_exento=_int(totales_el, "MntExe"),
                monto_total=_int(totales_el, "MntTotal") or 0,
                descuento_global_pct=dscto_pct,
                descuento_global_monto=dscto_monto,
            )

        # TED: usar el bloque crudo ISO-8859-1 del XML (preserva firmas y encoding)
        ted_el = doc.find(tag("TED"))
        if ted_el is not None and _ted_index[0] < len(_ted_blocks):
            ted_xml = _ted_blocks[_ted_index[0]]
            _ted_index[0] += 1
        else:
            ted_xml = None

        # Unidad SII (bajo el recuadro)
        unidad = _text(emisor, "Sucursal") or _text(emisor, "CmnaOrigen")

        dtes.append(DTE(
            tipo=tipo,
            folio=folio,
            fecha_emision=fecha,
            rut_emisor=_text(emisor, "RUTEmisor") or "",
            razon_social=_text(emisor, "RznSoc") or "",
            giro=_text(emisor, "GiroEmis") or "",
            dir_origen=_text(emisor, "DirOrigen") or "",
            cmna_origen=_text(emisor, "CmnaOrigen") or "",
            unidad_sii=unidad,
            rut_receptor=_text(receptor, "RUTRecep") or "",
            razon_social_receptor=_text(receptor, "RznSocRecep") or "",
            giro_receptor=_text(receptor, "GiroRecep"),
            dir_receptor=_text(receptor, "DirRecep"),
            cmna_receptor=_text(receptor, "CmnaRecep"),
            items=items,
            referencias=refs,
            totales=tot,
            ted_xml=ted_xml,
            nro_resol=nro_resol,
            fch_resol=fch_resol,
        ))

    return dtes

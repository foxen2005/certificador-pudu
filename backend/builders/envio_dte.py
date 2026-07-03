"""Genera DTEs individuales firmados y los empaqueta en un EnvioDTE.

Flujo:
    CAF (autorización SII) → build_ted → build_dte_xml → build_envio_dte

CAF: parsea archivos *.xml entregados por SII con autorización de folios y la
clave privada para firmar los TED.

TED: dato del documento + firma CAF, va impreso en el PDF417.

DTE: el documento tributario individual (Documento + TED). Aún sin firma XMLDsig.

EnvioDTE: paquete con N DTEs, cada uno con su firma per-documento, más la firma
outer del SetDTE.
"""
import base64
import copy
import re
from collections import Counter

from lxml import etree
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

from set_parser import CasoSet, ItemSet
from .common import (
    NS_DTE, NS_XSI,
    add_newlines,
    sign_via_pudu, serialize_signed,
)


# ─── CAF ─────────────────────────────────────────────────────────────────────

class CAF:
    """Código de Autorización de Folios entregado por el SII."""

    def __init__(self, xml_bytes: bytes):
        try:
            root = etree.fromstring(xml_bytes)
        except etree.XMLSyntaxError:
            root = etree.fromstring(
                xml_bytes,
                etree.XMLParser(encoding="iso-8859-1", recover=True),
            )
        caf_el = root.find(".//CAF")
        da = caf_el.find("DA")
        self.rut_emisor = da.find("RE").text.strip()
        self.tipo_doc = int(da.find("TD").text)
        self.desde = int(da.find("RNG/D").text)
        self.hasta = int(da.find("RNG/H").text)
        self.fecha_autorizacion = da.find("FA").text.strip()
        self.idk = da.find("IDK").text.strip()
        self._caf_el = caf_el
        self._da_el = da
        rsask_pem = root.find(".//RSASK").text.strip()
        self._private_key = serialization.load_pem_private_key(
            rsask_pem.encode(), password=None, backend=default_backend()
        )

    def caf_xml_element(self) -> etree._Element:
        """Retorna `<CAF>` limpio (DA + FRMA) para incluir en el TED."""
        caf_clean = etree.Element("CAF", version="1.0")
        caf_clean.append(copy.deepcopy(self._da_el))
        caf_clean.append(copy.deepcopy(self._caf_el.find("FRMA")))
        return caf_clean

    def sign_ted(self, dd_bytes: bytes) -> str:
        sig = self._private_key.sign(dd_bytes, padding.PKCS1v15(), hashes.SHA1())
        return base64.b64encode(sig).decode()

    def next_folio(self, used: set) -> int:
        for f in range(self.desde, self.hasta + 1):
            if f not in used:
                return f
        raise ValueError(f"CAF tipo {self.tipo_doc}: sin folios disponibles")


# ─── TED (Timbre Electrónico) ────────────────────────────────────────────────

def _dd_bytes_for_signing(DD: etree._Element) -> bytes:
    """Serializa DD para firmar TED.

    Instructivo SII A.2.4: eliminar whitespace entre tags y codificar en
    ISO-8859-1. NO usar C14N (UTF-8) — el SII verifica sobre los bytes
    ISO-8859-1 del archivo.
    """
    dd_str = etree.tostring(DD, encoding="unicode")
    dd_compact = re.sub(r">\s+<", "><", dd_str).strip()
    return dd_compact.encode("iso-8859-1")


def build_ted(tipo: int, folio: int, fecha: str, rut_receptor: str,
              rsoc_receptor: str, monto_total: int, primer_item: str,
              caf: CAF, timestamp: str) -> etree._Element:
    """Construye y firma el TED."""
    DD = etree.Element("DD")
    etree.SubElement(DD, "RE").text = caf.rut_emisor
    etree.SubElement(DD, "TD").text = str(tipo)
    etree.SubElement(DD, "F").text = str(folio)
    etree.SubElement(DD, "FE").text = fecha
    etree.SubElement(DD, "RR").text = rut_receptor
    etree.SubElement(DD, "RSR").text = rsoc_receptor[:40]
    etree.SubElement(DD, "MNT").text = str(monto_total)
    etree.SubElement(DD, "IT1").text = primer_item[:40]
    DD.append(caf.caf_xml_element())
    etree.SubElement(DD, "TSTED").text = timestamp

    frmt_value = caf.sign_ted(_dd_bytes_for_signing(DD))

    TED = etree.Element("TED", version="1.0")
    TED.append(DD)
    FRMT = etree.SubElement(TED, "FRMT", algoritmo="SHA1withRSA")
    FRMT.text = frmt_value
    return TED


# ─── Cálculo de montos ───────────────────────────────────────────────────────

def calc_totales(items: list[ItemSet], dscto_global_pct: float | None = None):
    neto = exento = 0
    for it in items:
        subtotal = round(it.cantidad * it.precio_unitario)
        if it.descuento_pct:
            subtotal -= round(subtotal * it.descuento_pct / 100)
        if it.es_exento:
            exento += subtotal
        else:
            neto += subtotal

    if dscto_global_pct and neto > 0:
        dscto_global = round(neto * dscto_global_pct / 100)
        neto -= dscto_global
    else:
        dscto_global = None

    iva = round(neto * 0.19)
    total = neto + iva + exento
    return {
        "neto": neto if neto > 0 else None,
        "exento": exento if exento > 0 else None,
        "iva": iva if neto > 0 else None,
        "total": total,
        "dscto_global": dscto_global,
    }


def _cod_ref(razon: str) -> str:
    """Código SII para tipo de referencia (Anula/Corrige/Devolución)."""
    r = (razon or "").upper()
    if "ANULA" in r:
        return "1"
    if "CORRIGE" in r or "GIRO" in r or "RUBRO" in r:
        return "2"
    if "DEVOLUCION" in r or "DEVOLUCIÓN" in r:
        return "3"
    return "1"


def aplicar_regla_corrige_texto(caso: CasoSet) -> bool:
    """Aplica la regla SII REF-2-781 a un caso de NC/ND.

    Una Nota de Crédito/Débito cuya razón de referencia resuelve a
    CodRef=2 ("Corrige Texto" / "Corrige Giro del Receptor" / similar, ver
    `_cod_ref`) NO debe llevar montos: el SII la rechaza con
    "REF-2-781 Modifica Texto no debe tener montos" si MntTotal > 0.

    Si la regla aplica, fuerza `precio_unitario=0` en todos los items del
    caso (creando un item genérico con la razón de referencia como nombre
    si el caso no traía ninguno) y retorna True — en ese caso el llamador
    NO debe aplicar la resolución normal de items (copiar/heredar montos
    del caso referenciado), porque el resultado siempre debe quedar en
    monto cero.

    Retorna False si la regla no aplica (CodRef != 2 o sin razón de
    referencia) y el caso debe seguir el flujo normal de resolución.
    """
    if not caso.razon_referencia:
        return False
    if _cod_ref(caso.razon_referencia) != "2":
        return False
    if not caso.items:
        caso.items = [ItemSet(nombre=caso.razon_referencia[:80], cantidad=1, precio_unitario=0)]
    else:
        for item in caso.items:
            item.precio_unitario = 0.0
    return True


# ─── DTE individual (Documento + TED, sin firma XMLDsig) ─────────────────────

def build_dte_xml(caso: CasoSet, folio: int, emisor_data: dict,
                  receptor: dict, caf: CAF, timestamp: str,
                  folios_referencia: dict | None = None,
                  tipos_referencia: dict | None = None) -> etree._Element:
    """Construye `<DTE>` con su TED firmado, listo para empaquetar en EnvioDTE."""
    fecha = timestamp[:10]

    # T34: todos los items son exentos por definición
    items = caso.items or []
    if caso.tipo_doc == 34:
        items = [copy.copy(it) for it in items]
        for it in items:
            it.es_exento = True

    tots = calc_totales(items, caso.descuento_global_pct)
    primer_item = items[0].nombre if items else "Item"

    ted = build_ted(
        tipo=caso.tipo_doc, folio=folio, fecha=fecha,
        rut_receptor=receptor["rut"], rsoc_receptor=receptor["razon_social"],
        monto_total=tots["total"], primer_item=primer_item,
        caf=caf, timestamp=timestamp,
    )

    DTE = etree.Element("DTE", version="1.0")
    DOC = etree.SubElement(DTE, "Documento",
                           ID=f"LibreDTE_T{caso.tipo_doc}F{folio}")

    # Encabezado
    ENC = etree.SubElement(DOC, "Encabezado")
    ID_DOC = etree.SubElement(ENC, "IdDoc")
    etree.SubElement(ID_DOC, "TipoDTE").text = str(caso.tipo_doc)
    etree.SubElement(ID_DOC, "Folio").text = str(folio)
    etree.SubElement(ID_DOC, "FchEmis").text = fecha
    if caso.tipo_doc == 33:
        etree.SubElement(ID_DOC, "TpoTranVenta").text = "1"
    if caso.tipo_doc == 52:
        etree.SubElement(ID_DOC, "IndTraslado").text = str(caso.ind_traslado or 1)

    # Emisor
    EMIS = etree.SubElement(ENC, "Emisor")
    etree.SubElement(EMIS, "RUTEmisor").text = emisor_data["rut"]
    etree.SubElement(EMIS, "RznSoc").text = emisor_data["razon_social"]
    etree.SubElement(EMIS, "GiroEmis").text = emisor_data["giro"][:80]
    etree.SubElement(EMIS, "Acteco").text = emisor_data.get("acteco", "999999")
    etree.SubElement(EMIS, "DirOrigen").text = emisor_data["dir_origen"]
    etree.SubElement(EMIS, "CmnaOrigen").text = emisor_data["cmna_origen"]

    # Receptor
    REC = etree.SubElement(ENC, "Receptor")
    etree.SubElement(REC, "RUTRecep").text = receptor["rut"]
    etree.SubElement(REC, "RznSocRecep").text = receptor["razon_social"][:100]
    if receptor.get("giro"):
        etree.SubElement(REC, "GiroRecep").text = receptor["giro"][:40]
    if receptor.get("dir"):
        etree.SubElement(REC, "DirRecep").text = receptor["dir"][:70]
    if receptor.get("cmna"):
        etree.SubElement(REC, "CmnaRecep").text = receptor["cmna"]

    # Totales (orden schema DTE_v10: Neto → Exe → TasaIVA → IVA → Total)
    TOTS = etree.SubElement(ENC, "Totales")
    if tots["neto"]:
        etree.SubElement(TOTS, "MntNeto").text = str(tots["neto"])
    if tots["exento"]:
        etree.SubElement(TOTS, "MntExe").text = str(tots["exento"])
    if tots["neto"]:
        etree.SubElement(TOTS, "TasaIVA").text = "19"
        etree.SubElement(TOTS, "IVA").text = str(tots["iva"])
    etree.SubElement(TOTS, "MntTotal").text = str(tots["total"])

    # Detalles (IndExe va ANTES de NmbItem por orden schema)
    for i, item in enumerate(items, 1):
        DET = etree.SubElement(DOC, "Detalle")
        etree.SubElement(DET, "NroLinDet").text = str(i)
        if item.es_exento:
            etree.SubElement(DET, "IndExe").text = "1"
        etree.SubElement(DET, "NmbItem").text = item.nombre
        if item.precio_unitario > 0:
            etree.SubElement(DET, "QtyItem").text = str(int(item.cantidad))
            etree.SubElement(DET, "PrcItem").text = str(int(item.precio_unitario))
            if item.descuento_pct:
                etree.SubElement(DET, "DescuentoPct").text = str(item.descuento_pct)
                dscto_monto = round(item.cantidad * item.precio_unitario * item.descuento_pct / 100)
                etree.SubElement(DET, "DescuentoMonto").text = str(dscto_monto)
        subtotal = round(item.cantidad * item.precio_unitario)
        if item.descuento_pct and item.precio_unitario > 0:
            subtotal -= round(subtotal * item.descuento_pct / 100)
        etree.SubElement(DET, "MontoItem").text = str(subtotal)

    # Descuento global (DESPUÉS de Detalle)
    if caso.descuento_global_pct:
        DRG = etree.SubElement(DOC, "DscRcgGlobal")
        etree.SubElement(DRG, "NroLinDR").text = "1"
        etree.SubElement(DRG, "TpoMov").text = "D"
        etree.SubElement(DRG, "GlosaDR").text = "Descuento Global"
        etree.SubElement(DRG, "TpoValor").text = "%"
        etree.SubElement(DRG, "ValorDR").text = str(caso.descuento_global_pct)

    # Referencia al set de pruebas
    REF_SET = etree.SubElement(DOC, "Referencia")
    etree.SubElement(REF_SET, "NroLinRef").text = "1"
    etree.SubElement(REF_SET, "TpoDocRef").text = "SET"
    etree.SubElement(REF_SET, "FolioRef").text = caso.numero.split("-")[1]
    etree.SubElement(REF_SET, "FchRef").text = fecha
    etree.SubElement(REF_SET, "RazonRef").text = f"CASO {caso.numero}"

    # Referencia a documento anterior (NC/ND)
    if caso.referencia_caso and folios_referencia:
        ref_folio = folios_referencia.get(caso.referencia_caso)
        ref_caso_num = caso.referencia_caso.split("-")[-1] if "-" in caso.referencia_caso else "1"
        tipo_ref = (tipos_referencia or {}).get(caso.referencia_caso, 33)
        REF_DOC = etree.SubElement(DOC, "Referencia")
        etree.SubElement(REF_DOC, "NroLinRef").text = "2"
        etree.SubElement(REF_DOC, "TpoDocRef").text = str(tipo_ref)
        etree.SubElement(REF_DOC, "FolioRef").text = str(ref_folio or ref_caso_num)
        etree.SubElement(REF_DOC, "FchRef").text = fecha
        if caso.razon_referencia:
            etree.SubElement(REF_DOC, "CodRef").text = _cod_ref(caso.razon_referencia)
            etree.SubElement(REF_DOC, "RazonRef").text = caso.razon_referencia

    DOC.append(ted)
    etree.SubElement(DOC, "TmstFirma").text = timestamp
    return DTE


# ─── EnvioDTE firmado ────────────────────────────────────────────────────────

def build_envio_dte(dtes: list[etree._Element], emisor_data: dict,
                    pfx_bytes: bytes, pfx_password: str,
                    timestamp: str,
                    rut_receptor_sii: str = "60803000-K") -> bytes:
    """Empaqueta DTEs en EnvioDTE firmado.

    Flujo crítico (mismo patrón que SII_pudu_Server/server.js:757):

      1. Cada `<DTE>` se firma en CONTEXTO STANDALONE — envuelto en su propio
         `<DTE xmlns="...sii.cl/SiiDte">` sin EnvioDTE padre. Esto evita que
         `xmlns:xsi` (heredado del EnvioDTE root) contamine el C14N del
         Documento, lo que rompía la firma inner (DTE-3-505).
      2. Los DTEs ya firmados se embeben dentro del EnvioDTE.
      3. Se firma el `<SetDTE>` outer en el contexto completo del EnvioDTE.
    """
    # ── PASO 1: firmar cada DTE en contexto STANDALONE ──────────────────────
    # CRÍTICO: los bytes del DTE firmado deben preservarse EXACTAMENTE al
    # embeberse en EnvioDTE. Usamos string concatenation (mismo patrón que
    # SII_pudu_Server/xml-builder.js:wrapInDTE/buildUnsignedEnvioDTE) en lugar
    # de manipulación con lxml — re-serializar con lxml cambia whitespace
    # dentro del Documento y rompe el digest del subtree firmado.
    signed_dtes_str = []
    for dte in dtes:
        doc_el = dte.find("Documento")
        doc_id = doc_el.get("ID")

        # Envolver DTE standalone con xmlns explícito (igual que wrapInDTE).
        # No agregar newlines internos — preservar la estructura tal cual.
        standalone = etree.Element("DTE", xmlns=NS_DTE, version="1.0")
        for child in list(dte):
            standalone.append(child)
        add_newlines(standalone)
        unsigned_dte = serialize_signed(standalone)

        signed_dte_bytes = sign_via_pudu(
            unsigned_dte, pfx_bytes, pfx_password,
            [{
                "ref_id": doc_id,
                "location_xpath": "//*[local-name()='DTE']",
            }],
        )
        # Quitar el <?xml ...?> y conservar el resto AS-IS (sin re-serializar)
        s = signed_dte_bytes.decode("iso-8859-1")
        s = re.sub(r'^\s*<\?xml[^>]*\?>\s*', '', s, count=1)
        signed_dtes_str.append(s.strip())

    # ── PASO 2: construir EnvioDTE con string concatenation ─────────────────
    # Preserva los bytes exactos de cada DTE firmado, vital para que los
    # digests internos no se invaliden al embeber.
    fch_resol = emisor_data.get("fch_resol", timestamp[:10])
    nro_resol = emisor_data.get("nro_resol", "0")

    # Contar tipos
    conteo = Counter()
    for s in signed_dtes_str:
        m = re.search(r'<TipoDTE>(\d+)</TipoDTE>', s)
        if m:
            conteo[m.group(1)] += 1

    parts = []
    parts.append('<EnvioDTE xmlns="' + NS_DTE + '" xmlns:xsi="' + NS_XSI + '" xsi:schemaLocation="' + NS_DTE + ' EnvioDTE_v10.xsd" version="1.0">')
    parts.append('<SetDTE ID="LibreDTE_SetDoc">')
    parts.append('<Caratula version="1.0">')
    parts.append('<RutEmisor>' + emisor_data["rut"] + '</RutEmisor>')
    parts.append('<RutEnvia>' + emisor_data["rut_envia"] + '</RutEnvia>')
    parts.append('<RutReceptor>' + rut_receptor_sii + '</RutReceptor>')
    parts.append('<FchResol>' + fch_resol + '</FchResol>')
    parts.append('<NroResol>' + nro_resol + '</NroResol>')
    parts.append('<TmstFirmaEnv>' + timestamp + '</TmstFirmaEnv>')
    for tipo, cant in sorted(conteo.items()):
        parts.append('<SubTotDTE><TpoDTE>' + tipo + '</TpoDTE><NroDTE>' + str(cant) + '</NroDTE></SubTotDTE>')
    parts.append('</Caratula>')
    for s in signed_dtes_str:
        parts.append(s)
    parts.append('</SetDTE>')
    parts.append('</EnvioDTE>')
    unsigned_envio_str = '\n'.join(parts)
    unsigned_envio = b'<?xml version="1.0" encoding="ISO-8859-1"?>\n' + unsigned_envio_str.encode("iso-8859-1")

    # ── PASO 3: firmar SetDTE outer (envelope) ──────────────────────────────
    return sign_via_pudu(
        unsigned_envio, pfx_bytes, pfx_password,
        [{
            "ref_id": "LibreDTE_SetDoc",
            "location_xpath": "//*[local-name()='EnvioDTE']",
        }],
    )

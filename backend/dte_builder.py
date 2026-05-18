"""
Construye y firma DTEs (XML) a partir de los casos del SIISetDePruebas.
Firma el TED con la clave RSA del CAF.
Firma el DTE con el certificado .pfx del representante.
"""
import base64
import hashlib
from lxml import etree
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import pkcs12

from set_parser import CasoSet, ItemSet

NS_DTE = "http://www.sii.cl/SiiDte"
NS_SIG = "http://www.w3.org/2000/09/xmldsig#"
NSMAP = {None: NS_DTE}


# ─── CAF ─────────────────────────────────────────────────────────────────────

class CAF:
    def __init__(self, xml_bytes: bytes):
        root = etree.fromstring(xml_bytes, etree.XMLParser(encoding="iso-8859-1"))
        caf_el = root.find(".//CAF")
        da = caf_el.find("DA")
        self.rut_emisor = da.find("RE").text.strip()
        self.tipo_doc = int(da.find("TD").text)
        self.desde = int(da.find("RNG/D").text)
        self.hasta = int(da.find("RNG/H").text)
        self.fecha_autorizacion = da.find("FA").text.strip()
        self.idk = da.find("IDK").text.strip()
        # CAF XML crudo (sin el RSASK/RSAPUBK — solo DA+FRMA)
        self._caf_el = caf_el
        self._da_el = da
        # Private key para firmar TED
        rsask_pem = root.find(".//RSASK").text.strip()
        self._private_key = serialization.load_pem_private_key(
            rsask_pem.encode(), password=None, backend=default_backend()
        )

    def caf_xml_element(self) -> etree._Element:
        """Retorna solo el elemento <CAF> (sin RSASK/RSAPUBK) para incluir en TED."""
        import copy
        caf_clean = etree.Element("CAF", version="1.0")
        caf_clean.append(copy.deepcopy(self._da_el))
        frma = self._caf_el.find("FRMA")
        caf_clean.append(copy.deepcopy(frma))
        return caf_clean

    def sign_ted(self, dd_bytes: bytes) -> str:
        """Firma los bytes del elemento DD y retorna la firma en base64."""
        sig = self._private_key.sign(dd_bytes, padding.PKCS1v15(), hashes.SHA1())
        return base64.b64encode(sig).decode()

    def next_folio(self, used: set) -> int:
        for f in range(self.desde, self.hasta + 1):
            if f not in used:
                return f
        raise ValueError(f"CAF para tipo {self.tipo_doc} sin folios disponibles")


# ─── Generador de TED ─────────────────────────────────────────────────────────

def _c14n_bytes(el: etree._Element) -> bytes:
    """Serializa en formato C14N."""
    output = etree.tostring(el, method="c14n")
    return output


def _dd_bytes_for_signing(DD: etree._Element) -> bytes:
    """
    Serializa el elemento DD para firmar el TED.
    Instructivo SII A.2.4: eliminar whitespace entre tags y codificar en ISO-8859-1.
    No usar C14N (UTF-8) — el SII verifica sobre los bytes ISO-8859-1 del archivo.
    """
    import re as _re
    dd_str = etree.tostring(DD, encoding="unicode")
    dd_compact = _re.sub(r">\s+<", "><", dd_str).strip()
    return dd_compact.encode("iso-8859-1")


def build_ted(tipo: int, folio: int, fecha: str, rut_receptor: str,
              rsoc_receptor: str, monto_total: int, primer_item: str,
              caf: CAF, timestamp: str) -> etree._Element:
    """Construye y firma el TED."""

    # DD element
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

    dd_bytes = _dd_bytes_for_signing(DD)
    frmt_value = caf.sign_ted(dd_bytes)

    TED = etree.Element("TED", version="1.0")
    TED.append(DD)
    FRMT = etree.SubElement(TED, "FRMT", algoritmo="SHA1withRSA")
    FRMT.text = frmt_value

    return TED


# ─── Cálculo de montos ────────────────────────────────────────────────────────

def calc_totales(items: list[ItemSet], dscto_global_pct: float = None):
    neto = 0
    exento = 0
    for it in items:
        subtotal = round(it.cantidad * it.precio_unitario)
        if it.descuento_pct:
            dscto = round(subtotal * it.descuento_pct / 100)
            subtotal -= dscto
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


# ─── Constructor del DTE XML ──────────────────────────────────────────────────

def build_dte_xml(caso: CasoSet, folio: int, emisor_data: dict,
                  receptor: dict, caf: CAF, timestamp: str,
                  folios_referencia: dict = None,
                  tipos_referencia: dict = None) -> etree._Element:
    """
    Construye el elemento <DTE> completo con TED firmado.
    folios_referencia: {caso_numero: folio_asignado, ...}
    tipos_referencia: {caso_numero: tipo_doc, ...}
    """
    import copy
    fecha = timestamp[:10]

    # T34: todos los ítems son exentos por definición del tipo de documento
    items = caso.items or []
    if caso.tipo_doc == 34:
        items = [copy.copy(it) for it in items]
        for it in items:
            it.es_exento = True

    tots = calc_totales(items, caso.descuento_global_pct)
    primer_item = items[0].nombre if items else "Item"

    # TED
    ted = build_ted(
        tipo=caso.tipo_doc,
        folio=folio,
        fecha=fecha,
        rut_receptor=receptor["rut"],
        rsoc_receptor=receptor["razon_social"],
        monto_total=tots["total"],
        primer_item=primer_item,
        caf=caf,
        timestamp=timestamp,
    )

    # DTE element
    DTE = etree.Element("DTE", version="1.0")
    DOC = etree.SubElement(DTE, "Documento", ID=f"LibreDTE_T{caso.tipo_doc}F{folio}")

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
    etree.SubElement(REC, "RznSocRecep").text = receptor["razon_social"]
    if receptor.get("giro"):
        etree.SubElement(REC, "GiroRecep").text = receptor["giro"]
    if receptor.get("dir"):
        etree.SubElement(REC, "DirRecep").text = receptor["dir"]
    if receptor.get("cmna"):
        etree.SubElement(REC, "CmnaRecep").text = receptor["cmna"]

    # Totales — orden exacto del schema DTE_v10: MntNeto, MntExe, TasaIVA, IVA, MntTotal
    TOTS = etree.SubElement(ENC, "Totales")
    if tots["neto"]:
        etree.SubElement(TOTS, "MntNeto").text = str(tots["neto"])
    if tots["exento"]:
        etree.SubElement(TOTS, "MntExe").text = str(tots["exento"])
    if tots["neto"]:
        etree.SubElement(TOTS, "TasaIVA").text = "19"
        etree.SubElement(TOTS, "IVA").text = str(tots["iva"])
    etree.SubElement(TOTS, "MntTotal").text = str(tots["total"])

    # Detalles — IndExe debe ir ANTES de NmbItem (orden schema)
    for i, item in enumerate(items, 1):
        DET = etree.SubElement(DOC, "Detalle")
        etree.SubElement(DET, "NroLinDet").text = str(i)
        if item.es_exento:
            etree.SubElement(DET, "IndExe").text = "1"
        etree.SubElement(DET, "NmbItem").text = item.nombre
        # PrcItem mínimo es 0.000001 — omitir para items de corrección (precio=0)
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

    # Descuento global — va DESPUÉS de Detalle (orden schema)
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

    # TED
    DOC.append(ted)
    etree.SubElement(DOC, "TmstFirma").text = timestamp

    return DTE


def _cod_ref(razon: str) -> str:
    r = razon.upper()
    if "ANULA" in r:
        return "1"
    if "CORRIGE" in r or "GIRO" in r or "RUBRO" in r:
        return "2"
    if "DEVOLUCION" in r or "DEVOLUCIÓN" in r:
        return "3"
    return "1"


# ─── Firma XML del DTE con .pfx ───────────────────────────────────────────────

def sign_dte_xml(dte_el: etree._Element, pfx_bytes: bytes, pfx_password: str) -> etree._Element:
    """Firma el elemento <Documento> dentro del DTE usando XMLDsig con el certificado .pfx."""
    from cryptography.x509 import Certificate
    import copy

    # Cargar .pfx
    pwd = pfx_password.encode() if pfx_password else None
    private_key, certificate, chain = pkcs12.load_key_and_certificates(
        pfx_bytes, pwd, backend=default_backend()
    )

    doc_el = dte_el.find("Documento")
    doc_id = doc_el.get("ID")

    # Serializar Documento en C14N para hacer digest
    doc_c14n = etree.tostring(doc_el, method="c14n")
    digest = base64.b64encode(hashlib.sha1(doc_c14n).digest()).decode()

    # Construir SignedInfo
    SI = etree.Element(f"{{{NS_SIG}}}SignedInfo")
    etree.SubElement(SI, f"{{{NS_SIG}}}CanonicalizationMethod",
                     Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315")
    etree.SubElement(SI, f"{{{NS_SIG}}}SignatureMethod",
                     Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1")
    REF = etree.SubElement(SI, f"{{{NS_SIG}}}Reference", URI=f"#{doc_id}")
    TRANS = etree.SubElement(REF, f"{{{NS_SIG}}}Transforms")
    etree.SubElement(TRANS, f"{{{NS_SIG}}}Transform",
                     Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature")
    etree.SubElement(REF, f"{{{NS_SIG}}}DigestMethod",
                     Algorithm="http://www.w3.org/2000/09/xmldsig#sha1")
    DV = etree.SubElement(REF, f"{{{NS_SIG}}}DigestValue")
    DV.text = digest

    # Firmar SignedInfo en C14N
    si_c14n = etree.tostring(SI, method="c14n")
    sig_value = private_key.sign(si_c14n, padding.PKCS1v15(), hashes.SHA1())
    sig_b64 = base64.b64encode(sig_value).decode()

    # Certificado en base64
    cert_der = certificate.public_bytes(serialization.Encoding.DER)
    cert_b64 = base64.b64encode(cert_der).decode()

    # Construir Signature
    SIG = etree.SubElement(dte_el, f"{{{NS_SIG}}}Signature")
    SIG.append(SI)
    SV = etree.SubElement(SIG, f"{{{NS_SIG}}}SignatureValue")
    SV.text = sig_b64
    KI = etree.SubElement(SIG, f"{{{NS_SIG}}}KeyInfo")
    KV = etree.SubElement(KI, f"{{{NS_SIG}}}KeyValue")
    RSA = etree.SubElement(KV, f"{{{NS_SIG}}}RSAKeyValue")
    # Módulo y exponente
    pub_key = certificate.public_key()
    pub_nums = pub_key.public_key().public_numbers() if hasattr(pub_key, 'public_key') else pub_key.public_numbers()
    n_bytes = pub_nums.n.to_bytes((pub_nums.n.bit_length() + 7) // 8, 'big')
    e_bytes = pub_nums.e.to_bytes((pub_nums.e.bit_length() + 7) // 8, 'big')
    etree.SubElement(RSA, f"{{{NS_SIG}}}Modulus").text = base64.b64encode(n_bytes).decode()
    etree.SubElement(RSA, f"{{{NS_SIG}}}Exponent").text = base64.b64encode(e_bytes).decode()
    X509 = etree.SubElement(KI, f"{{{NS_SIG}}}X509Data")
    etree.SubElement(X509, f"{{{NS_SIG}}}X509Certificate").text = cert_b64

    return dte_el


# ─── Formateo XML (newlines en árbol, antes de C14N) ─────────────────────────

def _add_newlines(el: etree._Element) -> None:
    """Agrega \\n entre elementos hijos (no toca texto de hojas).
    Debe llamarse ANTES de calcular cualquier C14N para que el digest
    y la serialización final sean consistentes."""
    if len(el) > 0:
        el.text = "\n"
        for child in el:
            child.tail = "\n"
            _add_newlines(child)


def _c14n_for_sii(el: etree._Element) -> bytes:
    """C14N compatible con la verificación del SII (Java spec-compliant).

    Aplica dos fixes a la salida de lxml etree.tostring(..., method="c14n"):
      1. ``xmlns=""`` en elementos a profundidad ≥2 → bug lxml subtree C14N.
      2. ``xmlns:xsi="..."`` heredado del root pero NO visibly utilized en el
         subtree → bug lxml inclusive C14N (debería excluirse por spec).
    Sin estos fixes, las firmas no validan en el SII (DTE-3-505 / firma libro).
    """
    c14n = etree.tostring(el, method="c14n")
    c14n = c14n.replace(b' xmlns=""', b'')
    c14n = c14n.replace(
        b' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"', b''
    )
    return c14n


def _wrap_base64(el: etree._Element, width: int = 64) -> None:
    """Corta en líneas de 'width' chars el texto de hojas largas (base64).
    Solo afecta elementos hoja (sin hijos). Debe llamarse ANTES del C14N
    que cubre ese elemento para que digest y serialización coincidan."""
    for child in el.iter():
        if child.text and len(child) == 0:
            raw = child.text.replace("\n", "").replace(" ", "")
            if len(raw) > width:
                child.text = "\n" + "\n".join(raw[i:i+width]
                                              for i in range(0, len(raw), width)) + "\n"


# ─── Construir EnvioDTE SIN firmas (para firmar con Node.js/signer.js) ────────

def build_unsigned_envio_dte(dtes: list[etree._Element], emisor_data: dict,
                              timestamp: str, rut_receptor_sii: str = "60803000-K") -> bytes:
    """Genera el EnvioDTE sin ninguna firma. El firmado lo hace Node.js/signer.js."""
    from collections import Counter

    ROOT = etree.Element("EnvioDTE",
                         xmlns="http://www.sii.cl/SiiDte",
                         attrib={
                             "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation":
                                 "http://www.sii.cl/SiiDte EnvioDTE_v10.xsd",
                             "version": "1.0"
                         })
    SET = etree.SubElement(ROOT, "SetDTE", ID="LibreDTE_SetDoc")
    CAR = etree.SubElement(SET, "Caratula", version="1.0")
    etree.SubElement(CAR, "RutEmisor").text = emisor_data["rut"]
    etree.SubElement(CAR, "RutEnvia").text = emisor_data["rut_envia"]
    etree.SubElement(CAR, "RutReceptor").text = rut_receptor_sii
    etree.SubElement(CAR, "FchResol").text = emisor_data.get("fch_resol", timestamp[:10])
    etree.SubElement(CAR, "NroResol").text = emisor_data.get("nro_resol", "0")
    etree.SubElement(CAR, "TmstFirmaEnv").text = timestamp

    conteo = Counter()
    for dte in dtes:
        tipo = dte.find("Documento/Encabezado/IdDoc/TipoDTE").text
        conteo[tipo] += 1
    for tipo, cantidad in sorted(conteo.items()):
        SUB = etree.SubElement(CAR, "SubTotDTE")
        etree.SubElement(SUB, "TpoDTE").text = tipo
        etree.SubElement(SUB, "NroDTE").text = str(cantidad)

    for dte in dtes:
        SET.append(dte)

    _add_newlines(ROOT)
    xml_bytes = etree.tostring(ROOT, xml_declaration=True, encoding="ISO-8859-1")
    return xml_bytes.replace(
        b"<?xml version='1.0' encoding='ISO-8859-1'?>",
        b'<?xml version="1.0" encoding="ISO-8859-1"?>'
    )


# ─── Construir EnvioDTE completo ──────────────────────────────────────────────

def build_envio_dte(dtes: list[etree._Element], emisor_data: dict,
                    pfx_bytes: bytes, pfx_password: str,
                    timestamp: str, rut_receptor_sii: str = "60803000-K") -> bytes:
    """Empaqueta todos los DTEs en un EnvioDTE y lo firma con el .pfx."""

    ROOT = etree.Element("EnvioDTE",
                         xmlns="http://www.sii.cl/SiiDte",
                         attrib={
                             "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation":
                                 "http://www.sii.cl/SiiDte EnvioDTE_v10.xsd",
                             "version": "1.0"
                         })

    SET = etree.SubElement(ROOT, "SetDTE", ID="LibreDTE_SetDoc")
    CAR = etree.SubElement(SET, "Caratula", version="1.0")
    etree.SubElement(CAR, "RutEmisor").text = emisor_data["rut"]
    etree.SubElement(CAR, "RutEnvia").text = emisor_data["rut_envia"]
    etree.SubElement(CAR, "RutReceptor").text = rut_receptor_sii
    etree.SubElement(CAR, "FchResol").text = emisor_data.get("fch_resol", timestamp[:10])
    etree.SubElement(CAR, "NroResol").text = emisor_data.get("nro_resol", "0")
    etree.SubElement(CAR, "TmstFirmaEnv").text = timestamp

    from collections import Counter
    conteo = Counter()
    for dte in dtes:
        tipo = dte.find("Documento/Encabezado/IdDoc/TipoDTE").text
        conteo[tipo] += 1
    for tipo, cantidad in sorted(conteo.items()):
        SUB = etree.SubElement(CAR, "SubTotDTE")
        etree.SubElement(SUB, "TpoDTE").text = tipo
        etree.SubElement(SUB, "NroDTE").text = str(cantidad)

    for dte in dtes:
        SET.append(dte)

    # ── PASO 1: normalizar namespaces (serialize + re-parse) ─────────────────
    # Los DTEs se crean sin namespace explícito; el re-parse les asigna NS_DTE
    # heredado del root. IMPORTANTE: este paso se hace ANTES de firmar los DTEs.
    _add_newlines(ROOT)
    _intermediate = etree.tostring(ROOT)
    ROOT = etree.fromstring(_intermediate)
    SET = ROOT.find(f"{{{NS_DTE}}}SetDTE")

    # ── PASO 2: cargar clave una sola vez ────────────────────────────────────
    pwd_bytes = pfx_password.encode() if pfx_password else None
    private_key, certificate, _ = pkcs12.load_key_and_certificates(
        pfx_bytes, pwd_bytes, backend=default_backend()
    )
    cert_der_dte = certificate.public_bytes(serialization.Encoding.DER)
    cert_b64_dte = base64.b64encode(cert_der_dte).decode()
    pub_nums_dte = certificate.public_key().public_numbers()
    n_bytes_dte = pub_nums_dte.n.to_bytes((pub_nums_dte.n.bit_length() + 7) // 8, 'big')
    e_bytes_dte = pub_nums_dte.e.to_bytes((pub_nums_dte.e.bit_length() + 7) // 8, 'big')

    # ── PASO 3: firmar cada Documento ────────────────────────────────────────
    # Mismo patrón que libro_builder._sign_libro (que funcionó con SII):
    #   1. Construir Signature COMPLETO dentro del árbol (no standalone)
    #   2. Formatear (_add_newlines + _wrap_base64) ANTES de computar si_c14n
    #   3. Calcular C14N del SI ya embebido → firmar → asignar SignatureValue
    # Esto asegura que el C14N que SII recompute al verificar coincida con el
    # que firmamos, porque el XML submitted refleja el árbol exacto que firmamos.
    for dte_el in SET.findall(f"{{{NS_DTE}}}DTE"):
        doc_el = dte_el.find(f"{{{NS_DTE}}}Documento")
        doc_id = doc_el.get("ID")

        # 1. DigestValue del Documento (C14N spec-compliant para SII)
        doc_c14n = _c14n_for_sii(doc_el)
        digest_doc = base64.b64encode(hashlib.sha1(doc_c14n).digest()).decode()

        # 2. Construir Signature en el árbol (nsmap={None: NS_SIG} → default xmlns
        #    de firma, sin prefijo ns0:)
        SIG_dte = etree.SubElement(dte_el, f"{{{NS_SIG}}}Signature",
                                   nsmap={None: NS_SIG})
        SIG_dte.tail = "\n"
        SI_dte = etree.SubElement(SIG_dte, f"{{{NS_SIG}}}SignedInfo")
        etree.SubElement(SI_dte, f"{{{NS_SIG}}}CanonicalizationMethod",
                         Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315")
        etree.SubElement(SI_dte, f"{{{NS_SIG}}}SignatureMethod",
                         Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1")
        REF_dte = etree.SubElement(SI_dte, f"{{{NS_SIG}}}Reference", URI=f"#{doc_id}")
        TRANS_dte = etree.SubElement(REF_dte, f"{{{NS_SIG}}}Transforms")
        etree.SubElement(TRANS_dte, f"{{{NS_SIG}}}Transform",
                         Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature")
        etree.SubElement(REF_dte, f"{{{NS_SIG}}}DigestMethod",
                         Algorithm="http://www.w3.org/2000/09/xmldsig#sha1")
        etree.SubElement(REF_dte, f"{{{NS_SIG}}}DigestValue").text = digest_doc
        SV_dte = etree.SubElement(SIG_dte, f"{{{NS_SIG}}}SignatureValue")
        KI_dte = etree.SubElement(SIG_dte, f"{{{NS_SIG}}}KeyInfo")
        KV_dte = etree.SubElement(KI_dte, f"{{{NS_SIG}}}KeyValue")
        RSA_dte = etree.SubElement(KV_dte, f"{{{NS_SIG}}}RSAKeyValue")
        etree.SubElement(RSA_dte, f"{{{NS_SIG}}}Modulus").text = base64.b64encode(n_bytes_dte).decode()
        etree.SubElement(RSA_dte, f"{{{NS_SIG}}}Exponent").text = base64.b64encode(e_bytes_dte).decode()
        X509_dte = etree.SubElement(KI_dte, f"{{{NS_SIG}}}X509Data")
        etree.SubElement(X509_dte, f"{{{NS_SIG}}}X509Certificate").text = cert_b64_dte

        # 3. Formatear (newlines + wrap base64) ANTES de C14N del SI
        #    El XML serializado tendrá \n entre elementos → C14N de SI los incluye.
        #    Si firmamos sin \n pero el XML los tiene, SII recomputa C14N con \n
        #    y no coincide → DTE-3-505.
        _add_newlines(SIG_dte)
        _wrap_base64(SIG_dte)

        # 4. C14N del SI embebido → firmar → asignar SignatureValue
        si_dte_c14n = _c14n_for_sii(SI_dte)
        sig_val_dte = private_key.sign(si_dte_c14n, padding.PKCS1v15(), hashes.SHA1())
        SV_dte.text = base64.b64encode(sig_val_dte).decode()

    # ── PASO 4: firmar SetDTE (C14N incluye DTEs con sus Signatures completas) ─
    set_c14n = _c14n_for_sii(SET)
    digest_set = base64.b64encode(hashlib.sha1(set_c14n).digest()).decode()

    # 1. Construir Signature del EnvioDTE en el árbol (mismo patrón nsmap)
    SIG = etree.SubElement(ROOT, f"{{{NS_SIG}}}Signature",
                           nsmap={None: NS_SIG})
    SIG.tail = "\n"
    SI = etree.SubElement(SIG, f"{{{NS_SIG}}}SignedInfo")
    etree.SubElement(SI, f"{{{NS_SIG}}}CanonicalizationMethod",
                     Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315")
    etree.SubElement(SI, f"{{{NS_SIG}}}SignatureMethod",
                     Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1")
    REF = etree.SubElement(SI, f"{{{NS_SIG}}}Reference", URI="#LibreDTE_SetDoc")
    TRANS = etree.SubElement(REF, f"{{{NS_SIG}}}Transforms")
    etree.SubElement(TRANS, f"{{{NS_SIG}}}Transform",
                     Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature")
    etree.SubElement(REF, f"{{{NS_SIG}}}DigestMethod",
                     Algorithm="http://www.w3.org/2000/09/xmldsig#sha1")
    etree.SubElement(REF, f"{{{NS_SIG}}}DigestValue").text = digest_set
    SV = etree.SubElement(SIG, f"{{{NS_SIG}}}SignatureValue")
    KI = etree.SubElement(SIG, f"{{{NS_SIG}}}KeyInfo")
    KV = etree.SubElement(KI, f"{{{NS_SIG}}}KeyValue")
    RSA = etree.SubElement(KV, f"{{{NS_SIG}}}RSAKeyValue")
    pub_nums = certificate.public_key().public_numbers()
    n_b = pub_nums.n.to_bytes((pub_nums.n.bit_length() + 7) // 8, 'big')
    e_b = pub_nums.e.to_bytes((pub_nums.e.bit_length() + 7) // 8, 'big')
    etree.SubElement(RSA, f"{{{NS_SIG}}}Modulus").text = base64.b64encode(n_b).decode()
    etree.SubElement(RSA, f"{{{NS_SIG}}}Exponent").text = base64.b64encode(e_b).decode()
    X509 = etree.SubElement(KI, f"{{{NS_SIG}}}X509Data")
    etree.SubElement(X509, f"{{{NS_SIG}}}X509Certificate").text = cert_b64_dte

    # 2. Agregar \n y wrappear base64 ANTES de calcular C14N del SI
    _add_newlines(SIG)
    _wrap_base64(SIG)

    # 3. Calcular C14N del SI ya embebido → firmar → asignar
    si_c14n = _c14n_for_sii(SI)
    sig_bytes = private_key.sign(si_c14n, padding.PKCS1v15(), hashes.SHA1())
    SV.text = base64.b64encode(sig_bytes).decode()

    xml_bytes = etree.tostring(ROOT, xml_declaration=True, encoding="ISO-8859-1")
    return xml_bytes.replace(
        b"<?xml version='1.0' encoding='ISO-8859-1'?>",
        b'<?xml version="1.0" encoding="ISO-8859-1"?>'
    )

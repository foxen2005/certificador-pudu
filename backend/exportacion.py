"""Documentos de Exportación — Factura (110), Nota de Débito (111) y Nota de
Crédito (112) de Exportación Electrónica.

MÓDULO INDEPENDIENTE del set básico: no modifica `builders/envio_dte.py`,
`parser.py` ni `generator.py`. Solo reutiliza piezas ya probadas con el SII:
`CAF`, `build_ted`, `sign_via_pudu`, `serialize_signed`, `add_newlines`.

Fuente de la estructura: `schemas/DTE_v10.xsd` (elemento `<Exportaciones>`,
que reemplaza a `<Documento>`), Formato DTE v2.5 (2026-02) y los EnvioDTE
reales `D:\\PUDU\\Documentacion SII\\exportartaciony doc nuevos\\dte110f202.xml`
y `dte112f102.xml`, que validan contra el XSD. Todo XML que sale de aquí se
valida con `xsd_validator.validar_envio_dte` antes de devolverse.

Reglas del Formato DTE que aplican (columna FACT EXPO):
- `RUTRecep` = 55555555-5 (receptor extranjero). `Extranjero/Nacionalidad` opcional.
- `Totales`: `TpoMoneda` (enum de Aduana, ej. "DOLAR USA") + `MntExe` + `MntTotal`.
  No hay `MntNeto` ni `IVA`: la exportación es exenta, cada ítem lleva `IndExe=1`.
- `OtraMoneda`: "PESO CL" con `TpoCambio` del Banco Central a la fecha de emisión y
  los montos en pesos. Obligatorio en exportación desde 2017 según la bitácora
  del formato (el XSD lo marca opcional).
- `Transporte/Aduana`: `CodModVenta` obligatorio salvo IndServicio 3/4/5; el resto
  (cláusula, vía, puertos, bultos, país) según lo pida el set / la mercadería.
  Los códigos son tablas del Servicio Nacional de Aduanas (aduana.cl), no del SII.
- NC/ND (111/112) deben referenciar la factura de exportación (CodRef 1/2/3).
- Primera `Referencia` de cada DTE de set: `TpoDocRef=SET`, `RazonRef=CASO n-n`.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from lxml import etree

from builders.common import NS_DTE, NS_XSI, add_newlines, serialize_signed, sign_via_pudu
from builders.envio_dte import CAF, build_ted
from xsd_validator import validar_envio_dte

RUT_RECEPTOR_EXTRANJERO = "55555555-5"
RUT_RECEPTOR_SII = "60803000-K"

TIPOS_EXPORTACION = {110, 111, 112}
TIPO_NOMBRE_EXP = {
    110: "FACTURA DE EXPORTACIÓN ELECTRÓNICA",
    111: "NOTA DE DÉBITO DE EXPORTACIÓN ELECTRÓNICA",
    112: "NOTA DE CRÉDITO DE EXPORTACIÓN ELECTRÓNICA",
}

# SiiTypes_v10.xsd → TipMonType (tabla de monedas de Aduana)
MONEDAS = [
    "DOLAR USA", "EURO", "PESO CL", "LIBRA EST", "YEN", "RENMINBI", "FRANCO SZ",
    "NUEVO SOL", "PESO COL", "PESO MEX", "PESO URUG", "PESO", "GUARANI", "RAND",
    "RUPIA", "SUCRE", "DRACMA", "ESCUDO", "FLORIN", "FRANCO BEL", "FRANCO FR",
    "LIRA", "MARCO AL", "MARCO FIN", "PESETA", "OTRAS MONEDAS",
]

# Códigos Aduana usados en la simulación (Formato DTE / tablas aduana.cl).
COD_MOD_VENTA = {"1": "A firme", "2": "Bajo condición", "3": "Consignación libre",
                 "4": "Consignación con mínimo a firme", "9": "Sin pago"}
COD_CLAU_VENTA = {"1": "CIF", "2": "CFR", "3": "EXW", "4": "FAS", "5": "FOB",
                  "6": "S/CL", "7": "DAP", "8": "DAT", "9": "OTROS"}
COD_VIA_TRANSP = {"1": "Marítima, fluvial y lacustre", "4": "Aéreo", "5": "Postal",
                  "6": "Ferroviario", "7": "Carretero / terrestre", "8": "Oleoductos, gasoductos",
                  "9": "Tendido eléctrico", "10": "Otra", "11": "Courier / aéreo"}


# ─── Modelo ──────────────────────────────────────────────────────────────────

@dataclass
class ItemExp:
    nombre: str
    cantidad: Decimal
    precio: Decimal            # en la moneda de la transacción
    unidad: str = "U"          # tabla unidades Aduana (U = unidad, KN = kilo neto, ...)

    @property
    def monto(self) -> Decimal:
        return (self.cantidad * self.precio).quantize(Decimal("0.01"), ROUND_HALF_UP)


@dataclass
class ReceptorExp:
    razon_social: str
    direccion: str = ""
    ciudad: str = ""
    giro: str = ""
    nacionalidad: str = ""     # código país Aduana (3 dígitos), opcional
    num_id: str = ""           # Tax ID extranjero, opcional


@dataclass
class AduanaExp:
    cod_mod_venta: str = "1"
    cod_clau_venta: str = ""
    tot_clau_venta: Decimal | None = None   # por defecto = MntTotal
    cod_via_transp: str = ""
    nombre_transp: str = ""
    cod_pto_embarque: str = ""
    cod_pto_desemb: str = ""
    peso_bruto: Decimal | None = None
    peso_neto: Decimal | None = None
    cod_unid_peso: str = ""       # ej. "6" = KN (kilo neto) según tabla Aduana
    tot_bultos: int | None = None
    cod_tpo_bultos: str = ""
    mnt_flete: Decimal | None = None
    mnt_seguro: Decimal | None = None
    cod_pais_recep: str = ""
    cod_pais_destin: str = ""


@dataclass
class RefExp:
    tipo_doc: str      # "110", "SET", "807" (DUS)...
    folio: str
    fecha: str
    cod_ref: str = ""  # 1 anula, 2 corrige texto, 3 corrige montos
    razon: str = ""


@dataclass
class DocExp:
    tipo: int
    folio: int
    fecha: str
    items: list[ItemExp]
    moneda: str
    tipo_cambio: Decimal
    receptor: ReceptorExp
    aduana: AduanaExp = field(default_factory=AduanaExp)
    ind_servicio: str = ""       # 3/4/5/6 → exportación de servicios
    fma_pag_exp: str = ""        # tabla formas de pago Aduana (21 = sin pago)
    referencias: list[RefExp] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"LibreDTE_T{self.tipo}F{self.folio}"

    @property
    def mnt_exe(self) -> Decimal:
        return sum((it.monto for it in self.items), Decimal("0")).quantize(Decimal("0.01"))

    @property
    def mnt_total(self) -> Decimal:
        return self.mnt_exe

    @property
    def mnt_total_clp(self) -> int:
        return int((self.mnt_total * self.tipo_cambio).quantize(Decimal("1"), ROUND_HALF_UP))


def fmt_dec(v: Decimal | int | float | None, max_dec: int = 4) -> str:
    """Decimal sin ceros a la derecha ("5600", "1234.5", "0.1234")."""
    if v is None:
        return ""
    d = Decimal(str(v)).quantize(Decimal(1).scaleb(-max_dec), ROUND_HALF_UP)
    s = f"{d:f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


# ─── XML del DTE ─────────────────────────────────────────────────────────────

def _sub(parent, tag, text=None):
    el = etree.SubElement(parent, tag)
    if text is not None:
        el.text = str(text)
    return el


def build_exportacion_dte(doc: DocExp, emisor: dict, caf: CAF, timestamp: str) -> etree._Element:
    """`<DTE version="1.0"><Exportaciones ID=…>…</Exportaciones></DTE>` sin firma XMLDSig
    (el TED sí va firmado con el CAF). Orden de elementos = DTE_v10.xsd."""
    if caf.tipo_doc != doc.tipo:
        raise ValueError(f"CAF es tipo {caf.tipo_doc}, el documento es {doc.tipo}")
    if not (caf.desde <= doc.folio <= caf.hasta):
        raise ValueError(f"Folio {doc.folio} fuera del rango del CAF ({caf.desde}-{caf.hasta})")
    if doc.tipo in (111, 112) and not any(r.tipo_doc in ("110", "111", "112") for r in doc.referencias):
        raise ValueError(f"T{doc.tipo} debe referenciar la factura de exportación (TpoDocRef 110)")
    if doc.moneda not in MONEDAS:
        raise ValueError(f"Moneda '{doc.moneda}' no está en la tabla TipMonType del SII")

    DTE = etree.Element("DTE", version="1.0")
    EXP = etree.SubElement(DTE, "Exportaciones", ID=doc.id)
    ENC = etree.SubElement(EXP, "Encabezado")

    ID = etree.SubElement(ENC, "IdDoc")
    _sub(ID, "TipoDTE", doc.tipo)
    _sub(ID, "Folio", doc.folio)
    _sub(ID, "FchEmis", doc.fecha)
    if doc.ind_servicio:
        _sub(ID, "IndServicio", doc.ind_servicio)
    if doc.fma_pag_exp:
        _sub(ID, "FmaPagExp", doc.fma_pag_exp)

    EM = etree.SubElement(ENC, "Emisor")
    _sub(EM, "RUTEmisor", emisor["rut"])
    _sub(EM, "RznSoc", emisor["razon_social"][:100])
    _sub(EM, "GiroEmis", emisor["giro"][:80])
    _sub(EM, "Acteco", emisor["acteco"])
    if emisor.get("dir_origen"):
        _sub(EM, "DirOrigen", emisor["dir_origen"][:60])
    if emisor.get("cmna_origen"):
        _sub(EM, "CmnaOrigen", emisor["cmna_origen"][:20])
        # Formato DTE: CiudadOrigen obligatoria en la 110; se usa la comuna si no hay ciudad
        _sub(EM, "CiudadOrigen", (emisor.get("ciudad_origen") or emisor["cmna_origen"])[:20])

    r = doc.receptor
    RE = etree.SubElement(ENC, "Receptor")
    _sub(RE, "RUTRecep", RUT_RECEPTOR_EXTRANJERO)
    _sub(RE, "RznSocRecep", r.razon_social[:100])
    if r.num_id or r.nacionalidad:
        EX = etree.SubElement(RE, "Extranjero")
        if r.num_id:
            _sub(EX, "NumId", r.num_id[:20])
        if r.nacionalidad:
            _sub(EX, "Nacionalidad", r.nacionalidad)
    if r.giro:
        _sub(RE, "GiroRecep", r.giro[:40])
    if r.direccion:
        _sub(RE, "DirRecep", r.direccion[:70])
    if r.ciudad:
        _sub(RE, "CiudadRecep", r.ciudad[:20])

    a = doc.aduana
    AD = etree.Element("Aduana")
    if a.cod_mod_venta:
        _sub(AD, "CodModVenta", a.cod_mod_venta)
    if a.cod_clau_venta:
        _sub(AD, "CodClauVenta", a.cod_clau_venta)
        _sub(AD, "TotClauVenta", fmt_dec(a.tot_clau_venta if a.tot_clau_venta is not None else doc.mnt_total, 2))
    if a.cod_via_transp:
        _sub(AD, "CodViaTransp", a.cod_via_transp)
    if a.nombre_transp:
        _sub(AD, "NombreTransp", a.nombre_transp[:40])
    if a.cod_pto_embarque:
        _sub(AD, "CodPtoEmbarque", a.cod_pto_embarque)
    if a.cod_pto_desemb:
        _sub(AD, "CodPtoDesemb", a.cod_pto_desemb)
    if a.peso_bruto is not None:
        _sub(AD, "PesoBruto", fmt_dec(a.peso_bruto, 2))
        _sub(AD, "CodUnidPesoBruto", a.cod_unid_peso or "6")
    if a.peso_neto is not None:
        _sub(AD, "PesoNeto", fmt_dec(a.peso_neto, 2))
        _sub(AD, "CodUnidPesoNeto", a.cod_unid_peso or "6")
    if a.tot_bultos is not None:
        _sub(AD, "TotBultos", a.tot_bultos)
        if a.cod_tpo_bultos:
            TB = etree.SubElement(AD, "TipoBultos")
            _sub(TB, "CodTpoBultos", a.cod_tpo_bultos)
            _sub(TB, "CantBultos", a.tot_bultos)
    if a.mnt_flete is not None and a.mnt_flete > 0:
        _sub(AD, "MntFlete", fmt_dec(a.mnt_flete, 4))
    if a.mnt_seguro is not None and a.mnt_seguro > 0:
        _sub(AD, "MntSeguro", fmt_dec(a.mnt_seguro, 4))
    if a.cod_pais_recep:
        _sub(AD, "CodPaisRecep", a.cod_pais_recep)
    if a.cod_pais_destin:
        _sub(AD, "CodPaisDestin", a.cod_pais_destin)
    if len(AD):
        TR = etree.SubElement(ENC, "Transporte")
        TR.append(AD)

    TOT = etree.SubElement(ENC, "Totales")
    _sub(TOT, "TpoMoneda", doc.moneda)
    _sub(TOT, "MntExe", fmt_dec(doc.mnt_exe, 2))
    _sub(TOT, "MntTotal", fmt_dec(doc.mnt_total, 2))

    OM = etree.SubElement(ENC, "OtraMoneda")
    _sub(OM, "TpoMoneda", "PESO CL")
    _sub(OM, "TpoCambio", fmt_dec(doc.tipo_cambio, 4))
    _sub(OM, "MntExeOtrMnda", doc.mnt_total_clp)
    _sub(OM, "MntTotOtrMnda", doc.mnt_total_clp)

    for n, it in enumerate(doc.items, 1):
        DET = etree.SubElement(EXP, "Detalle")
        _sub(DET, "NroLinDet", n)
        _sub(DET, "IndExe", 1)
        _sub(DET, "NmbItem", it.nombre[:80])
        _sub(DET, "QtyItem", fmt_dec(it.cantidad, 6))
        if it.unidad:
            _sub(DET, "UnmdItem", it.unidad[:4])
        _sub(DET, "PrcItem", fmt_dec(it.precio, 6))
        _sub(DET, "MontoItem", fmt_dec(it.monto, 2))

    for n, ref in enumerate(doc.referencias, 1):
        RF = etree.SubElement(EXP, "Referencia")
        _sub(RF, "NroLinRef", n)
        _sub(RF, "TpoDocRef", ref.tipo_doc)
        _sub(RF, "FolioRef", ref.folio)
        _sub(RF, "FchRef", ref.fecha)
        if ref.cod_ref:
            _sub(RF, "CodRef", ref.cod_ref)
        if ref.razon:
            _sub(RF, "RazonRef", ref.razon[:90])

    ted = build_ted(doc.tipo, doc.folio, doc.fecha, RUT_RECEPTOR_EXTRANJERO,
                    r.razon_social, fmt_dec(doc.mnt_total, 2), doc.items[0].nombre, caf, timestamp)
    EXP.append(ted)
    _sub(EXP, "TmstFirma", timestamp)
    return DTE


# ─── EnvioDTE firmado ────────────────────────────────────────────────────────

def build_envio_exportacion(dtes: list[etree._Element], emisor: dict, pfx_bytes: bytes,
                            pfx_password: str, timestamp: str,
                            rut_receptor: str = RUT_RECEPTOR_SII) -> bytes:
    """Mismo patrón probado en `build_envio_dte` (firma standalone + string concat +
    firma outer), pero referenciando `<Exportaciones ID>` en vez de `<Documento ID>`."""
    signed = []
    for dte in dtes:
        doc_id = dte.find("Exportaciones").get("ID")
        standalone = etree.Element("DTE", xmlns=NS_DTE, version="1.0")
        for child in list(dte):
            standalone.append(child)
        add_newlines(standalone)
        signed_bytes = sign_via_pudu(
            serialize_signed(standalone), pfx_bytes, pfx_password,
            [{"ref_id": doc_id, "location_xpath": "//*[local-name()='DTE']"}],
        )
        s = re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", signed_bytes.decode("iso-8859-1"), count=1)
        signed.append(s.strip())

    conteo = Counter()
    for s in signed:
        m = re.search(r"<TipoDTE>(\d+)</TipoDTE>", s)
        if m:
            conteo[m.group(1)] += 1

    parts = [
        f'<EnvioDTE xmlns="{NS_DTE}" xmlns:xsi="{NS_XSI}" xsi:schemaLocation="{NS_DTE} EnvioDTE_v10.xsd" version="1.0">',
        '<SetDTE ID="LibreDTE_SetDoc">',
        '<Caratula version="1.0">',
        f'<RutEmisor>{emisor["rut"]}</RutEmisor>',
        f'<RutEnvia>{emisor["rut_envia"]}</RutEnvia>',
        f'<RutReceptor>{rut_receptor}</RutReceptor>',
        f'<FchResol>{emisor["fch_resol"]}</FchResol>',
        f'<NroResol>{emisor["nro_resol"]}</NroResol>',
        f'<TmstFirmaEnv>{timestamp}</TmstFirmaEnv>',
    ]
    for tipo, cant in sorted(conteo.items()):
        parts.append(f"<SubTotDTE><TpoDTE>{tipo}</TpoDTE><NroDTE>{cant}</NroDTE></SubTotDTE>")
    parts.append("</Caratula>")
    parts.extend(signed)
    parts += ["</SetDTE>", "</EnvioDTE>"]
    unsigned = b'<?xml version="1.0" encoding="ISO-8859-1"?>\n' + "\n".join(parts).encode("iso-8859-1")
    envio = sign_via_pudu(unsigned, pfx_bytes, pfx_password,
                          [{"ref_id": "LibreDTE_SetDoc", "location_xpath": "//*[local-name()='EnvioDTE']"}])
    errores = validar_envio_dte(envio)
    if errores:
        raise ValueError("EnvioDTE de exportación no cumple el XSD del SII: " + " | ".join(errores[:5]))
    return envio


# ─── Parser (para PDF / muestras) ────────────────────────────────────────────

@dataclass
class ItemExpParsed:
    nro: int
    nombre: str
    cantidad: str
    unidad: str
    precio: str
    monto: str


@dataclass
class DocExpParsed:
    tipo: int
    folio: int
    fecha: str
    rut_emisor: str
    razon_social: str
    giro: str
    dir_origen: str
    cmna_origen: str
    rut_receptor: str
    razon_social_receptor: str
    dir_receptor: str
    ciudad_receptor: str
    moneda: str
    mnt_exe: str
    mnt_total: str
    tipo_cambio: str
    mnt_total_clp: str
    aduana: dict
    items: list[ItemExpParsed]
    referencias: list[RefExp]
    ted_xml: str
    nro_resol: str
    fch_resol: str


def parse_envio_exportacion(xml_bytes: bytes) -> list[DocExpParsed]:
    """Lee un EnvioDTE con `<Exportaciones>`. El TED se extrae como string crudo
    (lección 8: re-serializar con lxml agrega xmlns y rompe el PDF417)."""
    raw = xml_bytes.decode("iso-8859-1", errors="replace")
    teds = re.findall(r"<TED\b[^>]*>.*?</TED>", raw, re.DOTALL)
    root = etree.fromstring(xml_bytes)
    ns = {"s": NS_DTE}
    car = root.find(".//s:Caratula", ns)
    nro_resol = car.findtext("s:NroResol", default="0", namespaces=ns)
    fch_resol = car.findtext("s:FchResol", default="", namespaces=ns)

    def t(el, path):
        return (el.findtext(path, default="", namespaces=ns) or "").strip()

    docs = []
    for i, exp in enumerate(root.findall(".//s:Exportaciones", ns)):
        enc = exp.find("s:Encabezado", ns)
        ad = enc.find("s:Transporte/s:Aduana", ns)
        aduana = {}
        if ad is not None:
            for c in ad:
                tag = etree.QName(c).localname
                aduana[tag] = (c.text or "").strip() if len(c) == 0 else ""
        items = [ItemExpParsed(int(t(d, "s:NroLinDet") or 0), t(d, "s:NmbItem"), t(d, "s:QtyItem"),
                               t(d, "s:UnmdItem"), t(d, "s:PrcItem"), t(d, "s:MontoItem"))
                 for d in exp.findall("s:Detalle", ns)]
        refs = [RefExp(t(rf, "s:TpoDocRef"), t(rf, "s:FolioRef"), t(rf, "s:FchRef"), t(rf, "s:CodRef"), t(rf, "s:RazonRef"))
                for rf in exp.findall("s:Referencia", ns)]
        docs.append(DocExpParsed(
            tipo=int(t(enc, "s:IdDoc/s:TipoDTE")), folio=int(t(enc, "s:IdDoc/s:Folio")),
            fecha=t(enc, "s:IdDoc/s:FchEmis"),
            rut_emisor=t(enc, "s:Emisor/s:RUTEmisor"), razon_social=t(enc, "s:Emisor/s:RznSoc"),
            giro=t(enc, "s:Emisor/s:GiroEmis"), dir_origen=t(enc, "s:Emisor/s:DirOrigen"),
            cmna_origen=t(enc, "s:Emisor/s:CmnaOrigen"),
            rut_receptor=t(enc, "s:Receptor/s:RUTRecep"), razon_social_receptor=t(enc, "s:Receptor/s:RznSocRecep"),
            dir_receptor=t(enc, "s:Receptor/s:DirRecep"), ciudad_receptor=t(enc, "s:Receptor/s:CiudadRecep"),
            moneda=t(enc, "s:Totales/s:TpoMoneda"), mnt_exe=t(enc, "s:Totales/s:MntExe"),
            mnt_total=t(enc, "s:Totales/s:MntTotal"),
            tipo_cambio=t(enc, "s:OtraMoneda/s:TpoCambio"), mnt_total_clp=t(enc, "s:OtraMoneda/s:MntTotOtrMnda"),
            aduana=aduana, items=items, referencias=refs,
            ted_xml=teds[i] if i < len(teds) else "",
            nro_resol=nro_resol, fch_resol=fch_resol,
        ))
    return docs


# ─── Simulación (sin set del SII) ────────────────────────────────────────────

def docs_simulacion(fecha: str, folios: dict[int, int], producto: str, cantidad: int,
                    precio: Decimal, moneda: str, tipo_cambio: Decimal,
                    receptor: ReceptorExp, aduana: AduanaExp) -> list[DocExp]:
    """T110 (venta) → T112 anula la factura → T111 anula la NC. Misma cadena que la
    simulación del set básico y que el par 110/112 real de `dte110f202/dte112f102`."""
    item = ItemExp(producto, Decimal(cantidad), precio)
    f110 = DocExp(110, folios[110], fecha, [item], moneda, tipo_cambio, receptor, aduana)
    f112 = DocExp(112, folios[112], fecha, [item], moneda, tipo_cambio, receptor, aduana,
                  referencias=[RefExp("110", str(folios[110]), fecha, "1",
                                      f"Anula Factura de Exportacion {folios[110]}")])
    f111 = DocExp(111, folios[111], fecha, [item], moneda, tipo_cambio, receptor, aduana,
                  referencias=[RefExp("112", str(folios[112]), fecha, "1",
                                      f"Anula Nota de Credito de Exportacion {folios[112]}")])
    return [f110, f112, f111]

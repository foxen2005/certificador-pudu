"""Guía de Despacho Electrónica (52) — SET GUIA DE DESPACHO del SII.

MÓDULO INDEPENDIENTE del set básico (no modifica `set_parser.py`,
`builders/envio_dte.py`, `parser.py` ni `generator.py`). Reutiliza `CAF`,
`build_ted`, `build_envio_dte` (la guía SÍ usa `<Documento>`, así que el
empaquetado/firma del set básico sirve tal cual) y `calc_totales`.

Formato del set (ej. PUDU 78392059-K, N° atención 5089739, 2026-09-22):

    SET GUIA DE DESPACHO - NUMERO DE ATENCIÓN: 5089739
    CASO 5089739-1
    DOCUMENTO   GUIA DE DESPACHO
    MOTIVO:     TRASLADO DE MATERIALES ENTRE BODEGAS DE LA EMPRESA
    ITEM        CANTIDAD
    ITEM 1      59
    CASO 5089739-2
    DOCUMENTO   GUIA DE DESPACHO
    MOTIVO:     VENTA
    TRASLADO POR:   EMISOR DEL DOCUMENTO AL LOCAL DEL CLIENTE
    ITEM        CANTIDAD    PRECIO UNITARIO
    ITEM 1      122         2944

Reglas (Formato DTE v2.5 + instrucciones del propio set):
- `IndTraslado` (tabla del Formato): 1 venta, 2 ventas por efectuar, 3 consignación,
  4 entrega gratuita, 5 traslado interno, 6 otros no venta, 7 devolución,
  8 traslado para exportación, 9 venta para exportación. Se deduce del MOTIVO.
- `TipoDespacho`: 1 por cuenta del receptor (cliente), 2 por cuenta del emisor a
  instalaciones del cliente, 3 por cuenta del emisor a otras instalaciones.
  Se deduce de "TRASLADO POR"; traslado interno entre bodegas → 3.
- Traslado interno: "los datos del receptor deben coincidir con los del emisor",
  sin precios (MontoItem 0, MntTotal 0) y sin ejemplar cedible ("inoficioso").
- Venta: montos neto/IVA/total como una factura; lleva cedible
  "CEDIBLE CON SU FACTURA" (Manual de Muestras §1.4).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

from builders.common import NS_DTE
from builders.envio_dte import CAF, build_ted, calc_totales
from set_parser import ItemSet

IND_TRASLADO = {
    1: "Operación constituye venta",
    2: "Ventas por efectuar",
    3: "Consignaciones",
    4: "Entrega gratuita",
    5: "Traslados internos",
    6: "Otros traslados no venta",
    7: "Guía de devolución",
    8: "Traslado para exportación (no venta)",
    9: "Venta para exportación",
}
TIPO_DESPACHO = {
    1: "Despacho por cuenta del receptor del documento",
    2: "Despacho por cuenta del emisor a instalaciones del cliente",
    3: "Despacho por cuenta del emisor a otras instalaciones",
}


# ─── Parser del set ──────────────────────────────────────────────────────────

@dataclass
class CasoGuia:
    numero: str                 # "5089739-1"
    motivo: str
    traslado_por: str = ""
    items: list[ItemSet] = field(default_factory=list)
    ind_override: int | None = None   # simulación: el tipo lo elige el usuario

    @property
    def ind_traslado(self) -> int:
        if self.ind_override is not None:
            return self.ind_override
        m = self.motivo.upper()
        if "INTERNO" in m or "ENTRE BODEGAS" in m or "ENTRE SUCURSALES" in m:
            return 5
        # "OTROS TRASLADOS NO VENTA" contiene "VENTA": descartar antes de la
        # regla de venta, o se emitiría una guía de venta con IVA y cedible.
        if "NO VENTA" in m or "NO CONSTITUYE VENTA" in m:
            return 6
        if "DEVOLUCION" in m or "DEVOLUCIÓN" in m:
            return 7
        if "CONSIGNACION" in m or "CONSIGNACIÓN" in m:
            return 3
        if "GRATUITA" in m:
            return 4
        if "POR EFECTUAR" in m:
            return 2
        if "EXPORTACION" in m or "EXPORTACIÓN" in m:
            return 9 if "VENTA" in m else 8
        if "VENTA" in m:
            return 1
        return 6

    @property
    def tipo_despacho(self) -> int | None:
        # Reparo real del SII (77334712-3, set 5089806, 2026-09-22): con
        # IndTraslado=5 (interno) y TipoDespacho=3 → "Los Indicadores
        # (Despacho/Traslado) No Corresponden". Los casos de venta (TipoDespacho
        # 1 y 2) pasaron. Por eso: sin "TRASLADO POR" no se emite TipoDespacho.
        t = self.traslado_por.upper()
        if not t:
            return None
        if "CLIENTE" in t and "EMISOR" not in t:
            return 1
        if "EMISOR" in t and ("CLIENTE" in t or "RECEPTOR" in t):
            return 2
        if "EMISOR" in t:
            return 3
        return None

    @property
    def es_venta(self) -> bool:
        return self.ind_traslado in (1, 2, 9)

    @property
    def es_interno(self) -> bool:
        return self.ind_traslado == 5

    @property
    def lleva_cedible(self) -> bool:
        # Set del SII: "una operación que no constituye venta, el ejemplar cedible es inoficioso"
        return self.es_venta


@dataclass
class SetGuias:
    nro_atencion: str
    casos: list[CasoGuia]


def parse_set_guias(texto: str) -> SetGuias:
    """Parsea la sección SET GUIA DE DESPACHO de un SIISetDePruebas*.txt."""
    m = re.search(r"SET\s+GUIA\s+DE\s+DESPACHO\s*-\s*NUMERO\s+DE\s+ATENCI[OÓ]N:\s*(\d+)", texto, re.IGNORECASE)
    if not m:
        raise ValueError("El archivo no contiene un 'SET GUIA DE DESPACHO - NUMERO DE ATENCIÓN'")
    nro = m.group(1)
    seccion = texto[m.end():]
    fin = re.search(r"^SET\s+\w", seccion, re.MULTILINE)   # siguiente set, si lo hay
    if fin:
        seccion = seccion[:fin.start()]

    casos: list[CasoGuia] = []
    actual: CasoGuia | None = None
    for ln in seccion.splitlines():
        ln = ln.rstrip()
        if not ln.strip() or set(ln.strip()) <= {"=", "-"}:
            continue
        mc = re.match(r"^CASO\s+([\d-]+)", ln)
        if mc:
            actual = CasoGuia(numero=mc.group(1), motivo="")
            casos.append(actual)
            continue
        if actual is None:
            continue
        mm = re.match(r"^MOTIVO:\s*(.+)$", ln, re.IGNORECASE)
        if mm:
            actual.motivo = mm.group(1).strip()
            continue
        mt = re.match(r"^TRASLADO\s+POR:\s*(.+)$", ln, re.IGNORECASE)
        if mt:
            actual.traslado_por = mt.group(1).strip()
            continue
        if re.match(r"^(DOCUMENTO|ITEM\s+CANTIDAD)", ln, re.IGNORECASE):
            continue
        # Línea de ítem: "ITEM 1 <tabs> 122 [<tabs> 2944]"
        mi = re.match(r"^(.+?)\s{2,}(\d+)(?:\s+(\d+))?\s*$", ln.replace("\t", "    "))
        if mi:
            actual.items.append(ItemSet(
                nombre=mi.group(1).strip(), cantidad=float(mi.group(2)),
                precio_unitario=float(mi.group(3)) if mi.group(3) else 0.0,
            ))
    if not casos:
        raise ValueError("SET GUIA DE DESPACHO sin casos")
    for c in casos:
        if not c.items:
            raise ValueError(f"Caso {c.numero} sin ítems")
        if not c.motivo:
            # Sin MOTIVO no se puede deducir IndTraslado; firmar igual quemaría el folio.
            raise ValueError(f"Caso {c.numero} sin línea 'MOTIVO:' — revisar el formato del set")
    return SetGuias(nro_atencion=nro, casos=casos)


# ─── XML de la guía ──────────────────────────────────────────────────────────

def build_guia_dte(caso: CasoGuia, folio: int, emisor: dict, receptor: dict,
                   caf: CAF, timestamp: str, referencia_set: bool = True) -> etree._Element:
    """`<DTE><Documento ID=…>` de una guía, con TED firmado. El receptor de un
    traslado interno es el propio emisor (instrucción del set)."""
    if caf.tipo_doc != 52:
        raise ValueError(f"CAF es tipo {caf.tipo_doc}, se necesita 52")
    if not (caf.desde <= folio <= caf.hasta):
        raise ValueError(f"Folio {folio} fuera del rango del CAF ({caf.desde}-{caf.hasta})")
    fecha = timestamp[:10]

    if caso.es_interno:
        rec = {"rut": emisor["rut"], "razon_social": emisor["razon_social"], "giro": emisor["giro"],
               "dir": emisor.get("dir_origen", ""), "cmna": emisor.get("cmna_origen", "")}
        tots = {"neto": None, "exento": None, "iva": None, "total": 0}
    else:
        rec = receptor
        tots = calc_totales(caso.items)

    ted = build_ted(52, folio, fecha, rec["rut"], rec["razon_social"], tots["total"],
                    caso.items[0].nombre, caf, timestamp)

    DTE = etree.Element("DTE", version="1.0")
    DOC = etree.SubElement(DTE, "Documento", ID=f"LibreDTE_T52F{folio}")
    ENC = etree.SubElement(DOC, "Encabezado")
    ID = etree.SubElement(ENC, "IdDoc")
    etree.SubElement(ID, "TipoDTE").text = "52"
    etree.SubElement(ID, "Folio").text = str(folio)
    etree.SubElement(ID, "FchEmis").text = fecha
    if caso.tipo_despacho:
        etree.SubElement(ID, "TipoDespacho").text = str(caso.tipo_despacho)
    etree.SubElement(ID, "IndTraslado").text = str(caso.ind_traslado)

    EM = etree.SubElement(ENC, "Emisor")
    etree.SubElement(EM, "RUTEmisor").text = emisor["rut"]
    etree.SubElement(EM, "RznSoc").text = emisor["razon_social"][:100]
    etree.SubElement(EM, "GiroEmis").text = emisor["giro"][:80]
    etree.SubElement(EM, "Acteco").text = emisor.get("acteco", "999999")
    etree.SubElement(EM, "DirOrigen").text = emisor["dir_origen"][:60]
    etree.SubElement(EM, "CmnaOrigen").text = emisor["cmna_origen"][:20]

    RE = etree.SubElement(ENC, "Receptor")
    etree.SubElement(RE, "RUTRecep").text = rec["rut"]
    etree.SubElement(RE, "RznSocRecep").text = rec["razon_social"][:100]
    if rec.get("giro"):
        etree.SubElement(RE, "GiroRecep").text = rec["giro"][:40]
    if rec.get("dir"):
        etree.SubElement(RE, "DirRecep").text = rec["dir"][:70]
    if rec.get("cmna"):
        etree.SubElement(RE, "CmnaRecep").text = rec["cmna"][:20]

    TOT = etree.SubElement(ENC, "Totales")
    if tots["neto"]:
        etree.SubElement(TOT, "MntNeto").text = str(tots["neto"])
        etree.SubElement(TOT, "TasaIVA").text = "19"
        etree.SubElement(TOT, "IVA").text = str(tots["iva"])
    etree.SubElement(TOT, "MntTotal").text = str(tots["total"])

    for i, it in enumerate(caso.items, 1):
        DET = etree.SubElement(DOC, "Detalle")
        etree.SubElement(DET, "NroLinDet").text = str(i)
        etree.SubElement(DET, "NmbItem").text = it.nombre[:80]
        etree.SubElement(DET, "QtyItem").text = str(int(it.cantidad))
        if it.precio_unitario > 0:
            etree.SubElement(DET, "PrcItem").text = str(int(it.precio_unitario))
        etree.SubElement(DET, "MontoItem").text = str(round(it.cantidad * it.precio_unitario))

    # La referencia SET/CASO es exclusiva del set de pruebas; la simulación son
    # documentos de la operación real y no la lleva.
    if referencia_set:
        REF = etree.SubElement(DOC, "Referencia")
        etree.SubElement(REF, "NroLinRef").text = "1"
        etree.SubElement(REF, "TpoDocRef").text = "SET"
        etree.SubElement(REF, "FolioRef").text = caso.numero.split("-")[-1]
        etree.SubElement(REF, "FchRef").text = fecha
        etree.SubElement(REF, "RazonRef").text = f"CASO {caso.numero}"

    DOC.append(ted)
    etree.SubElement(DOC, "TmstFirma").text = timestamp
    return DTE


# ─── Parser del EnvioDTE (para PDF) ──────────────────────────────────────────

@dataclass
class ItemGuiaParsed:
    nro: int
    nombre: str
    cantidad: str
    precio: str
    monto: str


@dataclass
class GuiaParsed:
    folio: int
    fecha: str
    ind_traslado: int
    tipo_despacho: int | None
    rut_emisor: str
    razon_social: str
    giro: str
    dir_origen: str
    cmna_origen: str
    rut_receptor: str
    razon_social_receptor: str
    giro_receptor: str
    dir_receptor: str
    cmna_receptor: str
    mnt_neto: str
    iva: str
    mnt_total: str
    items: list[ItemGuiaParsed]
    caso: str
    ted_xml: str
    nro_resol: str
    fch_resol: str

    @property
    def es_venta(self) -> bool:
        return self.ind_traslado in (1, 2, 9)


def parse_envio_guias(xml_bytes: bytes) -> list[GuiaParsed]:
    raw = xml_bytes.decode("iso-8859-1", errors="replace")
    teds = re.findall(r"<TED\b[^>]*>.*?</TED>", raw, re.DOTALL)  # crudo (lección 8)
    root = etree.fromstring(xml_bytes)
    ns = {"s": NS_DTE}
    car = root.find(".//s:Caratula", ns)

    def t(el, path):
        return (el.findtext(path, default="", namespaces=ns) or "").strip()

    out = []
    for i, doc in enumerate(root.findall(".//s:Documento", ns)):
        if t(doc, "s:Encabezado/s:IdDoc/s:TipoDTE") != "52":
            continue
        enc = doc.find("s:Encabezado", ns)
        caso = next((t(r, "s:RazonRef") for r in doc.findall("s:Referencia", ns) if t(r, "s:TpoDocRef") == "SET"), "")
        out.append(GuiaParsed(
            folio=int(t(enc, "s:IdDoc/s:Folio")), fecha=t(enc, "s:IdDoc/s:FchEmis"),
            ind_traslado=int(t(enc, "s:IdDoc/s:IndTraslado") or 1),
            tipo_despacho=int(t(enc, "s:IdDoc/s:TipoDespacho")) if t(enc, "s:IdDoc/s:TipoDespacho") else None,
            rut_emisor=t(enc, "s:Emisor/s:RUTEmisor"), razon_social=t(enc, "s:Emisor/s:RznSoc"),
            giro=t(enc, "s:Emisor/s:GiroEmis"), dir_origen=t(enc, "s:Emisor/s:DirOrigen"), cmna_origen=t(enc, "s:Emisor/s:CmnaOrigen"),
            rut_receptor=t(enc, "s:Receptor/s:RUTRecep"), razon_social_receptor=t(enc, "s:Receptor/s:RznSocRecep"),
            giro_receptor=t(enc, "s:Receptor/s:GiroRecep"), dir_receptor=t(enc, "s:Receptor/s:DirRecep"),
            cmna_receptor=t(enc, "s:Receptor/s:CmnaRecep"),
            mnt_neto=t(enc, "s:Totales/s:MntNeto"), iva=t(enc, "s:Totales/s:IVA"), mnt_total=t(enc, "s:Totales/s:MntTotal"),
            items=[ItemGuiaParsed(int(t(d, "s:NroLinDet") or 0), t(d, "s:NmbItem"), t(d, "s:QtyItem"), t(d, "s:PrcItem"), t(d, "s:MontoItem"))
                   for d in doc.findall("s:Detalle", ns)],
            caso=caso, ted_xml=teds[i] if i < len(teds) else "",
            nro_resol=car.findtext("s:NroResol", default="0", namespaces=ns),
            fch_resol=car.findtext("s:FchResol", default="", namespaces=ns),
        ))
    return out


# ─── Simulación (Etapa 2: datos reales del contribuyente, sin set) ───────────
#
# El Manual de Certificación (§6.2) define la Simulación como un envío con
# documentos "correspondientes a su facturación de los últimos 2 meses … con
# datos representativos, paralelos de la operación real del contribuyente".
# Para guías eso significa los mismos tipos de traslado que usará en producción,
# pero con sus productos, precios y receptor reales — no los del set.
#
# Se construyen `CasoGuia` sintéticos para pasar por el MISMO builder que el
# set (`build_guia_dte`), de modo que las reglas ya aceptadas por el SII
# (receptor = emisor e importes 0 en traslado interno, TipoDespacho solo en
# venta, cedible solo en venta) se apliquen igual.

MOTIVO_SIMULACION = {
    1: "VENTA",
    2: "VENTAS POR EFECTUAR",
    3: "CONSIGNACION",
    4: "ENTREGA GRATUITA",
    5: "TRASLADO INTERNO ENTRE BODEGAS DE LA EMPRESA",
    6: "OTROS TRASLADOS NO VENTA",
    7: "DEVOLUCION DE MERCADERIAS",
}
TRASLADO_POR_SIMULACION = {
    1: "CLIENTE",
    2: "EMISOR DEL DOCUMENTO AL LOCAL DEL CLIENTE",
    3: "EMISOR DEL DOCUMENTO A OTRAS INSTALACIONES",
}


def casos_simulacion(traslados: list[int], items: list[ItemSet],
                     tipo_despacho: int | None = None) -> list[CasoGuia]:
    """Casos de simulación: un `CasoGuia` por tipo de traslado pedido.

    `items` son los productos reales (nombre, cantidad, precio). El traslado
    interno (5) va sin precios y con montos 0; los demás traslados que no son
    venta (3, 4, 6, 7) sí informan montos, como cualquier guía valorizada.
    `tipo_despacho` (1/2/3) aplica solo a los traslados de venta; el traslado
    interno nunca lo lleva (reparo del SII, ver `CasoGuia.tipo_despacho`).

    El tipo de traslado se fija con `ind_override`, no se deduce del texto: en
    la simulación lo elige el usuario y no puede depender de un match de glosa.
    """
    if not traslados:
        raise ValueError("Indica al menos un tipo de traslado para la simulación")
    if not items:
        raise ValueError("Indica al menos un producto para la simulación")
    casos = []
    for n, ind in enumerate(traslados, 1):
        if ind not in MOTIVO_SIMULACION:
            raise ValueError(f"Tipo de traslado {ind} no soportado en la simulación (1-7)")
        caso = CasoGuia(numero=f"SIM-{n}", motivo=MOTIVO_SIMULACION[ind], ind_override=ind,
                        items=[ItemSet(nombre=i.nombre, cantidad=i.cantidad,
                                       precio_unitario=i.precio_unitario) for i in items])
        if ind in (1, 2, 9) and tipo_despacho:
            caso.traslado_por = TRASLADO_POR_SIMULACION.get(tipo_despacho, "")
        casos.append(caso)
    return casos

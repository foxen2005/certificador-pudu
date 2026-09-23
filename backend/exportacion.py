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

D2 = Decimal("0.01")


@dataclass
class ItemExp:
    nombre: str
    cantidad: Decimal | None       # None → ítem de servicio con "valor línea"
    precio: Decimal | None         # en la moneda de la transacción
    unidad: str = "U"              # tabla unidades Aduana (U, KN, LT, PAR…)
    valor_linea: Decimal | None = None   # servicios: monto directo sin cantidad×precio
    descuento_pct: Decimal | None = None
    recargo_pct: Decimal | None = None   # ej. "10% recargo en la línea por comisiones"

    def __post_init__(self):
        # Servicio con "VALOR LINEA": se normaliza a cantidad 1 × precio = valor,
        # sin unidad (IndServicio 3/4/5 no la exige). El SII compara PrcItem con el
        # valor del set (reparo "Datos de la Linea 1 No Cuadran") y así las NC/ND,
        # el XML y el PDF usan una sola representación.
        if self.valor_linea is not None and self.cantidad is None:
            self.cantidad, self.precio = Decimal(1), Decimal(self.valor_linea)
            self.unidad, self.valor_linea = "", None

    @property
    def bruto(self) -> Decimal:
        return (self.cantidad * self.precio).quantize(D2, ROUND_HALF_UP)

    # DescuentoMonto / RecargoMonto son MntImpType en el XSD (entero, sin decimales),
    # también en Exportaciones. Se redondean y MontoItem se calcula con el entero
    # para que el SII cuadre la línea.
    @property
    def descuento_monto(self) -> Decimal:
        return (self.bruto * self.descuento_pct / 100).quantize(Decimal("1"), ROUND_HALF_UP) if self.descuento_pct else Decimal("0")

    @property
    def recargo_monto(self) -> Decimal:
        return (self.bruto * self.recargo_pct / 100).quantize(Decimal("1"), ROUND_HALF_UP) if self.recargo_pct else Decimal("0")

    @property
    def monto(self) -> Decimal:
        # Formato DTE: MontoItem = (Precio × Cantidad) − Descuento + Recargo
        return (self.bruto - self.descuento_monto + self.recargo_monto).quantize(D2)


@dataclass
class RecargoGlobal:
    glosa: str
    monto: Decimal          # en la moneda de la transacción; TpoValor "$"
    tipo: str = "R"         # R recargo / D descuento


@dataclass
class ReceptorExp:
    razon_social: str
    direccion: str = ""
    ciudad: str = ""
    giro: str = ""
    nacionalidad: str = ""     # código país Aduana (3 dígitos), opcional
    num_id: str = ""           # Tax ID extranjero, opcional


def _iso6346(prefijo: str) -> str:
    """Contenedor ISO 6346 (4 letras + 6 dígitos) con su dígito verificador tras guion."""
    valores, v = {}, 10
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if v % 11 == 0:
            v += 1
        valores[ch] = v
        v += 1
    total = sum((valores[c] if c.isalpha() else int(c)) * 2 ** i for i, c in enumerate(prefijo))
    return f"{prefijo}-{total % 11 % 10}"


# Tipos de bulto "contenedor" de la tabla de Aduana (73/74 dry, 75/76 refrigerado,
# 78 no especificado). El 77 (ESTANQUE) es explícitamente "no contenedor".
CODIGOS_CONTENEDOR = {"73", "74", "75", "76", "78"}
# El set no trae marcas ni datos del contenedor ("agregue otros datos que estime
# necesarios"): se informan valores de ejemplo con formato válido.
MARCAS_DEFECTO = "S/M"
ID_CONTAINER_DEFECTO = _iso6346("MSCU123456")
SELLO_DEFECTO = "123456-7"
EMISOR_SELLO_DEFECTO = "LINEA NAVIERA"
PASAPORTE_DEFECTO = "E12345"  # hotelería: N° de pasaporte del huésped (ref. 813)


def es_contenedor(cod_tpo_bultos: str) -> bool:
    return str(cod_tpo_bultos).lstrip("0") in CODIGOS_CONTENEDOR


@dataclass
class AduanaExp:
    cod_mod_venta: str = "1"
    cod_clau_venta: str = ""
    tot_clau_venta: Decimal | None = None   # por defecto = MntTotal
    cod_via_transp: str = ""
    nombre_transp: str = ""
    cod_pto_embarque: str = ""
    cod_pto_desemb: str = ""
    tara: int | None = None
    cod_unid_tara: str = ""
    peso_bruto: Decimal | None = None
    peso_neto: Decimal | None = None
    cod_unid_peso: str = ""       # ej. "6" = KN (kilo neto) según tabla Aduana
    cod_unid_peso_neto: str = ""  # si difiere del bruto (el set puede pedir U bruto y KN neto)
    tot_bultos: int | None = None
    cod_tpo_bultos: str = ""
    marcas: str = ""              # bulto distinto de contenedor
    id_container: str = ""        # bulto contenedor (con guion y DV)
    sello: str = ""
    emisor_sello: str = ""
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
    recargos_globales: list[RecargoGlobal] = field(default_factory=list)  # flete, seguro, comisiones

    @property
    def id(self) -> str:
        return f"LibreDTE_T{self.tipo}F{self.folio}"

    @property
    def mnt_exe(self) -> Decimal:
        # Suma de ítems (exentos) ± descuentos/recargos globales exentos
        base = sum((it.monto for it in self.items), Decimal("0"))
        for r in self.recargos_globales:
            base += r.monto if r.tipo == "R" else -r.monto
        return base.quantize(D2)

    @property
    def mnt_total(self) -> Decimal:
        # Formato DTE (MntTotal): "En documentos de exportación es 0 (cero) si
        # forma de pago es = 21 (sin pago)".
        if self.fma_pag_exp == "21":
            return Decimal("0")
        return self.mnt_exe

    @property
    def mnt_exe_clp(self) -> int:
        return int((self.mnt_exe * self.tipo_cambio).quantize(Decimal("1"), ROUND_HALF_UP))

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
        raise ValueError(f"T{doc.tipo} debe referenciar la factura/nota de exportación (TpoDocRef 110/112)")
    if not doc.items:
        raise ValueError(f"T{doc.tipo} F{doc.folio} sin ítems")
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
        # TotClauVenta: valor según cláusula (DUS). Si el set no lo da, el monto
        # exento del documento. XSD exige ≥ 0.01, por eso no se usa MntTotal
        # (que es 0 con forma de pago 21).
        # Con IndServicio 3/4/5 TotClauVenta no es obligatorio (Formato DTE): si el
        # set no lo da, no se inventa (LibreDTE tampoco lo emite en ese caso).
        tot_clau = a.tot_clau_venta
        if tot_clau is None and str(doc.ind_servicio) not in ("3", "4", "5"):
            tot_clau = doc.mnt_exe
        if tot_clau and tot_clau > 0:
            _sub(AD, "TotClauVenta", fmt_dec(tot_clau, 2))
    if a.cod_via_transp:
        _sub(AD, "CodViaTransp", a.cod_via_transp)
    if a.nombre_transp:
        _sub(AD, "NombreTransp", a.nombre_transp[:40])
    if a.cod_pto_embarque:
        _sub(AD, "CodPtoEmbarque", a.cod_pto_embarque)
    if a.cod_pto_desemb:
        _sub(AD, "CodPtoDesemb", a.cod_pto_desemb)
    if a.tara is not None:
        _sub(AD, "Tara", a.tara)
        _sub(AD, "CodUnidMedTara", a.cod_unid_tara or a.cod_unid_peso or "6")
    if a.peso_bruto is not None:
        _sub(AD, "PesoBruto", fmt_dec(a.peso_bruto, 2))
        _sub(AD, "CodUnidPesoBruto", a.cod_unid_peso or "6")
    if a.peso_neto is not None:
        _sub(AD, "PesoNeto", fmt_dec(a.peso_neto, 2))
        _sub(AD, "CodUnidPesoNeto", a.cod_unid_peso_neto or a.cod_unid_peso or "6")
    if a.tot_bultos is not None:
        _sub(AD, "TotBultos", a.tot_bultos)
        if a.cod_tpo_bultos:
            TB = etree.SubElement(AD, "TipoBultos")
            _sub(TB, "CodTpoBultos", a.cod_tpo_bultos)
            _sub(TB, "CantBultos", a.tot_bultos)
            # Formato DTE campos 98-101 (reparo HED-2-804 del SII si faltan):
            # contenedor → IdContainer + Sello (+ EmisorSello); otro bulto → Marcas.
            if es_contenedor(a.cod_tpo_bultos):
                _sub(TB, "IdContainer", a.id_container or ID_CONTAINER_DEFECTO)
                _sub(TB, "Sello", a.sello or SELLO_DEFECTO)
                _sub(TB, "EmisorSello", a.emisor_sello or EMISOR_SELLO_DEFECTO)
            else:
                _sub(TB, "Marcas", a.marcas or MARCAS_DEFECTO)
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
    _sub(OM, "MntExeOtrMnda", doc.mnt_exe_clp)
    _sub(OM, "MntTotOtrMnda", doc.mnt_total_clp)

    for n, it in enumerate(doc.items, 1):
        DET = etree.SubElement(EXP, "Detalle")
        _sub(DET, "NroLinDet", n)
        _sub(DET, "IndExe", 1)
        _sub(DET, "NmbItem", it.nombre[:80])
        if it.cantidad is not None:
            _sub(DET, "QtyItem", fmt_dec(it.cantidad, 6))
            if it.unidad:
                _sub(DET, "UnmdItem", it.unidad[:4])
        if it.precio is not None:
            _sub(DET, "PrcItem", fmt_dec(it.precio, 6))
        # MntImpType es positiveInteger: si el % redondea a 0 no se emite la línea
        if it.descuento_pct and it.descuento_monto > 0:
            _sub(DET, "DescuentoPct", fmt_dec(it.descuento_pct, 2))
            _sub(DET, "DescuentoMonto", fmt_dec(it.descuento_monto, 0))
        if it.recargo_pct and it.recargo_monto > 0:
            _sub(DET, "RecargoPct", fmt_dec(it.recargo_pct, 2))
            _sub(DET, "RecargoMonto", fmt_dec(it.recargo_monto, 0))
        _sub(DET, "MontoItem", fmt_dec(it.monto, 2))

    # Recargos/descuentos globales (flete, seguro, comisiones). En exportación
    # ValorDROtrMnda (en pesos) es obligatorio según el Formato DTE.
    for n, rg in enumerate(doc.recargos_globales, 1):
        DR = etree.SubElement(EXP, "DscRcgGlobal")
        _sub(DR, "NroLinDR", n)
        _sub(DR, "TpoMov", rg.tipo)
        _sub(DR, "GlosaDR", rg.glosa[:45])
        _sub(DR, "TpoValor", "$")
        _sub(DR, "ValorDR", fmt_dec(rg.monto, 2))
        _sub(DR, "ValorDROtrMnda", fmt_dec((rg.monto * doc.tipo_cambio).quantize(D2, ROUND_HALF_UP), 4))
        _sub(DR, "IndExeDR", 1)

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
    descuento_pct: str = ""
    descuento_monto: str = ""
    recargo_pct: str = ""
    recargo_monto: str = ""


@dataclass
class RecargoParsed:
    tipo: str       # R / D
    glosa: str
    valor: str


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
    ind_servicio: str = ""
    fma_pag_exp: str = ""
    recargos: list[RecargoParsed] = field(default_factory=list)


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
                               t(d, "s:UnmdItem"), t(d, "s:PrcItem"), t(d, "s:MontoItem"),
                               t(d, "s:DescuentoPct"), t(d, "s:DescuentoMonto"), t(d, "s:RecargoPct"), t(d, "s:RecargoMonto"))
                 for d in exp.findall("s:Detalle", ns)]
        recargos = [RecargoParsed(t(r, "s:TpoMov"), t(r, "s:GlosaDR"), t(r, "s:ValorDR")) for r in exp.findall("s:DscRcgGlobal", ns)]
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
            ind_servicio=t(enc, "s:IdDoc/s:IndServicio"), fma_pag_exp=t(enc, "s:IdDoc/s:FmaPagExp"),
            recargos=recargos,
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


# ─── Set de pruebas de exportación (SII) ─────────────────────────────────────
#
# Formato real (PUDU 78392059-K, 2026-09-22, N° atención 5089803 y 5089804):
#
#   SET BASICO DOCUMENTOS DE EXPORTACION (1) - NUMERO DE ATENCION: 5089803
#   CASO 5089803-1
#   DOCUMENTO   FACTURA DE EXPORTACION ELECTRONICA
#   ITEM                 CANTIDAD   UNIDAD MEDIDA   PRECIO UNITARIO
#   CHATARRA DE ALUMINIO    326         U               123
#   REFERENCIA:                        MIC (MANIFIESTO INTERNACIONAL)
#   MONEDA DE LA OPERACION:            DOLAR USA
#   FORMA DE PAGO EXPORTACION:         ACRED
#   MODALIDAD DE VENTA:                A FIRME
#   CLAUSULA DE VENTA DE EXPORTACION:  FOB
#   TOTAL CLAUSULA DE VENTA:           1356.22
#   VIA DE TRANSPORTE:                 AEREO
#   PUERTO DE EMBARQUE / DESEMBARQUE:  ARICA / BUENOS AIRES
#   UNIDAD DE MEDIDA DE TARA / PESO BRUTO / PESO NETO: U / U / KN
#   TIPO DE BULTO / TOTAL BULTOS:      CONTENEDOR REFRIGERADO / 33
#   FLETE (**) / SEGURO (**):          306.55 / 69.29
#   PAIS RECEPTOR Y PAIS DESTINO:      ARGENTINA
#
# Variantes: ítems "VALOR LINEA" (servicios, sin cantidad), "%10 RECARGO EN LA
# LINEA", "COMISIONES EN EL EXTRANJERO (RECARGOS GLOBALES): 11% DEL TOTAL DE LA
# CLAUSULA", "DESCUENTO LINEA # 1: 5%", "NACIONALIDAD: JAPON" (hotelería), NC con
# solo cantidades ("EL PRECIO UNITARIO DEBE SER EL MISMO DE LA FACTURA") y ND que
# anula la NC. Instrucciones del set: (**) flete y seguro van en MntFlete/MntSeguro
# Y ADEMÁS como dos líneas de recargo global; cada set se envía por separado.

from aduana_tablas import (cod_bulto, cod_clausula, cod_forma_pago, cod_modalidad,
                           cod_pais, cod_puerto, cod_unidad, cod_via)

_TIPO_SET = {
    "FACTURA DE EXPORTACION ELECTRONICA": 110,
    "NOTA DE DEBITO DE EXPORTACION ELECTRONICA": 111,
    "NOTA DE CREDITO DE EXPORTACION ELECTRONICA": 112,
}
# Referencias documentales del set → TpoDocRef (Formato DTE, tabla de tipos de referencia)
_REF_DOC = {
    "DUS": "807", "B/L": "808", "BL": "808", "CONOCIMIENTO DE EMBARQUE": "808", "AWB": "809",
    "MIC": "810", "MIC/DTA": "810", "MANIFIESTO INTERNACIONAL": "810", "CARTA DE PORTE": "811",
    "RESOLUCION SNA": "812", "RESOLUCION DEL SNA": "812", "PASAPORTE": "813",
}


@dataclass
class ItemSetExp:
    nombre: str
    cantidad: Decimal | None
    unidad: str | None
    precio: Decimal | None
    valor_linea: Decimal | None


@dataclass
class CasoExp:
    numero: str
    tipo: int
    items: list[ItemSetExp] = field(default_factory=list)
    campos: dict = field(default_factory=dict)          # "MONEDA DE LA OPERACION" → "DOLAR USA"
    referencias_doc: list[str] = field(default_factory=list)   # "DUS", "AWB", "MIC (…)"
    referencia_caso: str = ""                             # NC/ND: "5089803-1"
    razon_referencia: str = ""
    recargo_linea_pct: Decimal | None = None              # "%10 RECARGO EN LA LINEA DE ITEM"
    recargo_global_pct: Decimal | None = None             # "COMISIONES … 11% DEL TOTAL DE LA CLAUSULA"
    descuento_linea: dict = field(default_factory=dict)   # {1: Decimal(5)}
    notas: list[str] = field(default_factory=list)

    @property
    def es_servicio(self) -> bool:
        return bool(self.items) and all(i.valor_linea is not None for i in self.items)

    @property
    def es_hoteleria(self) -> bool:
        return self.es_servicio and "NACIONALIDAD" in self.campos and "PUERTO DE EMBARQUE" not in self.campos


@dataclass
class SetExp:
    nro_atencion: str
    nombre: str
    casos: list[CasoExp]


def parse_set_exportacion(texto: str) -> list[SetExp]:
    """Devuelve los sets de exportación del archivo (el SII entrega 2, se envían por separado)."""
    cabeceras = list(re.finditer(
        r"^SET\s+BASICO\s+DOCUMENTOS\s+DE\s+EXPORTACION\s*(\([^)]*\))?\s*-\s*NUMERO\s+DE\s+ATENCI[OÓ]N:\s*(\d+)",
        texto, re.MULTILINE | re.IGNORECASE))
    if not cabeceras:
        raise ValueError("El archivo no contiene 'SET BASICO DOCUMENTOS DE EXPORTACION - NUMERO DE ATENCION'")
    sets = []
    for i, m in enumerate(cabeceras):
        fin = cabeceras[i + 1].start() if i + 1 < len(cabeceras) else len(texto)
        cuerpo = texto[m.end():fin]
        cuerpo = re.split(r"^INSTRUCCIONES AL CONTRIBUYENTE", cuerpo, flags=re.MULTILINE)[0]
        sets.append(SetExp(nro_atencion=m.group(2), nombre=m.group(0).split(" - ")[0].strip(), casos=_parse_casos_exp(cuerpo)))
    return sets


def _num(s: str) -> Decimal:
    return Decimal(s.replace(",", ".").strip())


def _parse_casos_exp(cuerpo: str) -> list[CasoExp]:
    casos: list[CasoExp] = []
    actual: CasoExp | None = None
    en_items = False
    cols: list[str] = []
    for raw in cuerpo.splitlines():
        ln = raw.replace("\t", "    ").rstrip()
        s = ln.strip()
        if not s or set(s) <= {"=", "-"}:
            if en_items and actual and actual.items:
                en_items = False
            continue
        mc = re.match(r"^CASO\s+([\d-]+)", s)
        if mc:
            actual = CasoExp(numero=mc.group(1), tipo=0)
            casos.append(actual)
            en_items = False
            continue
        if actual is None:
            continue
        md = re.match(r"^DOCUMENTO\s+(.+)$", s, re.IGNORECASE)
        if md:
            nombre = re.sub(r"\s+", " ", md.group(1)).upper()
            if nombre not in _TIPO_SET:
                raise ValueError(f"Caso {actual.numero}: tipo de documento desconocido '{nombre}'")
            actual.tipo = _TIPO_SET[nombre]
            continue
        mr = re.match(r"^REFERENCIA\s+(.+?)\s+CORRESPONDIENTE\s+A\s+CASO\s+([\d-]+)", s, re.IGNORECASE)
        if mr:
            actual.referencia_caso = mr.group(2)
            continue
        mz = re.match(r"^RAZON\s+REFERENCIA\s+(.+)$", s, re.IGNORECASE)
        if mz:
            actual.razon_referencia = mz.group(1).strip()
            continue
        if re.match(r"^ITEM\b", s, re.IGNORECASE) and ("CANTIDAD" in s.upper() or "VALOR LINEA" in s.upper()):
            hdr = s.upper()
            if "VALOR LINEA" in hdr:
                cols = ["VALOR"]
            elif "UNIDAD" in hdr:
                cols = ["CANT", "UNID", "PRECIO"]
            elif "PRECIO" in hdr:
                cols = ["CANT", "PRECIO"]
            else:
                cols = ["CANT"]
            en_items = True
            continue
        mk = re.match(r"^([A-ZÁÉÍÓÚÑ/ ()*#0-9]+?)\s*:\s*(.*)$", s)
        if mk and not en_items:
            clave = re.sub(r"\s*\(\*\*\)", "", mk.group(1)).strip().upper()
            valor = mk.group(2).strip()
            if clave == "REFERENCIA":
                actual.referencias_doc.append(valor)
            elif clave.startswith("DESCUENTO LINEA"):
                mnum = re.search(r"#\s*(\d+)", clave)
                actual.descuento_linea[int(mnum.group(1)) if mnum else 1] = _num(valor.rstrip("%"))
            elif "RECARGOS GLOBALES" in clave or "COMISIONES" in clave:
                mp = re.search(r"(\d+(?:[.,]\d+)?)\s*%", valor)
                actual.recargo_global_pct = _num(mp.group(1)) if mp else None
                actual.notas.append(s)
            else:
                actual.campos[clave] = valor
            continue
        mp = re.match(r"^%\s*(\d+(?:[.,]\d+)?)\s+RECARGO EN LA LINEA", s, re.IGNORECASE)
        if mp:
            actual.recargo_linea_pct = _num(mp.group(1))
            actual.notas.append(s)
            continue
        if s.upper().startswith("EL PRECIO UNITARIO"):
            actual.notas.append(s)
            en_items = False
            continue
        if en_items:
            # ítem: nombre (con espacios simples) + columnas separadas por ≥2 espacios
            partes = re.split(r"\s{2,}", s)
            if len(partes) >= 2:
                it = ItemSetExp(nombre=partes[0], cantidad=None, unidad=None, precio=None, valor_linea=None)
                vals = partes[1:]
                if cols == ["VALOR"]:
                    it.valor_linea = _num(vals[0])
                else:
                    it.cantidad = _num(vals[0])
                    if "UNID" in cols and len(vals) > 1:
                        it.unidad = vals[1].strip()
                    if "PRECIO" in cols and len(vals) >= len(cols):
                        it.precio = _num(vals[-1])
                actual.items.append(it)
    for c in casos:
        if not c.tipo:
            raise ValueError(f"Caso {c.numero} sin línea DOCUMENTO")
        if c.tipo == 110 and not c.items:
            raise ValueError(f"Caso {c.numero} sin ítems")
        if c.tipo in (111, 112) and not c.referencia_caso:
            raise ValueError(f"Caso {c.numero}: NC/ND sin 'REFERENCIA … CORRESPONDIENTE A CASO'")
    return casos


def _ref_doc_code(texto: str) -> str:
    t = re.sub(r"\s+", " ", texto.upper()).strip()
    for k, v in _REF_DOC.items():
        if t.startswith(k) or k in t:
            return v
    raise ValueError(f"Referencia documental '{texto}' no reconocida (DUS, AWB, B/L, MIC, CARTA DE PORTE, RESOLUCION SNA, PASAPORTE)")


#: Campos Aduana que docs_desde_set traduce a código (solo T110 que no es hotelería).
#: Debe calzar EXACTO con docs_desde_set: si revisa de más bloquea sets válidos,
#: si revisa de menos da luz verde y la generación falla igual.
CAMPOS_ADUANA = [
    ("MODALIDAD DE VENTA", cod_modalidad),
    ("CLAUSULA DE VENTA DE EXPORTACION", cod_clausula),
    ("VIA DE TRANSPORTE", cod_via),
    ("PUERTO DE EMBARQUE", cod_puerto),
    ("PUERTO DE DESEMBARQUE", cod_puerto),
    ("UNIDAD DE MEDIDA DE TARA", cod_unidad),
    ("UNIDAD PESO BRUTO", cod_unidad),
    ("UNIDAD PESO NETO", cod_unidad),
    ("TIPO DE BULTO", cod_bulto),
]


def revisar_set_exportacion(sets: list[SetExp]) -> list[dict]:
    """Traduce a código los textos de Aduana del set SIN generar ni firmar nada.

    Revisa exactamente lo que resuelve docs_desde_set (T110; las NC/ND copian
    los datos del documento que referencian), para avisar en la web qué textos
    no están en las tablas de Aduana (o son ambiguos) antes de gastar folios.
    La unidad de los ítems NO se revisa: va como texto libre en UnmdItem.
    """
    revisiones = []
    for s in sets:
        for c in s.casos:
            campos = []

            def chequear(etiqueta: str, valor: str, fn):
                try:
                    campos.append({"campo": etiqueta, "valor": valor, "ok": True, "codigo": fn(valor), "error": None})
                except (KeyError, ValueError) as e:
                    campos.append({"campo": etiqueta, "valor": valor, "ok": False, "codigo": None,
                                   "error": str(e).strip('"')})

            f = c.campos
            if c.tipo == 110:
                moneda = f.get("MONEDA DE LA OPERACION", "")
                ok = moneda in MONEDAS
                campos.append({"campo": "MONEDA DE LA OPERACION", "valor": moneda, "ok": ok, "codigo": None,
                               "error": None if ok else f"Moneda '{moneda}' no está en la tabla del SII"})
                pais_campo = next((k for k in ("PAIS RECEPTOR Y PAIS DESTINO", "PAIS RECEPTOR", "NACIONALIDAD")
                                   if f.get(k)), None)
                if pais_campo:
                    chequear(pais_campo, f[pais_campo], cod_pais)
                if not c.es_hoteleria:
                    for clave_campo, fn in CAMPOS_ADUANA:
                        if f.get(clave_campo):
                            chequear(clave_campo, f[clave_campo], fn)
                if f.get("FORMA DE PAGO EXPORTACION"):
                    chequear("FORMA DE PAGO EXPORTACION", f["FORMA DE PAGO EXPORTACION"], cod_forma_pago)
                for r in c.referencias_doc:
                    chequear("TIPO DE DOCUMENTO DE REFERENCIA", r, _ref_doc_code)
                if c.recargo_global_pct and not f.get("TOTAL CLAUSULA DE VENTA"):
                    campos.append({"campo": "COMISIONES EN EL EXTRANJERO", "valor": f"{c.recargo_global_pct}%",
                                   "ok": False, "codigo": None,
                                   "error": "Pide comisiones sobre el total de la cláusula, pero el set no trae "
                                            "'TOTAL CLAUSULA DE VENTA'"})
            revisiones.append({
                "set": s.nro_atencion, "caso": c.numero, "tipo": c.tipo,
                "campos": campos,
                "errores": [x for x in campos if not x["ok"]],
            })
    return revisiones


def docs_desde_set(set_exp: SetExp, folios: dict, fecha: str, tipo_cambio: Decimal,
                   receptor_nombre: str = "IMPORTADOR DE PRUEBA",
                   tara: int = 50, peso_bruto: Decimal = Decimal("1000"), peso_neto: Decimal = Decimal("950")) -> list[DocExp]:
    """Convierte los casos del set en DocExp listos para `build_exportacion_dte`.

    `folios` = folio inicial por tipo (se consumen correlativos por tipo). Tara/pesos
    no vienen en el set ("agregue otros datos que estime necesarios"): se informan
    con valores por defecto en las unidades que pide el set.
    """
    usados: dict = {}
    por_caso: dict = {}
    docs: list[DocExp] = []

    def siguiente_folio(tipo: int) -> int:
        usados[tipo] = usados.get(tipo, folios[tipo] - 1) + 1
        return usados[tipo]

    for c in set_exp.casos:
        f = c.campos
        if c.tipo == 110:
            moneda = f.get("MONEDA DE LA OPERACION", "")
            if moneda not in MONEDAS:
                raise ValueError(f"Caso {c.numero}: moneda '{moneda}' no está en TipMonType del SII")
            items = [ItemExp(nombre=it.nombre, cantidad=it.cantidad, precio=it.precio, unidad=it.unidad or "U",
                             valor_linea=it.valor_linea, descuento_pct=c.descuento_linea.get(n),
                             recargo_pct=c.recargo_linea_pct)
                     for n, it in enumerate(c.items, 1)]
            ind_servicio = "4" if c.es_hoteleria else ("3" if c.es_servicio else "")
            pais_txt = f.get("PAIS RECEPTOR Y PAIS DESTINO") or f.get("PAIS RECEPTOR") or f.get("NACIONALIDAD", "")
            pais = str(cod_pais(pais_txt)) if pais_txt else ""
            receptor = ReceptorExp(receptor_nombre, "SIN DIRECCION", pais_txt.title() if pais_txt else "",
                                   nacionalidad=pais if f.get("NACIONALIDAD") else "")
            ad = AduanaExp(cod_mod_venta="")
            if not c.es_hoteleria:
                if f.get("MODALIDAD DE VENTA"):
                    ad.cod_mod_venta = str(cod_modalidad(f["MODALIDAD DE VENTA"]))
                elif not c.es_servicio:
                    ad.cod_mod_venta = "1"
                if f.get("CLAUSULA DE VENTA DE EXPORTACION"):
                    ad.cod_clau_venta = str(cod_clausula(f["CLAUSULA DE VENTA DE EXPORTACION"]))
                if f.get("TOTAL CLAUSULA DE VENTA"):
                    ad.tot_clau_venta = _num(f["TOTAL CLAUSULA DE VENTA"])
                if f.get("VIA DE TRANSPORTE"):
                    ad.cod_via_transp = str(cod_via(f["VIA DE TRANSPORTE"]))
                if f.get("PUERTO DE EMBARQUE"):
                    ad.cod_pto_embarque = str(cod_puerto(f["PUERTO DE EMBARQUE"]))
                if f.get("PUERTO DE DESEMBARQUE"):
                    ad.cod_pto_desemb = str(cod_puerto(f["PUERTO DE DESEMBARQUE"]))
                if f.get("UNIDAD DE MEDIDA DE TARA"):
                    ad.tara = tara
                    ad.cod_unid_tara = str(cod_unidad(f["UNIDAD DE MEDIDA DE TARA"]))
                if f.get("UNIDAD PESO BRUTO"):
                    ad.peso_bruto = peso_bruto
                    ad.cod_unid_peso = str(cod_unidad(f["UNIDAD PESO BRUTO"]))
                if f.get("UNIDAD PESO NETO"):
                    ad.peso_neto = peso_neto
                    ad.cod_unid_peso_neto = str(cod_unidad(f["UNIDAD PESO NETO"]))
                if f.get("TOTAL BULTOS"):
                    ad.tot_bultos = int(_num(f["TOTAL BULTOS"]))
                if f.get("TIPO DE BULTO"):
                    ad.cod_tpo_bultos = str(cod_bulto(f["TIPO DE BULTO"]))
                if f.get("FLETE"):
                    ad.mnt_flete = _num(f["FLETE"])
                if f.get("SEGURO"):
                    ad.mnt_seguro = _num(f["SEGURO"])
                ad.cod_pais_recep = pais
                ad.cod_pais_destin = pais
            recargos = []
            # Orden de líneas DscRcgGlobal: primero la comisión (% del total de la
            # cláusula), luego flete y seguro. El SII compara la línea 1 con la
            # comisión (reparo "Linea 1 de Descuento/Recargo Global No Cuadran").
            if c.recargo_global_pct and not ad.tot_clau_venta:
                raise ValueError(f"Caso {c.numero}: pide comisiones del {c.recargo_global_pct}% del total de la "
                                 "cláusula pero el set no trae 'TOTAL CLAUSULA DE VENTA'")
            if c.recargo_global_pct:
                recargos.append(RecargoGlobal("COMISIONES EN EL EXTRANJERO",
                                              (ad.tot_clau_venta * c.recargo_global_pct / 100).quantize(D2, ROUND_HALF_UP)))
            # (**) flete y seguro: en el encabezado Y como dos líneas de recargo global
            if ad.mnt_flete:
                recargos.append(RecargoGlobal("FLETE", ad.mnt_flete))
            if ad.mnt_seguro:
                recargos.append(RecargoGlobal("SEGURO", ad.mnt_seguro))
            refs = [RefExp(_ref_doc_code(r), "1", fecha, "", r[:90]) for r in c.referencias_doc]
            if c.es_hoteleria and not any(r.tipo_doc == "813" for r in refs):
                # Hotelería: el SII exige 2 referencias (SET + pasaporte del huésped, 813).
                refs.append(RefExp("813", PASAPORTE_DEFECTO, fecha, "", "PASAPORTE"))
            fma = str(cod_forma_pago(f["FORMA DE PAGO EXPORTACION"])) if f.get("FORMA DE PAGO EXPORTACION") else ""
            doc = DocExp(110, siguiente_folio(110), fecha, items, moneda, tipo_cambio, receptor, ad,
                         ind_servicio=ind_servicio, fma_pag_exp=fma, referencias=refs, recargos_globales=recargos)
        else:
            ref = por_caso.get(c.referencia_caso)
            if ref is None:
                raise ValueError(f"Caso {c.numero} referencia al caso {c.referencia_caso}, que no está antes en el set")
            razon = c.razon_referencia.upper()
            def copia(x: ItemExp, cantidad=None, precio=None) -> ItemExp:
                return ItemExp(x.nombre, cantidad if cantidad is not None else x.cantidad,
                               precio if precio is not None else x.precio, x.unidad,
                               None, x.descuento_pct, x.recargo_pct)
            recargos = []
            if c.tipo == 112:
                cod_ref = "3" if "DEVOLUCION" in razon else ("2" if "CORRIGE" in razon else "1")
                if c.items:
                    # NC por devolución: cantidades del set, precio (y % de línea) de la factura
                    items = []
                    for it in c.items:
                        base = next((x for x in ref.items if x.nombre.upper() == it.nombre.upper()), ref.items[0])
                        if it.valor_linea is not None:
                            # NC parcial de un servicio: el set da el nuevo valor de línea
                            items.append(copia(base, Decimal(1), it.valor_linea))
                        else:
                            items.append(copia(base, it.cantidad))
                else:
                    # NC que anula la factura completa: mismos ítems y recargos globales
                    items = [copia(x) for x in ref.items]
                    recargos = list(ref.recargos_globales)
            else:
                # ND que anula la NC: mismos ítems, % de línea y recargos globales de la NC
                items = [copia(x) for x in ref.items]
                recargos = list(ref.recargos_globales)
                cod_ref = "1"
            doc = DocExp(c.tipo, siguiente_folio(c.tipo), fecha, items, ref.moneda, tipo_cambio, ref.receptor,
                         AduanaExp(cod_mod_venta=ref.aduana.cod_mod_venta, cod_pais_recep=ref.aduana.cod_pais_recep,
                                   cod_pais_destin=ref.aduana.cod_pais_destin),
                         ind_servicio=ref.ind_servicio, fma_pag_exp=ref.fma_pag_exp,
                         referencias=[RefExp(str(ref.tipo), str(ref.folio), fecha, cod_ref, c.razon_referencia[:90])],
                         recargos_globales=recargos)
        # Primera referencia siempre SET / CASO (instrucciones del set de pruebas)
        doc.referencias.insert(0, RefExp("SET", c.numero.split("-")[-1], fecha, "", f"CASO {c.numero}"))
        por_caso[c.numero] = doc
        docs.append(doc)
    return docs

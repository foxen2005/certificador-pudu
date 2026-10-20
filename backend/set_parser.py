"""
Parsea el archivo SIISetDePruebas*.txt que entrega el SII.
Extrae los casos de prueba: tipo de documento, ítems, descuentos, referencias
y las secciones de Libro de Ventas / Libro de Compras.
"""
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ItemSet:
    nombre: str
    cantidad: float
    precio_unitario: float
    descuento_pct: Optional[float] = None
    es_exento: bool = False
    # Columna "UNIDAD MEDIDA" del set (ej. "Hora" en el SET FACTURA EXENTA) → UnmdItem
    unidad: Optional[str] = None


@dataclass
class CasoSet:
    numero: str          # "4779246-1"
    tipo_doc: int        # 33, 56, 61, 52, etc.
    items: list[ItemSet] = field(default_factory=list)
    descuento_global_pct: Optional[float] = None
    # Para NC/ND
    referencia_caso: Optional[str] = None
    razon_referencia: Optional[str] = None
    # Para T52 (Guía de Despacho)
    ind_traslado: Optional[int] = None
    # Factura de Compra (T46) y NC/ND de su cadena: retención total del IVA
    # (cambio de sujeto). Se resuelve en main.py recorriendo las referencias.
    con_retencion: bool = False
    # Encabezado "SET ... - NUMERO DE ATENCION" bajo el que aparece el caso
    # (normalizado, ej. "SET BASICO", "SET FACTURA DE COMPRA"). None si el
    # archivo no trae encabezados. Separa el set de Factura de Compra del básico.
    seccion: Optional[str] = None


@dataclass
class LibroCompraItem:
    tipo_doc: str        # "FACTURA ELECTRONICA", etc.
    folio: int
    observacion: str = ""
    fecha: Optional[str] = None          # "YYYY-MM-DD"
    rut_emisor: Optional[str] = None
    razon_social: Optional[str] = None
    monto_exento: Optional[int] = None
    monto_afecto: Optional[int] = None   # = monto neto
    monto_iva: Optional[int] = None
    monto_total: Optional[int] = None


@dataclass
class SetDePruebas:
    nro_atencion_basico: Optional[str] = None
    nro_atencion_ventas: Optional[str] = None
    nro_atencion_compras: Optional[str] = None
    # Set de DTE "SET FACTURA DE COMPRA" (T46 → NC → ND), distinto del Libro de Compras
    nro_atencion_factura_compra: Optional[str] = None
    # "SET FACTURA EXENTA" (T34 → NC/ND): opcional, va junto al set básico
    nro_atencion_exenta: Optional[str] = None
    casos: list[CasoSet] = field(default_factory=list)
    libro_compras: list[LibroCompraItem] = field(default_factory=list)
    fct_prop_iva_uso_comun: float = 0.6   # factor de proporcionalidad IVA uso común


TIPO_DOC_MAP = {
    "FACTURA ELECTRONICA": 33,
    "FACTURA NO AFECTA O EXENTA ELECTRONICA": 34,
    "FACTURA NO AFECTA": 34,
    "GUIA DE DESPACHO ELECTRONICA": 52,
    "NOTA DE DEBITO ELECTRONICA": 56,
    "NOTA DE CREDITO ELECTRONICA": 61,
    "FACTURA DE COMPRA ELECTRONICA": 46,
    "LIQUIDACION FACTURA ELECTRONICA": 43,
}

# Tipos de documento que van en libro de compras (por nombre normalizado)
LIBRO_COMPRAS_TIPOS = {
    "FACTURA ELECTRONICA": 33,
    "FACTURA": 33,
    "FACTURA DE COMPRA ELECTRONICA": 46,
    "FACTURA DE COMPRA": 46,
    "NOTA DE CREDITO ELECTRONICA": 61,
    "NOTA DE CREDITO": 61,
    "NOTA DE DEBITO ELECTRONICA": 56,
    "NOTA DE DEBITO": 56,
    "LIQUIDACION FACTURA ELECTRONICA": 43,
}


def _normalize(s: str) -> str:
    return re.sub(r'[ÁÉÍÓÚÜ]', lambda m: {'Á':'A','É':'E','Í':'I','Ó':'O','Ú':'U','Ü':'U'}[m.group()],
                  s.upper().strip())


def _parse_monto(s: str) -> Optional[int]:
    """Convierte string de monto a int, admite negativos y puntos de miles."""
    s = s.strip().replace('.', '').replace(',', '').replace('$', '').replace(' ', '')
    try:
        return int(s)
    except ValueError:
        return None


def _parse_fecha(s: str) -> Optional[str]:
    """Normaliza fecha a YYYY-MM-DD desde DD-MM-YYYY, DD/MM/YYYY o YYYY-MM-DD."""
    s = s.strip()
    m = re.match(r'^(\d{2})[/-](\d{2})[/-](\d{4})$', s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', s)
    if m:
        return s
    return None


def parse_set_pruebas(content: str) -> SetDePruebas:
    result = SetDePruebas()
    lines = content.splitlines()

    # Extraer factor de proporcionalidad IVA uso común (OBSERVACIONES GENERALES)
    m_fct = re.search(
        r'FACTOR\s+DE\s+PROPORCIONALIDAD[^0-9]+([0-9]+[.,][0-9]+)',
        _normalize(content)
    )
    if m_fct:
        result.fct_prop_iva_uso_comun = float(m_fct.group(1).replace(',', '.'))

    # Extraer números de atención
    for line in lines:
        ln = _normalize(line)
        m = re.search(r'SET (?:BASICO )?FACTURA DE COMPRA.*NUMERO DE ATENCION[:\s]+(\d+)', ln)
        if m:
            result.nro_atencion_factura_compra = m.group(1)
        m = re.search(r'SET FACTURA (?:NO AFECTA O )?EXENTA.*NUMERO DE ATENCION[:\s]+(\d+)', ln)
        if m:
            result.nro_atencion_exenta = m.group(1)
        m = re.search(r'SET BASICO.*NUMERO DE ATENCION[:\s]+(\d+)', ln)
        if m and 'FACTURA DE COMPRA' not in ln:
            result.nro_atencion_basico = m.group(1)
        m = re.search(r'SET LIBRO DE VENTAS.*NUMERO DE ATENCION[:\s]+(\d+)', ln)
        if m:
            result.nro_atencion_ventas = m.group(1)
        m = re.search(r'SET LIBRO DE COMPRAS.*NUMERO DE ATENCION[:\s]+(\d+)', ln)
        if m:
            result.nro_atencion_compras = m.group(1)
        # Formato alternativo: "NUMERO DE ATENCION: 1234567  SET LIBRO DE VENTAS"
        m = re.search(r'NUMERO DE ATENCION[:\s]+(\d+).*SET LIBRO DE VENTAS', ln)
        if m:
            result.nro_atencion_ventas = m.group(1)
        m = re.search(r'NUMERO DE ATENCION[:\s]+(\d+).*SET LIBRO DE COMPRAS', ln)
        if m:
            result.nro_atencion_compras = m.group(1)

    # Máquina de estados principal
    caso_pattern = re.compile(r'^CASO\s+(\S+)', re.IGNORECASE)
    current_caso: Optional[CasoSet] = None
    in_libro_compras = False
    seccion_actual: Optional[str] = None
    # Columnas de la tabla de ítems del caso actual (según su encabezado ITEM ...)
    columnas: Optional[list[str]] = None

    # Estado para el libro de compras (acumula campos por entrada)
    lc_current: Optional[dict] = None

    for raw_line in lines:
        line = raw_line.strip()
        ln = _normalize(line)

        if not line or line.startswith('=') or line.startswith('-'):
            continue

        # ── Encabezado de otro set (p. ej. SET FACTURA DE COMPRA después del
        # libro de compras): cierra la sección anterior. Antes, una vez dentro
        # del libro de compras, el resto del archivo se leía como libro.
        # Basta "SET ..." al inicio: el N° de atención puede venir en otra línea.
        if ln.startswith('SET ') and 'LIBRO DE COMPRAS' not in ln:
            if in_libro_compras and lc_current:
                _flush_lc_entry(lc_current, result)
            in_libro_compras = False
            lc_current = None
            current_caso = None
            seccion_actual = re.split(r'\s+-\s+|\s+NUMERO DE ATENCION', ln)[0].strip()
            continue

        # ── Detectar inicio del libro de compras ──────────────────────────────
        # Solo en un encabezado (no en una observación que lo mencione).
        if 'LIBRO DE COMPRAS' in ln and (ln.startswith('SET ') or 'NUMERO DE ATENCION' in ln):
            in_libro_compras = True
            current_caso = None
            lc_current = None
            continue

        if in_libro_compras:
            lc_current = _parse_libro_compras_line(ln, line, result, lc_current)
            continue

        # ── Detectar inicio de CASO ───────────────────────────────────────────
        m = caso_pattern.match(line)
        if m:
            current_caso = CasoSet(numero=m.group(1), tipo_doc=33, seccion=seccion_actual)
            result.casos.append(current_caso)
            columnas = None
            continue

        if current_caso is None:
            continue

        # Tipo de documento
        if ln.startswith('DOCUMENTO'):
            doc_text = re.sub(r'^DOCUMENTO\s*', '', ln).strip()
            for key, val in TIPO_DOC_MAP.items():
                if key in doc_text:
                    current_caso.tipo_doc = val
                    break
            continue

        # Referencia (para NC/ND)
        if ln.startswith('REFERENCIA') and 'RAZON' not in ln:
            m2 = re.search(r'CASO\s+(\S+)', ln)
            if m2:
                current_caso.referencia_caso = m2.group(1)
            continue

        if ln.startswith('RAZON REFERENCIA'):
            current_caso.razon_referencia = re.sub(r'^RAZON REFERENCIA\s*', '', line).strip()
            continue

        # Descuento global
        m_dg = re.search(r'DESCUENTO GLOBAL[^%\d]*(\d+(?:[.,]\d+)?)\s*%', ln)
        if m_dg:
            current_caso.descuento_global_pct = float(m_dg.group(1).replace(',', '.'))
            continue

        # IndTraslado para T52 (Guía de Despacho)
        m_tr = re.search(r'TIPO\s+(?:DE\s+)?TRASLADO[:\s]+(\d)', ln)
        if m_tr:
            current_caso.ind_traslado = int(m_tr.group(1))
            continue

        # Encabezado de la tabla de ítems ("ITEM  CANTIDAD  UNIDAD MEDIDA  VALOR UNITARIO")
        cols = _columnas_item(ln)
        if cols is not None:
            columnas = cols
            continue

        # Con encabezado reconocido se lee por columnas; si no calza, la lógica de siempre.
        item = _parse_item_por_columnas(line, columnas) if columnas else None
        if item is None:
            item = _try_parse_item(line)
        if item:
            current_caso.items.append(item)

    # Finalizar última entrada de libro de compras si quedó pendiente
    if in_libro_compras and lc_current:
        _flush_lc_entry(lc_current, result)

    return result


def _flush_lc_entry(entry: dict, result: SetDePruebas) -> None:
    """Persiste un dict acumulado de compra en result.libro_compras."""
    tipo = entry.get("tipo_doc")
    folio = entry.get("folio")
    if not tipo or not folio:
        return
    result.libro_compras.append(LibroCompraItem(
        tipo_doc=tipo,
        folio=int(folio),
        observacion=entry.get("observacion", ""),
        fecha=entry.get("fecha"),
        rut_emisor=entry.get("rut_emisor"),
        razon_social=entry.get("razon_social"),
        monto_exento=entry.get("monto_exento"),
        monto_afecto=entry.get("monto_afecto"),
        monto_iva=entry.get("monto_iva"),
        monto_total=entry.get("monto_total"),
    ))


def _parse_libro_compras_line(ln: str, raw_line: str, result: SetDePruebas,
                               current: Optional[dict]) -> Optional[dict]:
    """
    Parser de libro de compras multi-línea (acumula campos por entrada).
    Soporta formato clave-valor y formato tabular en una sola línea.
    Retorna el dict acumulado (puede ser el mismo, uno nuevo, o None).
    """
    # Inicio de nueva entrada: COMPRA <N>, CASO LC-<N>, o CASO <N>
    # Restringir a que después haya dígitos para evitar matchear observaciones
    # tipo "COMPRA CON RETENCION TOTAL DEL IVA"
    if re.match(r'^(?:COMPRA|CASO)\s+(?:LC-)?\d', ln, re.IGNORECASE):
        if current:
            _flush_lc_entry(current, result)
        return {}

    # ── Formato clave-valor ───────────────────────────────────────────────────
    if current is None:
        current = {}

    # TIPO DOCUMENTO / DOCUMENTO
    m = re.match(r'^(?:TIPO\s+)?DOCUMENTO[:\s]+(.+)', ln)
    if m:
        current["tipo_doc"] = m.group(1).strip()
        return current

    # FOLIO
    m = re.match(r'^FOLIO[:\s]+(\d+)', ln)
    if m:
        current["folio"] = m.group(1)
        return current

    # FECHA
    m = re.match(r'^FECHA[:\s]+(\S+)', ln)
    if m:
        current["fecha"] = _parse_fecha(m.group(1))
        return current

    # RUT EMISOR / RUT PROVEEDOR / RUT
    m = re.match(r'^(?:RUT\s+(?:EMISOR|PROVEEDOR)|RUT)[:\s]+(\d[\d.]*-[\dkK])', ln)
    if m:
        current["rut_emisor"] = m.group(1).replace('.', '')
        return current

    # RAZON SOCIAL / NOMBRE / PROVEEDOR
    m = re.match(r'^(?:RAZON SOCIAL|NOMBRE|PROVEEDOR)[:\s]+(.+)', ln)
    if m:
        current["razon_social"] = raw_line.split(':', 1)[-1].strip() if ':' in raw_line else m.group(1)
        return current

    # MONTO NETO / MONTO AFECTO
    m = re.match(r'^MONTO\s+(?:NETO|AFECTO)[:\s]+(-?\d[\d.]*)', ln)
    if m:
        current["monto_afecto"] = _parse_monto(m.group(1))
        return current

    # MONTO EXENTO
    m = re.match(r'^MONTO\s+EXENTO[:\s]+(-?\d[\d.]*)', ln)
    if m:
        current["monto_exento"] = _parse_monto(m.group(1))
        return current

    # IVA
    m = re.match(r'^IVA[:\s]+(-?\d[\d.]*)', ln)
    if m:
        current["monto_iva"] = _parse_monto(m.group(1))
        return current

    # MONTO TOTAL / TOTAL
    m = re.match(r'^(?:MONTO\s+)?TOTAL[:\s]+(-?\d[\d.]*)', ln)
    if m:
        current["monto_total"] = _parse_monto(m.group(1))
        return current

    # ── Formato PUDU: montos en línea separada (sin etiqueta) ──
    # Ej: "        48406"  o  "  10362    10723"
    if current and current.get("folio"):
        m_dos = re.match(r'^\s*(-?\d[\d.]*)\s+(-?\d[\d.]*)\s*$', ln)
        if m_dos:
            current["monto_exento"] = _parse_monto(m_dos.group(1))
            current["monto_afecto"] = _parse_monto(m_dos.group(2))
            return current
        m_uno = re.match(r'^\s*(-?\d[\d.]*)\s*$', ln)
        if m_uno:
            current["monto_afecto"] = _parse_monto(m_uno.group(1))
            return current

    # Observación: primera línea de texto no reconocida después de que el folio está
    # definido y antes de que lleguen los montos. Identifica casos especiales como
    # "FACTURA CON IVA USO COMUN" o "ENTREGA GRATUITA DEL PROVEEDOR".
    if current.get("folio") and not current.get("observacion") and not current.get("monto_afecto"):
        if ln and not re.match(r'^\d', ln):
            current["observacion"] = raw_line.strip()
            return current

    # ── Formato tabular en una línea: TIPO  FOLIO  [RUT]  [NETO]  [IVA]  [TOTAL] ──
    # Ej: "FACTURA ELECTRONICA   1234   76543210-K   500000   95000   595000"
    tab_m = re.match(
        r'^(FACTURA(?:\s+(?:ELECTRONICA|DE COMPRA(?:\s+ELECTRONICA)?|NO AFECTA(?:\s+O EXENTA)?(?:\s+ELECTRONICA)?))?'
        r'|NOTA\s+DE\s+(?:CREDITO|DEBITO)(?:\s+ELECTRONICA)?'
        r'|LIQUIDACION\s+FACTURA(?:\s+ELECTRONICA)?)'
        r'\s+(\d+)'               # folio
        r'(?:\s+(\d[\d.]*-[\dkK]))?'  # RUT opcional
        r'(?:\s+(-?\d[\d.]*))?'       # neto opcional
        r'(?:\s+(-?\d[\d.]*))?'       # iva opcional
        r'(?:\s+(-?\d[\d.]*))?',      # total opcional
        ln
    )
    if tab_m:
        if current:
            _flush_lc_entry(current, result)
        entry: dict = {"tipo_doc": tab_m.group(1).strip()}
        entry["folio"] = tab_m.group(2)
        if tab_m.group(3):
            entry["rut_emisor"] = tab_m.group(3).replace('.', '')
        if tab_m.group(4):
            entry["monto_afecto"] = _parse_monto(tab_m.group(4))
        if tab_m.group(5):
            entry["monto_iva"] = _parse_monto(tab_m.group(5))
        if tab_m.group(6):
            entry["monto_total"] = _parse_monto(tab_m.group(6))
        # Con montos en la misma línea → flush inmediato
        # Sin montos → dejar abierto para capturar montos en líneas siguientes
        if tab_m.group(4) or tab_m.group(5) or tab_m.group(6):
            _flush_lc_entry(entry, result)
            return {}
        return entry

    return current


# Columnas de la tabla de ítems del set → campo de ItemSet. "VALOR UNITARIO" es el
# nombre que usa el SET FACTURA EXENTA; "PRECIO UNITARIO", el del set básico.
_COLS_ITEM = {
    "CANTIDAD": "cantidad",
    "UNIDAD MEDIDA": "unidad",
    "PRECIO UNITARIO": "precio",
    "VALOR UNITARIO": "precio",
    "DESCUENTO ITEM": "descuento",
}
# Separador de columnas: cualquier espacio con un tabulador, o 2+ espacios.
_SEP_COLS = re.compile(r'\s*\t\s*|\s{2,}')


def _columnas_item(ln: str) -> Optional[list[str]]:
    """Si `ln` es el encabezado de la tabla de ítems, devuelve sus columnas
    (sin ITEM), ej. ["cantidad", "unidad", "precio"]. Si no, None."""
    campos = _SEP_COLS.split(ln.strip())
    if len(campos) < 2 or campos[0] != "ITEM":
        return None
    if not all(c in _COLS_ITEM for c in campos[1:]):
        return None
    return [_COLS_ITEM[c] for c in campos[1:]]


def _num_set(s: str) -> float:
    return float(s.replace('.', '').replace(',', '.'))


def _parse_item_por_columnas(line: str, columnas: list[str]) -> Optional[ItemSet]:
    """Lee una línea de ítem según las columnas del encabezado. Resuelve los casos
    que la lectura por patrón no entendía: la columna de texto UNIDAD MEDIDA
    ("HORAS PROGRAMADOR  12  Hora  6991"), un solo tabulador como separador y las
    NC con solo VALOR UNITARIO (cantidad = 0 → se toma de la factura referenciada:
    "en NC por diferencia de precio, la diferencia se aplica a todas las unidades",
    Instrucciones del Set de Pruebas). Devuelve None si la línea no calza."""
    campos = _SEP_COLS.split(line.strip())
    if len(campos) < 2 or len(campos) > len(columnas) + 1:
        return None
    nombre = campos[0].strip()
    if len(nombre) < 2:
        return None
    # El separador junta tabs y espacios, así que una celda en blanco correría
    # las demás columnas (ej. cantidad vacía → el valor quedaría como cantidad).
    # Solo el descuento puede faltar (va al final); si falta otra columna, la
    # línea es ambigua: mejor un error claro que un monto inventado.
    # Solo es fila de ítem si trae algún número; "CLAVE: valor" u otro texto no.
    valores = [c.strip() for c in campos[1:]]
    if nombre.endswith(':') or not any(re.fullmatch(r'[\d.,]+%?', v) for v in valores):
        return None
    obligatorias = [c for c in columnas if c != "descuento"]
    if len(campos) - 1 < len(obligatorias):
        raise ValueError(f"La línea '{_SEP_COLS.sub(' | ', line.strip())}' no calza con las columnas "
                         f"del set ({', '.join(columnas)}): falta un valor.")
    vals = dict(zip(columnas, (c.strip() for c in campos[1:])))
    try:
        cantidad = _num_set(vals["cantidad"]) if vals.get("cantidad") else 0.0
        precio = _num_set(vals["precio"]) if vals.get("precio") else 0.0
        dscto = (float(vals["descuento"].rstrip('%').strip().replace(',', '.'))
                 if vals.get("descuento") else None)
    except ValueError:
        return None   # columnas corridas (ej. falta la unidad): que decida el patrón
    unidad = vals.get("unidad") or None
    if unidad and re.fullmatch(r'[\d.,]+', unidad):
        raise ValueError(f"La línea '{_SEP_COLS.sub(' | ', line.strip())}' no calza con las columnas "
                         f"del set ({', '.join(columnas)}): la unidad de medida es un número.")
    if cantidad == 0 and precio == 0:
        return None
    return ItemSet(nombre=nombre, cantidad=cantidad, precio_unitario=precio, descuento_pct=dscto,
                   es_exento='EXENTO' in nombre.upper(), unidad=unidad)


def _try_parse_item(line: str) -> Optional[ItemSet]:
    # Intento 1: línea con CANTIDAD + PRECIO [+ DESCUENTO%]
    m = re.match(
        r'^(.+?)\s{2,}(\d[\d.]*)\s+(\d[\d.]*)\s*(?:(\d+(?:[.,]\d+)?)\s*%)?',
        line.rstrip()
    )
    if m:
        nombre = m.group(1).strip()
        if re.match(r'^(ITEM|CODIGO|DESCRIPCION|NOMBRE)\s+(CANTIDAD|CODIGO|DESCRIPCION)', nombre.upper()):
            return None
        try:
            cantidad = float(m.group(2).replace('.', '').replace(',', '.'))
            precio = float(m.group(3).replace('.', '').replace(',', '.'))
        except ValueError:
            return None
        dscto = float(m.group(4).replace(',', '.')) if m.group(4) else None
        es_exento = 'EXENTO' in nombre.upper()
        return ItemSet(nombre=nombre, cantidad=cantidad, precio_unitario=precio,
                       descuento_pct=dscto, es_exento=es_exento)

    # Intento 2: línea con solo CANTIDAD (NC parciales — precio se resuelve del doc referenciado)
    m2 = re.match(r'^(.+?)\s{2,}(\d[\d.]*)\s*$', line.rstrip())
    if m2:
        nombre = m2.group(1).strip()
        if re.match(r'^(ITEM|CODIGO|DESCRIPCION|NOMBRE)\s+(CANTIDAD|CODIGO|DESCRIPCION|PRECIO)', nombre.upper()):
            return None
        if len(nombre) < 3:
            return None
        try:
            cantidad = float(m2.group(2).replace('.', '').replace(',', '.'))
        except ValueError:
            return None
        es_exento = 'EXENTO' in nombre.upper()
        return ItemSet(nombre=nombre, cantidad=cantidad, precio_unitario=0.0, es_exento=es_exento)

    return None

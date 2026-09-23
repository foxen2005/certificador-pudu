"""Genera backend/aduana_tablas.py desde los seeds de pos-matic_no (tablas oficiales de Aduana)."""
import re, json
M = r"D:\PUDU\pos-matic_no\supabase\migrations"
sql = open(f"{M}\\20260826140100_aduana_tablas_referencia.sql", encoding="utf-8").read() + "\n" + \
      open(f"{M}\\20260826140200_aduana_seed_paises_monedas_bultos_puertos.sql", encoding="utf-8").read()

def bloque(tabla):
    ms = list(re.finditer(r"INSERT INTO public\." + tabla + r"\s*\(([^)]*)\)\s*VALUES\s*((?:'(?:[^']|'')*'|[^';])*);", sql, re.S | re.I))
    if not ms:
        return [], []
    cols = [c.strip() for c in ms[0].group(1).split(",")]
    rows = []
    for m in ms:  # el seed parte algunas tablas en varios INSERT
        rows += [x[1:-1] for x in re.findall(r"\((?:'(?:[^']|'')*'|[^()'])*\)", m.group(2))]
    out = []
    for r in rows:
        vals = re.findall(r"'((?:[^']|'')*)'|(NULL)|(-?\d+(?:\.\d+)?)", r)
        out.append([v[0].replace("''", "'").replace("&amp;", "&") if v[0] else (None if v[1] else v[2]) for v in vals])
    return cols, [r for r in out if len(r) >= 2]

tablas = {}
for t in ["paises_aduana", "puertos_aduana", "vias_transporte_aduana", "monedas_aduana", "clausulas_venta_aduana", "tipos_bulto_aduana", "modalidad_venta_aduana"]:
    cols, rows = bloque(t)
    tablas[t] = (cols, rows)
    print(t, cols, len(rows), rows[:2])

def norm(s):
    import unicodedata
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper().strip()

paises = {norm(r[1]): int(r[0]) for r in tablas["paises_aduana"][1] if r[1]}
puertos = {norm(r[1]): int(r[0]) for r in tablas["puertos_aduana"][1] if r[1]}
vias = {norm(r[1]): int(r[0]) for r in tablas["vias_transporte_aduana"][1]}
monedas = {norm(r[2]): {"nombre": r[1], "sii": r[2]} for r in tablas["monedas_aduana"][1]}
clausulas = {norm(r[1]): int(r[0]) for r in tablas["clausulas_venta_aduana"][1]}
bultos = {norm(r[1]): int(r[0]) for r in tablas["tipos_bulto_aduana"][1] if r[1]}
modalidad = {norm(r[2]): int(r[0]) for r in tablas["modalidad_venta_aduana"][1]}
modalidad.update({norm(r[1]): int(r[0]) for r in tablas["modalidad_venta_aduana"][1]})

out = '''"""Tablas de códigos del Servicio Nacional de Aduanas usadas en documentos de
exportación (CodPaisRecep, CodPtoEmbarque, CodViaTransp, CodClauVenta, CodModVenta,
CodTpoBultos, unidades de medida, FmaPagExp).

GENERADO desde los seeds oficiales de pos-matic_no
(supabase/migrations/20260826140100_aduana_tablas_referencia.sql y
20260826140200_aduana_seed_paises_monedas_bultos_puertos.sql). Las unidades de
medida y formas de pago vienen de la tabla de Aduana usada en el DUS (misma que
LibreDTE); KN=6 coincide con SII_pudu_Server (UNIDAD_MEDIDA_ADUANA_KG='06').
Claves normalizadas: mayúsculas sin acentos.
"""
import re
import unicodedata


def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper().strip()


_PAREN = re.compile(r"\\([^)]*\\)")
_SEPARADORES = re.compile(r"[.\\-_/,;]+")
_ESPACIOS = re.compile(r"\\s+")


def clave(s: str) -> str:
    """Normalización tolerante para comparar: sin acentos, sin puntos ni guiones
    ("U.S.A." → "U S A") y sin sufijos entre paréntesis que solo existen en la
    tabla de Aduana ("REPUBLICA CHECA (D)" → "REPUBLICA CHECA")."""
    k = _PAREN.sub(" ", norm(s))
    k = _SEPARADORES.sub(" ", k)
    return _ESPACIOS.sub(" ", k).strip()


PAISES = %s

PUERTOS = %s

VIAS_TRANSPORTE = %s

CLAUSULAS_VENTA = %s

MODALIDAD_VENTA = %s

TIPOS_BULTO = %s

# Unidades de medida Aduana (tabla del DUS)
UNIDADES_MEDIDA = {
    "TMB": 1, "QMB": 2, "MKWH": 3, "TMN": 4, "KLT": 5, "KN": 6, "KB": 7, "QMN": 8,
    "MKN": 9, "U": 10, "DOC": 11, "U(JGO)": 12, "MU": 13, "MT": 14, "MT2": 15,
    "MCUB": 16, "PAR": 17, "KNFC": 18, "CARTON": 19, "KWH": 20, "GN": 21, "GB": 22,
    "BAR": 23, "LT": 24, "S.U.M.": 99,
}

# Formas de pago de exportación Aduana (FmaPagExp). Formato DTE: 21 = sin pago
# ("muestras sin carácter comercial"), y con 21 el MntTotal del DTE va en 0.
FORMAS_PAGO_EXP = {
    "COB1": 1, "COBRANZA": 1, "ACRED": 2, "ACREDITIVO": 2, "COB2": 11, "ACRED2": 12,
    "SIN PAGO": 21, "ANTICIPO": 32,
}

# Alias y acrónimos frecuentes en los sets del SII → nombre de la tabla de Aduana.
# Las claves se comparan con clave() (sin puntos ni acentos), así que "EE.UU.",
# "EE UU" y "EEUU" caen todos en la misma entrada.
_ALIAS_RAW = {
    # Vía de transporte / modalidad / bultos
    "AEREO": "AEREO", "MARITIMA, FLUVIAL Y LACUSTRE": "MARITIMA, FLUVIAL Y LACUSTRE",
    "CARRETERO": "CARRETERO / TERRESTRE", "TERRESTRE": "CARRETERO / TERRESTRE",
    "A FIRME": "A FIRME", "FIRME": "A FIRME",
    "EN CONSIGNACION CON UN MINIMO A FIRME": "EN CONSIGNACION CON UN MINIMO A FIRME",
    "CONTENEDOR REFRIGERADO": "CONTENEDOR REFRIGERADO 20 PIES",
    # Países: acrónimos y nombres cortos de uso corriente
    "USA": "ESTADOS UNIDOS DE AMERICA", "U.S.A.": "ESTADOS UNIDOS DE AMERICA",
    "US": "ESTADOS UNIDOS DE AMERICA", "EEUU": "ESTADOS UNIDOS DE AMERICA",
    "EE.UU.": "ESTADOS UNIDOS DE AMERICA", "EUA": "ESTADOS UNIDOS DE AMERICA",
    "ESTADOS UNIDOS": "ESTADOS UNIDOS DE AMERICA",
    "UNITED STATES": "ESTADOS UNIDOS DE AMERICA",
    "UK": "REINO UNIDO", "U.K.": "REINO UNIDO", "R. UNIDO": "REINO UNIDO",
    "GRAN BRETANA": "REINO UNIDO", "INGLATERRA": "REINO UNIDO",
    "REINO UNIDO DE GRAN BRETANA E IRLANDA DEL NORTE": "REINO UNIDO",
    "P. BAJOS": "PAISES BAJOS", "HOLANDA": "PAISES BAJOS", "NETHERLANDS": "PAISES BAJOS",
    "R.P. CHINA": "CHINA", "RP CHINA": "CHINA", "REPUBLICA POPULAR CHINA": "CHINA",
    "CHINA POPULAR": "CHINA", "R. CHECA": "REPUBLICA CHECA (D)",
    "REPUBLICA CHECA": "REPUBLICA CHECA (D)", "CHEQUIA": "REPUBLICA CHECA (D)",
    "RUSIA": "RUSIA (B)", "FEDERACION RUSA": "RUSIA (B)",
    "TAIWAN": "TAIWAN (FORMOSA)", "FORMOSA": "TAIWAN (FORMOSA)",
    "BIRMANIA": "MYANMAR (EX BIRMANIA)", "MYANMAR": "MYANMAR (EX BIRMANIA)",
    "EAU": "EMIRATOS ARABES UNIDOS", "E.A.U.": "EMIRATOS ARABES UNIDOS",
    "EMIRATOS ARABES": "EMIRATOS ARABES UNIDOS",
    "ALEMANIA FEDERAL": "ALEMANIA", "R.F. ALEMANA": "ALEMANIA",
    "COREA DEL SUR": "COREA DEL SUR", "COREA DEL NORTE": "COREA DEL NORTE",
    # Puertos escritos abreviados
    "S. ANTONIO": "SAN ANTONIO", "SN ANTONIO": "SAN ANTONIO", "VALPO": "VALPARAISO",
    "PTO MONTT": "PUERTO MONTT", "PTA ARENAS": "PUNTA ARENAS",
    "NUEVA YORK": "NEW YORK", "SHANGHAI": "SHANGAI",
}
_ALIAS = {clave(k): v for k, v in _ALIAS_RAW.items()}

# Índice tolerante por tabla: clave() → [(nombre oficial, código), ...]
_INDICES: dict = {}


def _indice(tabla: dict) -> dict:
    idx = _INDICES.get(id(tabla))
    if idx is None:
        idx = {}
        for nombre, cod in tabla.items():
            idx.setdefault(clave(nombre), []).append((nombre, cod))
        _INDICES[id(tabla)] = idx
    return idx


def _unico(cands: list, texto: str, que: str) -> int:
    if len({c for _, c in cands}) == 1:
        return cands[0][1]
    nombres = sorted({n for n, _ in cands})
    muestra = " o ".join(nombres[:4]) + (", ..." if len(nombres) > 4 else "")
    raise KeyError(f"{que} '{texto}' es ambiguo: puede ser {muestra}. Escribe el nombre exacto de la tabla de Aduana")


def _buscar(tabla: dict, texto: str, que: str) -> int:
    # 1. nombre exacto de la tabla
    if norm(texto) in tabla:
        return tabla[norm(texto)]
    # 2. acrónimo o alias conocido
    t = texto
    alias = _ALIAS.get(clave(texto))
    if alias:
        if norm(alias) in tabla:
            return tabla[norm(alias)]
        t = alias
    k = clave(t)
    if not k:
        raise KeyError(f"Falta {que}")
    idx = _indice(tabla)
    # 3. coincidencia tolerante (sin puntos, sin "(D)"/"(B)" de la tabla)
    if k in idx:
        return _unico(idx[k], texto, que)
    # 4. sigla escrita con puntos ("C.I.F." → "CIF")
    compacto = k.replace(" ", "")
    if compacto in tabla:
        return tabla[compacto]
    if compacto in idx:
        return _unico(idx[compacto], texto, que)
    # 5. prefijo por palabras completas ("CONTENEDOR REFRIGERADO" → "... 20 PIES")
    cands = [x for kk, v in idx.items()
             if kk.startswith(k + " ") or k.startswith(kk + " ") for x in v]
    if cands:
        return _unico(cands, texto, que)
    raise KeyError(f"{que} '{texto}' no está en la tabla de Aduana")


def cod_pais(t): return _buscar(PAISES, t, "País")
def cod_puerto(t): return _buscar(PUERTOS, t, "Puerto")
def cod_via(t): return _buscar(VIAS_TRANSPORTE, t, "Vía de transporte")
def cod_clausula(t): return _buscar(CLAUSULAS_VENTA, t, "Cláusula de venta")
def cod_modalidad(t): return _buscar(MODALIDAD_VENTA, t, "Modalidad de venta")
def cod_bulto(t): return _buscar(TIPOS_BULTO, t, "Tipo de bulto")
def cod_unidad(t): return _buscar(UNIDADES_MEDIDA, t, "Unidad de medida")
def cod_forma_pago(t): return _buscar(FORMAS_PAGO_EXP, t, "Forma de pago")
''' % tuple(json.dumps(d, ensure_ascii=False, indent=None, sort_keys=True) for d in [paises, puertos, vias, clausulas, modalidad, bultos])
open(r"D:\PUDU\Certificador Pudu\backend\aduana_tablas.py", "w", encoding="utf-8").write(out)
print("OK", len(paises), len(puertos), len(vias), len(clausulas), len(modalidad), len(bultos), list(clausulas.items())[:6], list(modalidad.items())[:8])

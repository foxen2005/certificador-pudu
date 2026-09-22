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
import unicodedata


def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper().strip()


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

# Alias frecuentes en los sets del SII → clave de la tabla
_ALIAS = {
    "AEREO": "AEREO", "MARITIMA, FLUVIAL Y LACUSTRE": "MARITIMA, FLUVIAL Y LACUSTRE",
    "CARRETERO": "CARRETERO / TERRESTRE", "TERRESTRE": "CARRETERO / TERRESTRE",
    "A FIRME": "A FIRME", "FIRME": "A FIRME",
    "EN CONSIGNACION CON UN MINIMO A FIRME": "EN CONSIGNACION CON UN MINIMO A FIRME",
    "CONTENEDOR REFRIGERADO": "CONTENEDOR REFRIGERADO 20 PIES",
}


def _buscar(tabla: dict, texto: str, que: str) -> int:
    k = norm(_ALIAS.get(norm(texto), texto))
    if k in tabla:
        return tabla[k]
    # coincidencia por prefijo (ej. "CONTENEDOR REFRIGERADO" → "... 20 PIES")
    cands = [v for kk, v in tabla.items() if kk.startswith(k) or k.startswith(kk)]
    if len(cands) == 1:
        return cands[0]
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

"""
Genera el EnvioDTE de Etapa 2 (Simulación) para PUDU TECNOLOGIA SPA.

3 DTEs:
  - T33 F37 : Factura → 2× Ubiquiti Loco M5 @ 35000
  - T61 F28 : NC devolución → 1× Ubiquiti Loco M5 @ 35000 (ref T33 F37)
  - T56 F10 : ND anula NC  → 1× Ubiquiti Loco M2 @ 35000 (ref T61 F28)

Uso:
    cd backend
    python test_etapa2.py
"""
import os, sys, datetime, subprocess
sys.path.insert(0, os.path.dirname(__file__))

from lxml import etree
from dte_builder import CAF, build_ted

PUDU_SET    = r"f:\PUDU\Certificador Pudu\sets\pudu_78392059K"
OUTPUT_BASE = r"f:\PUDU\Certificador Pudu\output"
FIRMA_JS    = r"f:\PUDU\Certificador Pudu\verify\firmar_envio.js"
NS_DTE = "http://www.sii.cl/SiiDte"


def leer_datos(path: str) -> dict:
    with open(path, encoding="iso-8859-1") as f:
        lines = [l.rstrip("\n") for l in f if l.strip()]
    return {
        "rut":          lines[3],
        "rut_envia":    lines[1],
        "razon_social": lines[2],
        "giro":         lines[5] if len(lines) > 5 else "",
        "acteco":       lines[6] if len(lines) > 6 else "999999",
        "dir_origen":   lines[7] if len(lines) > 7 else "",
        "cmna_origen":  lines[8] if len(lines) > 8 else "",
        "nro_resol":    lines[9] if len(lines) > 9 else "0",
        "fch_resol":    lines[10] if len(lines) > 10 else datetime.date.today().isoformat(),
        "_pfx_pass":    lines[4],
    }


RECEPTOR = {
    "rut":          "77221286-0",
    "razon_social": "C&C SPA",
    "giro":         "VENTA AL POR MENOR DE ALIMENTOS EN COMER",
    "dir":          "AVDA AUSTRAL 1780 JARDIN ORIENTE II",
    "cmna":         "Puerto Montt",
}


def build_dte(tipo: int, folio: int, emisor: dict, receptor: dict,
              caf: CAF, timestamp: str,
              items: list[dict],
              referencias: list[dict] = None) -> etree._Element:
    """Construye un <DTE> con TED firmado. Sin referencia a SET."""
    fecha = timestamp[:10]

    neto = sum(round(it["qty"] * it["prc"]) for it in items if not it.get("exento"))
    exento = sum(round(it["qty"] * it["prc"]) for it in items if it.get("exento"))
    iva = round(neto * 0.19) if neto else 0
    total = neto + iva + exento

    primer_item = items[0]["nombre"]

    ted = build_ted(
        tipo=tipo, folio=folio, fecha=fecha,
        rut_receptor=receptor["rut"],
        rsoc_receptor=receptor["razon_social"],
        monto_total=total,
        primer_item=primer_item,
        caf=caf, timestamp=timestamp,
    )

    DTE = etree.Element("DTE", version="1.0")
    DOC = etree.SubElement(DTE, "Documento", ID=f"LibreDTE_T{tipo}F{folio}")

    ENC = etree.SubElement(DOC, "Encabezado")
    ID_DOC = etree.SubElement(ENC, "IdDoc")
    etree.SubElement(ID_DOC, "TipoDTE").text  = str(tipo)
    etree.SubElement(ID_DOC, "Folio").text    = str(folio)
    etree.SubElement(ID_DOC, "FchEmis").text  = fecha
    if tipo == 33:
        etree.SubElement(ID_DOC, "TpoTranVenta").text = "1"
    if tipo in (56, 61):
        etree.SubElement(ID_DOC, "TpoTranVenta").text = "1"

    EMIS = etree.SubElement(ENC, "Emisor")
    etree.SubElement(EMIS, "RUTEmisor").text  = emisor["rut"]
    etree.SubElement(EMIS, "RznSoc").text     = emisor["razon_social"]
    etree.SubElement(EMIS, "GiroEmis").text   = emisor["giro"][:80]
    etree.SubElement(EMIS, "Acteco").text     = emisor.get("acteco", "999999")
    etree.SubElement(EMIS, "DirOrigen").text  = emisor["dir_origen"]
    etree.SubElement(EMIS, "CmnaOrigen").text = emisor["cmna_origen"]

    REC = etree.SubElement(ENC, "Receptor")
    etree.SubElement(REC, "RUTRecep").text    = receptor["rut"]
    etree.SubElement(REC, "RznSocRecep").text = receptor["razon_social"]
    etree.SubElement(REC, "GiroRecep").text   = receptor["giro"]
    etree.SubElement(REC, "DirRecep").text    = receptor["dir"]
    etree.SubElement(REC, "CmnaRecep").text   = receptor["cmna"]

    TOTS = etree.SubElement(ENC, "Totales")
    if neto:
        etree.SubElement(TOTS, "MntNeto").text = str(neto)
    if exento:
        etree.SubElement(TOTS, "MntExe").text  = str(exento)
    if neto:
        etree.SubElement(TOTS, "TasaIVA").text = "19"
        etree.SubElement(TOTS, "IVA").text     = str(iva)
    etree.SubElement(TOTS, "MntTotal").text = str(total)

    for i, it in enumerate(items, 1):
        DET = etree.SubElement(DOC, "Detalle")
        etree.SubElement(DET, "NroLinDet").text = str(i)
        etree.SubElement(DET, "NmbItem").text   = it["nombre"]
        etree.SubElement(DET, "QtyItem").text   = str(it["qty"])
        etree.SubElement(DET, "PrcItem").text   = str(it["prc"])
        etree.SubElement(DET, "MontoItem").text = str(round(it["qty"] * it["prc"]))

    for j, ref in enumerate(referencias or [], 1):
        REF = etree.SubElement(DOC, "Referencia")
        etree.SubElement(REF, "NroLinRef").text  = str(j)
        etree.SubElement(REF, "TpoDocRef").text  = str(ref["tipo"])
        etree.SubElement(REF, "FolioRef").text   = str(ref["folio"])
        etree.SubElement(REF, "FchRef").text     = fecha
        etree.SubElement(REF, "CodRef").text     = str(ref["cod"])
        etree.SubElement(REF, "RazonRef").text   = ref["razon"]

    DOC.append(ted)
    etree.SubElement(DOC, "TmstFirma").text = timestamp
    return DTE


def build_unsigned_envio(dtes: list, emisor: dict, timestamp: str) -> bytes:
    from collections import Counter
    ROOT = etree.Element(
        "EnvioDTE",
        xmlns="http://www.sii.cl/SiiDte",
        attrib={
            "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation":
                "http://www.sii.cl/SiiDte EnvioDTE_v10.xsd",
            "version": "1.0",
        }
    )
    SET = etree.SubElement(ROOT, "SetDTE", ID="LibreDTE_SetDoc")
    CAR = etree.SubElement(SET, "Caratula", version="1.0")
    etree.SubElement(CAR, "RutEmisor").text   = emisor["rut"]
    etree.SubElement(CAR, "RutEnvia").text    = emisor["rut_envia"]
    etree.SubElement(CAR, "RutReceptor").text = "60803000-K"
    etree.SubElement(CAR, "FchResol").text    = emisor.get("fch_resol", timestamp[:10])
    etree.SubElement(CAR, "NroResol").text    = emisor.get("nro_resol", "0")
    etree.SubElement(CAR, "TmstFirmaEnv").text = timestamp

    conteo = Counter()
    for dte in dtes:
        doc = dte.find("Documento")
        tipo = doc.find("Encabezado/IdDoc/TipoDTE").text
        conteo[tipo] += 1
    for tipo, n in sorted(conteo.items(), key=lambda x: int(x[0])):
        ST = etree.SubElement(CAR, "SubTotDTE")
        etree.SubElement(ST, "TpoDTE").text = tipo
        etree.SubElement(ST, "NroDTE").text = str(n)

    for dte in dtes:
        SET.append(dte)

    return etree.tostring(ROOT, xml_declaration=True,
                          encoding="ISO-8859-1", pretty_print=True)


def firmar(unsigned_path: str, signed_path: str, p12_path: str, p12_pass: str):
    result = subprocess.run(
        ["node", FIRMA_JS, unsigned_path, signed_path, p12_path, p12_pass],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"firma fallida:\n{result.stderr}")
    print(result.stderr.strip())


def run():
    ts = datetime.datetime.now()
    timestamp = ts.strftime("%Y-%m-%dT%H:%M:%S")
    out_dir = os.path.join(OUTPUT_BASE, ts.strftime("etapa2_%Y%m%d_%H%M"))
    os.makedirs(out_dir, exist_ok=True)

    datos = leer_datos(os.path.join(PUDU_SET, "DATOS.txt"))
    p12_path = os.path.join(PUDU_SET, "cert.p12")
    for f in os.listdir(PUDU_SET):
        if f.endswith(".p12") or f.endswith(".pfx"):
            p12_path = os.path.join(PUDU_SET, f)
            break

    caf33 = CAF(open(os.path.join(PUDU_SET, "33_1-100.xml"), "rb").read())
    caf61 = CAF(open(os.path.join(PUDU_SET, "61_1-100.xml"), "rb").read())
    caf56 = CAF(open(os.path.join(PUDU_SET, "56_1-100.xml"), "rb").read())

    FOLIO_33 = 37
    FOLIO_61 = 28
    FOLIO_56 = 10

    print(f"Folios: T33F{FOLIO_33}  T61F{FOLIO_61}  T56F{FOLIO_56}")

    # T33 — Factura: 2× Ubiquiti Loco M5 @ 35000
    dte33 = build_dte(
        tipo=33, folio=FOLIO_33, emisor=datos,
        receptor=RECEPTOR, caf=caf33, timestamp=timestamp,
        items=[{"nombre": "Ubiquiti Loco M5", "qty": 2, "prc": 35000}],
    )

    # T61 — NC devolución: 1× Ubiquiti Loco M5 @ 35000, ref T33
    dte61 = build_dte(
        tipo=61, folio=FOLIO_61, emisor=datos,
        receptor=RECEPTOR, caf=caf61, timestamp=timestamp,
        items=[{"nombre": "Ubiquiti Loco M5", "qty": 1, "prc": 35000}],
        referencias=[{
            "tipo": 33, "folio": FOLIO_33,
            "cod": 3, "razon": "Devolucion mercaderia",
        }],
    )

    # T56 — ND anula NC: 1× Ubiquiti Loco M2 @ 35000, ref T61
    dte56 = build_dte(
        tipo=56, folio=FOLIO_56, emisor=datos,
        receptor=RECEPTOR, caf=caf56, timestamp=timestamp,
        items=[{"nombre": "Ubiquiti Loco M2", "qty": 1, "prc": 35000}],
        referencias=[{
            "tipo": 61, "folio": FOLIO_61,
            "cod": 1, "razon": "Anula nota de credito electronica",
        }],
    )

    unsigned_xml = build_unsigned_envio([dte33, dte61, dte56], datos, timestamp)
    unsigned_path = os.path.join(out_dir, "EnvioDTE_UNSIGNED.xml")
    with open(unsigned_path, "wb") as f:
        f.write(unsigned_xml)
    print(f"XML sin firma: {unsigned_path}")

    signed_path = os.path.join(out_dir, f"EnvioDTE_{datos['rut'].replace('-','')}.xml")
    firmar(unsigned_path, signed_path, p12_path, datos["_pfx_pass"])
    os.remove(unsigned_path)
    print(f"EnvioDTE firmado: {signed_path}")
    print(f"\nListo → {out_dir}")


if __name__ == "__main__":
    run()

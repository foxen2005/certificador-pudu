"""
Genera los 3 archivos de Etapa 3 (Intercambio) para PUDU TECNOLOGIA SPA.

Lee el SET de Intercambio del SII y produce:
  1_RecepcionDTE.xml   — acuse de recepción del envío
  2_EnvioRecibos.xml   — recibo de mercaderías por cada DTE
  3_ResultadoDTE.xml   — resultado comercial (aceptado/rechazado)

Uso:
    cd backend
    python test_etapa3.py <path_set_intercambio.xml>
"""
import os, sys, re, datetime, subprocess
from lxml import etree

PUDU_SET  = r"f:\PUDU\Certificador Pudu\sets\pudu_78392059K"
OUT_BASE  = r"f:\PUDU\Certificador Pudu\output"
FIRMA_RESP   = r"f:\PUDU\Certificador Pudu\verify\firmar_respuesta_dte.js"
FIRMA_RECIB  = r"f:\PUDU\Certificador Pudu\verify\firmar_envio_recibos.js"
NS = "http://www.sii.cl/SiiDte"

SET_XML = sys.argv[1] if len(sys.argv) > 1 else \
    r"f:\PUDU\Certificador Pudu\sets\pudu_78392059K\epata3_ENVIO_DTE_4832678.xml"


def leer_datos(path):
    with open(path, encoding="iso-8859-1") as f:
        lines = [l.rstrip("\n") for l in f if l.strip()]
    return {
        "rut":         lines[3],
        "rut_envia":   lines[1],
        "nombre":      lines[0],
        "email":       "julio1741@gmail.com",
        "_pfx_pass":   lines[4],
    }


def firmar(js_script, unsigned_path, signed_path, p12_path, p12_pass):
    r = subprocess.run(
        ["node", js_script, unsigned_path, signed_path, p12_path, p12_pass],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        raise RuntimeError(f"firma fallida:\n{r.stderr}")
    print(r.stderr.strip())


def sign_xml(js_script, xml_bytes, out_path, p12_path, p12_pass):
    tmp = out_path + ".unsigned.xml"
    with open(tmp, "wb") as f:
        f.write(xml_bytes)
    firmar(js_script, tmp, out_path, p12_path, p12_pass)
    os.remove(tmp)
    with open(out_path, "rb") as f:
        return f.read()


def parse_set(set_path):
    with open(set_path, "rb") as f:
        raw = f.read()
    tree = etree.fromstring(raw)
    set_dte = tree.find(f"{{{NS}}}SetDTE")
    set_id  = set_dte.get("ID")

    # Digest = DigestValue from outer Signature that references the SetDTE ID
    NS_DS = "http://www.w3.org/2000/09/xmldsig#"
    digest = None
    for sig in tree.findall(f"{{{NS_DS}}}Signature"):
        for ref in sig.findall(f".//{{{NS_DS}}}Reference"):
            if ref.get("URI") == f"#{set_id}":
                dv = ref.find(f"{{{NS_DS}}}DigestValue")
                if dv is not None:
                    digest = dv.text.strip()
    dtes = []
    for dte_el in set_dte.findall(f"{{{NS}}}DTE"):
        doc = dte_el.find(f"{{{NS}}}Documento")
        enc = doc.find(f"{{{NS}}}Encabezado")
        iddoc = enc.find(f"{{{NS}}}IdDoc")
        tots  = enc.find(f"{{{NS}}}Totales")
        rec   = enc.find(f"{{{NS}}}Receptor")
        dtes.append({
            "tipo":     iddoc.findtext(f"{{{NS}}}TipoDTE"),
            "folio":    iddoc.findtext(f"{{{NS}}}Folio"),
            "fch_emis": iddoc.findtext(f"{{{NS}}}FchEmis"),
            "rut_emisor": enc.find(f"{{{NS}}}Emisor").findtext(f"{{{NS}}}RUTEmisor"),
            "rut_recep":  rec.findtext(f"{{{NS}}}RUTRecep"),
            "mnt_total":  tots.findtext(f"{{{NS}}}MntTotal"),
        })
    # Canonical SII name: "ENVIO_DTE_{nAtención}.xml" regardless of local filename
    m = re.search(r'ENVIO_DTE_(\d+)', os.path.basename(set_path), re.IGNORECASE)
    nmbenvio = f"ENVIO_DTE_{m.group(1)}.xml" if m else os.path.basename(set_path)
    return digest, set_id, nmbenvio, dtes


def build_recepcion_dte(datos, ts, digest, set_id, nmbenvio, rut_emisor_set, dtes):
    """1_RecepcionDTE.xml — RespuestaDTE con RecepcionEnvio."""
    root = etree.Element(
        "RespuestaDTE",
        xmlns=NS,
        attrib={
            "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation":
                "http://www.sii.cl/SiiDte RespuestaEnvioDTE_v10.xsd",
            "version": "1.0",
        }
    )
    RES = etree.SubElement(root, "Resultado", ID="LibreDTE_ResultadoEnvio")
    CAR = etree.SubElement(RES, "Caratula", version="1.0")
    etree.SubElement(CAR, "RutResponde").text  = datos["rut"]
    etree.SubElement(CAR, "RutRecibe").text    = rut_emisor_set
    etree.SubElement(CAR, "IdRespuesta").text  = "1"
    etree.SubElement(CAR, "NroDetalles").text  = "1"
    etree.SubElement(CAR, "NmbContacto").text  = datos["nombre"]
    etree.SubElement(CAR, "MailContacto").text = datos["email"]
    etree.SubElement(CAR, "TmstFirmaResp").text = ts

    REC_ENV = etree.SubElement(RES, "RecepcionEnvio")
    etree.SubElement(REC_ENV, "NmbEnvio").text      = nmbenvio
    etree.SubElement(REC_ENV, "FchRecep").text       = ts
    etree.SubElement(REC_ENV, "CodEnvio").text       = "1"
    etree.SubElement(REC_ENV, "EnvioDTEID").text     = set_id
    etree.SubElement(REC_ENV, "Digest").text         = digest
    etree.SubElement(REC_ENV, "RutEmisor").text      = rut_emisor_set
    etree.SubElement(REC_ENV, "RutReceptor").text    = datos["rut"]
    etree.SubElement(REC_ENV, "EstadoRecepEnv").text = "0"
    etree.SubElement(REC_ENV, "RecepEnvGlosa").text  = "Envio Recibido Conforme"
    etree.SubElement(REC_ENV, "NroDTE").text         = str(len(dtes))

    for dte in dtes:
        es_nuestro = dte["rut_recep"] == datos["rut"]
        RD = etree.SubElement(REC_ENV, "RecepcionDTE")
        etree.SubElement(RD, "TipoDTE").text    = dte["tipo"]
        etree.SubElement(RD, "Folio").text      = dte["folio"]
        etree.SubElement(RD, "FchEmis").text    = dte["fch_emis"]
        etree.SubElement(RD, "RUTEmisor").text  = dte["rut_emisor"]
        etree.SubElement(RD, "RUTRecep").text   = dte["rut_recep"]
        etree.SubElement(RD, "MntTotal").text   = dte["mnt_total"]
        if es_nuestro:
            etree.SubElement(RD, "EstadoRecepDTE").text  = "0"
            etree.SubElement(RD, "RecepDTEGlosa").text   = "DTE Recibido OK"
        else:
            etree.SubElement(RD, "EstadoRecepDTE").text  = "3"
            etree.SubElement(RD, "RecepDTEGlosa").text   = "DTE No Recibido - Error en RUT Receptor"

    return etree.tostring(root, xml_declaration=True,
                          encoding="ISO-8859-1", pretty_print=True)


def build_envio_recibos(datos, ts, rut_emisor_set, dtes):
    """2_EnvioRecibos.xml — acuse de recibo de mercaderías."""
    root = etree.Element(
        "EnvioRecibos",
        xmlns=NS,
        attrib={
            "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation":
                "http://www.sii.cl/SiiDte EnvioRecibos_v10.xsd",
            "version": "1.0",
        }
    )
    SET = etree.SubElement(root, "SetRecibos", ID="LibreDTE_SetDteRecibidos")
    CAR = etree.SubElement(SET, "Caratula", version="1.0")
    etree.SubElement(CAR, "RutResponde").text  = datos["rut"]
    etree.SubElement(CAR, "RutRecibe").text    = rut_emisor_set
    etree.SubElement(CAR, "NmbContacto").text  = datos["nombre"]
    etree.SubElement(CAR, "MailContacto").text = datos["email"]
    etree.SubElement(CAR, "TmstFirmaEnv").text = ts

    declaracion = ("El acuse de recibo que se declara en este acto, de acuerdo a lo dispuesto "
                   "en la letra b) del Art. 4, y la letra c) del Art. 5 de la Ley 19.983, "
                   "acredita que la entrega de mercaderias o servicio(s) prestado(s) ha(n) "
                   "sido recibido(s).")

    for dte in dtes:
        REC = etree.SubElement(SET, "Recibo", version="1.0")
        DR  = etree.SubElement(REC, "DocumentoRecibo",
                               ID=f"LibreDTE_T{dte['tipo']}F{dte['folio']}")
        etree.SubElement(DR, "TipoDoc").text   = dte["tipo"]
        etree.SubElement(DR, "Folio").text     = dte["folio"]
        etree.SubElement(DR, "FchEmis").text   = dte["fch_emis"]
        etree.SubElement(DR, "RUTEmisor").text = dte["rut_emisor"]
        etree.SubElement(DR, "RUTRecep").text  = dte["rut_recep"]
        etree.SubElement(DR, "MntTotal").text  = dte["mnt_total"]
        etree.SubElement(DR, "Recinto").text   = "Oficina central"
        etree.SubElement(DR, "RutFirma").text  = datos["rut_envia"]
        etree.SubElement(DR, "Declaracion").text       = declaracion
        etree.SubElement(DR, "TmstFirmaRecibo").text   = ts

    return etree.tostring(root, xml_declaration=True,
                          encoding="ISO-8859-1", pretty_print=True)


def build_resultado_dte(datos, ts, rut_emisor_set, dtes):
    """3_ResultadoDTE.xml — resultado comercial."""
    root = etree.Element(
        "RespuestaDTE",
        xmlns=NS,
        attrib={
            "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation":
                "http://www.sii.cl/SiiDte RespuestaEnvioDTE_v10.xsd",
            "version": "1.0",
        }
    )
    RES = etree.SubElement(root, "Resultado", ID="LibreDTE_ResultadoEnvio")
    CAR = etree.SubElement(RES, "Caratula", version="1.0")
    etree.SubElement(CAR, "RutResponde").text  = datos["rut"]
    etree.SubElement(CAR, "RutRecibe").text    = rut_emisor_set
    etree.SubElement(CAR, "IdRespuesta").text  = "1"
    etree.SubElement(CAR, "NroDetalles").text  = str(len(dtes))
    etree.SubElement(CAR, "NmbContacto").text  = datos["nombre"]
    etree.SubElement(CAR, "MailContacto").text = datos["email"]
    etree.SubElement(CAR, "TmstFirmaResp").text = ts

    for i, dte in enumerate(dtes, 1):
        es_nuestro = dte["rut_recep"] == datos["rut"]
        RD = etree.SubElement(RES, "ResultadoDTE")
        etree.SubElement(RD, "TipoDTE").text   = dte["tipo"]
        etree.SubElement(RD, "Folio").text     = dte["folio"]
        etree.SubElement(RD, "FchEmis").text   = dte["fch_emis"]
        etree.SubElement(RD, "RUTEmisor").text = dte["rut_emisor"]
        etree.SubElement(RD, "RUTRecep").text  = dte["rut_recep"]
        etree.SubElement(RD, "MntTotal").text  = dte["mnt_total"]
        etree.SubElement(RD, "CodEnvio").text  = str(i)
        if es_nuestro:
            etree.SubElement(RD, "EstadoDTE").text      = "0"
            etree.SubElement(RD, "EstadoDTEGlosa").text = "ACEPTADO OK"
        else:
            etree.SubElement(RD, "EstadoDTE").text      = "2"
            etree.SubElement(RD, "EstadoDTEGlosa").text = "RECHAZADO"

    return etree.tostring(root, xml_declaration=True,
                          encoding="ISO-8859-1", pretty_print=True)


def run():
    ts = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    out_dir = os.path.join(OUT_BASE,
        datetime.datetime.now().strftime("etapa3_%Y%m%d_%H%M"))
    os.makedirs(out_dir, exist_ok=True)

    datos = leer_datos(os.path.join(PUDU_SET, "DATOS.txt"))
    p12_path = next(
        os.path.join(PUDU_SET, f) for f in os.listdir(PUDU_SET)
        if f.endswith(".p12") or f.endswith(".pfx")
    )

    print(f"SET: {SET_XML}")
    digest, set_id, nmbenvio, dtes = parse_set(SET_XML)
    rut_emisor_set = dtes[0]["rut_emisor"]

    print(f"DTEs en el SET: {len(dtes)}")
    for d in dtes:
        nuestro = "(NUESTRO)" if d["rut_recep"] == datos["rut"] else "(ajeno)"
        print(f"  T{d['tipo']}F{d['folio']} -> {d['rut_recep']} ${d['mnt_total']} {nuestro}")

    # 1. RecepcionDTE
    xml1 = build_recepcion_dte(datos, ts, digest, set_id, nmbenvio, rut_emisor_set, dtes)
    path1 = os.path.join(out_dir, "1_RecepcionDTE.xml")
    sign_xml(FIRMA_RESP, xml1, path1, p12_path, datos["_pfx_pass"])
    print(f"OK {path1}")

    # 2. EnvioRecibos
    xml2 = build_envio_recibos(datos, ts, rut_emisor_set, dtes)
    path2 = os.path.join(out_dir, "2_EnvioRecibos.xml")
    sign_xml(FIRMA_RECIB, xml2, path2, p12_path, datos["_pfx_pass"])
    print(f"OK {path2}")

    # 3. ResultadoDTE
    xml3 = build_resultado_dte(datos, ts, rut_emisor_set, dtes)
    path3 = os.path.join(out_dir, "3_ResultadoDTE.xml")
    sign_xml(FIRMA_RESP, xml3, path3, p12_path, datos["_pfx_pass"])
    print(f"OK {path3}")

    print(f"\nListo -> {out_dir}")


if __name__ == "__main__":
    run()

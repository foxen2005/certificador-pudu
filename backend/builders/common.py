"""Helpers compartidos para construir XMLs firmados del SII.

Patrones aprendidos en certificación que importan replicar siempre:

1. **C14N spec-compliant (`c14n_for_sii`)**: lxml tiene dos bugs en subtree C14N
   que provocan rechazo de firma en el SII (Java spec-compliant). Esta función
   los corrige post-serialización.

2. **Construir Signature ANTES de firmar (`build_signature`)**: el Signature
   debe insertarse en el árbol con `nsmap={None: NS_SIG}` y con su formato
   final (newlines + base64 wrap) ANTES de calcular el C14N del SignedInfo.
   Si se firma "compacto" y luego se formatea, el XML enviado no coincide con
   lo firmado → DTE-3-505 / firma de libro rechazada.

3. **Serializar + re-parsear** (`serialize_and_reparse`): después de construir
   un árbol mezclando elementos sin namespace (que luego heredarán el default
   xmlns del root), serializar el árbol completo y re-parsearlo deja todos
   los nodos con su namespace explícito. Sin esto el C14N de subtree omite el
   `xmlns="http://www.sii.cl/SiiDte"` y la firma no valida.
"""
import base64
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from lxml import etree
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.backends import default_backend


NS_DTE = "http://www.sii.cl/SiiDte"
NS_SIG = "http://www.w3.org/2000/09/xmldsig#"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"

PUDU_SIGN_SCRIPT = Path(__file__).parent / "pudu_sign.cjs"


# ─── Formateo del árbol ───────────────────────────────────────────────────────

def add_newlines(el: etree._Element) -> None:
    """Agrega `\\n` entre elementos hijos (no toca texto de hojas).

    Debe llamarse ANTES de calcular cualquier C14N que cubra `el` para que
    digest y serialización final coincidan.
    """
    if len(el) > 0:
        el.text = "\n"
        for child in el:
            child.tail = "\n"
            add_newlines(child)


def wrap_base64(el: etree._Element, width: int = 64) -> None:
    """Corta en líneas de `width` chars el texto de hojas largas (base64).

    Solo afecta hojas (sin hijos). Debe llamarse ANTES del C14N que cubre
    `el` para que digest y serialización coincidan.
    """
    for child in el.iter():
        if child.text and len(child) == 0:
            raw = child.text.replace("\n", "").replace(" ", "")
            if len(raw) > width:
                child.text = (
                    "\n"
                    + "\n".join(raw[i:i + width] for i in range(0, len(raw), width))
                    + "\n"
                )


def serialize_and_reparse(root: etree._Element) -> etree._Element:
    """Serializa y re-parsea para fijar los namespaces inferidos del root.

    Necesario cuando se construye el árbol mezclando elementos sin namespace
    explícito (ej: `etree.Element("DTE")`) bajo un root con `xmlns=NS_DTE` en
    atributos. Después del round-trip lxml ve esos elementos como pertenecientes
    al namespace por inheritance y el C14N de subtree es consistente.
    """
    return etree.fromstring(etree.tostring(root))


# ─── C14N compatible con el verificador del SII ──────────────────────────────

def c14n_for_sii(el: etree._Element) -> bytes:
    """C14N de un subtree compatible con la verificación del SII.

    Corrige el bug de lxml en subtree C14N que agrega `xmlns=""` en elementos
    a profundidad ≥2 aunque los elementos estén en el namespace del root del
    subtree. Java/SII (spec-compliant) no lo agrega.

    NOTA: NO removemos `xmlns:xsi="..."` aunque no sea "visibly utilized" en
    el subtree. Empíricamente el SII lo incluye en su C14N (LibreDTE
    certificado lo tiene explícito en `<SignedInfo>`). Si lo removemos →
    RFR/firma incorrecta porque nuestro digest ≠ el que computa el SII.
    """
    c14n = etree.tostring(el, method="c14n")
    c14n = c14n.replace(b' xmlns=""', b'')
    return c14n


# ─── Firma XMLDsig genérica para envoltorios SII ─────────────────────────────

def build_and_sign_envelope_signature(
    parent: etree._Element,
    reference_uri: str,
    target_el: etree._Element,
    private_key,
    certificate,
) -> None:
    """Construye y firma un `<Signature>` envolvente sobre `target_el`.

    Patrón estándar del SII para EnvioDTE outer, SetDTE outer, EnvioLibro:

    1. Calcula DigestValue del `target_el` (C14N spec-compliant para SII)
    2. Construye `<Signature xmlns="...xmldsig#">` como SubElement de `parent`
       con `nsmap={None: NS_SIG}` (sin prefijo) y referencia `URI=reference_uri`
    3. Aplica `add_newlines` + `wrap_base64` al Signature
    4. Calcula C14N del SignedInfo embebido → firma con la clave privada
    5. Rellena `<SignatureValue>` con la firma base64

    El Signature queda en el árbol listo para que la serialización final
    refleje el contenido firmado exactamente.
    """
    # 1. Digest del target
    target_c14n = c14n_for_sii(target_el)
    digest_b64 = base64.b64encode(hashlib.sha1(target_c14n).digest()).decode()

    # 2. Construir Signature en el árbol
    SIG = etree.SubElement(parent, f"{{{NS_SIG}}}Signature", nsmap={None: NS_SIG})
    SIG.tail = "\n"
    SI = etree.SubElement(SIG, f"{{{NS_SIG}}}SignedInfo")
    etree.SubElement(
        SI, f"{{{NS_SIG}}}CanonicalizationMethod",
        Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
    )
    etree.SubElement(
        SI, f"{{{NS_SIG}}}SignatureMethod",
        Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1",
    )
    REF = etree.SubElement(SI, f"{{{NS_SIG}}}Reference", URI=reference_uri)
    TRANS = etree.SubElement(REF, f"{{{NS_SIG}}}Transforms")
    etree.SubElement(
        TRANS, f"{{{NS_SIG}}}Transform",
        Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature",
    )
    etree.SubElement(
        REF, f"{{{NS_SIG}}}DigestMethod",
        Algorithm="http://www.w3.org/2000/09/xmldsig#sha1",
    )
    etree.SubElement(REF, f"{{{NS_SIG}}}DigestValue").text = digest_b64
    SV = etree.SubElement(SIG, f"{{{NS_SIG}}}SignatureValue")
    KI = etree.SubElement(SIG, f"{{{NS_SIG}}}KeyInfo")
    KV = etree.SubElement(KI, f"{{{NS_SIG}}}KeyValue")
    RSA = etree.SubElement(KV, f"{{{NS_SIG}}}RSAKeyValue")
    pub_nums = certificate.public_key().public_numbers()
    n_b = pub_nums.n.to_bytes((pub_nums.n.bit_length() + 7) // 8, "big")
    e_b = pub_nums.e.to_bytes((pub_nums.e.bit_length() + 7) // 8, "big")
    etree.SubElement(RSA, f"{{{NS_SIG}}}Modulus").text = base64.b64encode(n_b).decode()
    etree.SubElement(RSA, f"{{{NS_SIG}}}Exponent").text = base64.b64encode(e_b).decode()
    X509 = etree.SubElement(KI, f"{{{NS_SIG}}}X509Data")
    cert_der = certificate.public_bytes(serialization.Encoding.DER)
    etree.SubElement(X509, f"{{{NS_SIG}}}X509Certificate").text = base64.b64encode(cert_der).decode()

    # 3. Formatear ANTES del C14N final
    add_newlines(SIG)
    wrap_base64(SIG)

    # 4. Firmar SignedInfo embebido
    si_c14n = c14n_for_sii(SI)
    sig_bytes = private_key.sign(si_c14n, padding.PKCS1v15(), hashes.SHA1())
    SV.text = base64.b64encode(sig_bytes).decode()


def sign_via_pudu(unsigned_xml: bytes, pfx_bytes: bytes, pfx_password: str,
                  signatures: list[dict]) -> bytes:
    """Firma un XML invocando pudu_sign.js (xml-crypto del SII_pudu_Server).

    Las firmas se aplican en el orden dado. Cada elemento de `signatures` es:
        {"ref_id": "ID del elemento referenciado",
         "location_xpath": "XPath del nodo PADRE donde insertar <Signature>"}

    El SII_pudu_Server tiene `signer.js` ya probado en producción con xml-crypto,
    cuyo C14N coincide con el verificador del SII (Java). Usar esto evita los
    bugs de lxml subtree C14N que hicimos sufrir varias iteraciones.
    """
    # Guardar el .pfx en archivo temporal (Node.js lo lee desde path)
    with tempfile.NamedTemporaryFile(suffix=".pfx", delete=False) as pfx_tmp:
        pfx_tmp.write(pfx_bytes)
        pfx_tmp_path = pfx_tmp.name

    try:
        payload = json.dumps({
            "xml": unsigned_xml.decode("iso-8859-1"),
            "pfx_path": pfx_tmp_path,
            "pfx_password": pfx_password or "",
            "signatures": signatures,
        })
        result = subprocess.run(
            ["node", str(PUDU_SIGN_SCRIPT)],
            input=payload.encode("utf-8"),
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"pudu_sign.js falló (exit {result.returncode}): "
                f"{result.stderr.decode('utf-8', errors='replace')}"
            )
        # Devolver bytes en ISO-8859-1 como espera el SII
        signed_xml_str = result.stdout.decode("utf-8")
        return signed_xml_str.encode("iso-8859-1")
    finally:
        Path(pfx_tmp_path).unlink(missing_ok=True)


def load_pfx(pfx_bytes: bytes, password: str):
    """Carga un .pfx y retorna (private_key, certificate)."""
    pwd = password.encode() if password else None
    private_key, certificate, _ = pkcs12.load_key_and_certificates(
        pfx_bytes, pwd, backend=default_backend()
    )
    return private_key, certificate


# ─── Encoding final ──────────────────────────────────────────────────────────

def serialize_signed(root: etree._Element) -> bytes:
    """Serializa el árbol firmado a ISO-8859-1 con la declaración XML del SII."""
    xml_bytes = etree.tostring(root, xml_declaration=True, encoding="ISO-8859-1")
    return xml_bytes.replace(
        b"<?xml version='1.0' encoding='ISO-8859-1'?>",
        b'<?xml version="1.0" encoding="ISO-8859-1"?>',
    )

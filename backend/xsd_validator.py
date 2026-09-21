"""Validación de XML contra los XSD oficiales del SII (schemas/).

Los XSD son copia de `D:\\PUDU\\Documentacion SII\\XML\\schema_dte\\` (schema_dte.zip
publicado por el SII). Se usan para validar EnvioDTE ANTES de subirlos al
portal: un XML que no pasa el schema se rechaza con "Envío rechazado — error
de schema" sin llegar a evaluar contenido ni firmas.

Nota: la firma XMLDSig del SII usa `xmlns="http://www.w3.org/2000/09/xmldsig#"`
sin prefijo y el XSD la importa como `ds:`; lxml resuelve bien ambos casos.
"""
import os
from functools import lru_cache

from lxml import etree

_SCHEMAS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemas")


@lru_cache(maxsize=1)
def _envio_dte_schema() -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(os.path.join(_SCHEMAS_DIR, "EnvioDTE_v10.xsd")))


def validar_envio_dte(xml_bytes: bytes) -> list[str]:
    """Devuelve la lista de errores de schema (vacía = válido)."""
    try:
        doc = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as e:
        return [f"XML mal formado: {e}"]
    schema = _envio_dte_schema()
    if schema.validate(doc):
        return []
    return [f"línea {e.line}: {e.message}" for e in schema.error_log]

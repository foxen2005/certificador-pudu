"""
Valida PDFs de muestras impresas según el Manual SII versión 4.0.
Retorna un reporte de validación con checks pass/fail.
"""
import re
from dataclasses import dataclass, field
import fitz  # PyMuPDF


TIPO_NOMBRE = {
    33: "FACTURA ELECTRÓNICA",
    34: "FACTURA NO AFECTA O EXENTA ELECTRÓNICA",
    52: "GUÍA DE DESPACHO ELECTRÓNICA",
    56: "NOTA DE DÉBITO ELECTRÓNICA",
    61: "NOTA DE CRÉDITO ELECTRÓNICA",
    46: "FACTURA DE COMPRA ELECTRÓNICA",
}

MAX_SIZE_BYTES = 500 * 1024  # 500 KB


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ValidationResult:
    filename: str
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self):
        return all(c.passed for c in self.checks)

    @property
    def score(self):
        total = len(self.checks)
        ok = sum(1 for c in self.checks if c.passed)
        return f"{ok}/{total}"


def validate_pdf(pdf_bytes: bytes, filename: str = "documento.pdf") -> ValidationResult:
    result = ValidationResult(filename=filename)
    checks = result.checks

    # 1. Tamaño máximo 500 KB
    size = len(pdf_bytes)
    checks.append(Check(
        "Tamaño ≤ 500 KB",
        size <= MAX_SIZE_BYTES,
        f"{size // 1024} KB" + ("" if size <= MAX_SIZE_BYTES else " — excede límite")
    ))

    # Abrir con PyMuPDF
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        checks.append(Check("PDF válido", False, str(e)))
        return result

    checks.append(Check("PDF válido", True))

    # 2. Una sola página
    n_pages = len(doc)
    checks.append(Check(
        "Una sola página",
        n_pages == 1,
        f"{n_pages} página(s)"
    ))

    page = doc[0]
    text = page.get_text()
    text_upper = text.upper()
    # Versión con espacios normalizados: los títulos largos (ej. "FACTURA DE
    # COMPRA ELECTRÓNICA") se parten en dos líneas al renderizar, insertando un
    # salto de línea donde el nombre esperado tiene un espacio. Colapsar los
    # espacios en blanco permite el match sin importar el ajuste de línea.
    text_flat = re.sub(r"\s+", " ", text_upper)

    # 3. Nombre del tipo de documento en mayúsculas
    tipo_encontrado = any(nombre in text_flat for nombre in TIPO_NOMBRE.values())
    checks.append(Check(
        "Nombre tipo documento presente",
        tipo_encontrado,
        "Encontrado" if tipo_encontrado else "No se encontró ningún tipo DTE conocido"
    ))

    # 4. RUT emisor con separador de miles
    rut_pattern = re.compile(r'\d{1,2}\.\d{3}\.\d{3}-[\dkK]')
    ruts = rut_pattern.findall(text)
    checks.append(Check(
        "RUT con formato (puntos y guión)",
        len(ruts) >= 1,
        f"RUTs encontrados: {ruts[:3]}" if ruts else "No se encontró RUT con formato correcto"
    ))

    # 5. N° de folio presente
    folio_match = re.search(r'N[°º]\s*\d+', text)
    checks.append(Check(
        "N° de folio presente",
        folio_match is not None,
        folio_match.group() if folio_match else "No encontrado"
    ))

    # 6. Leyenda "Timbre Electrónico SII"
    has_timbre_label = "TIMBRE ELECTRÓNICO SII" in text_upper or "TIMBRE ELECTRONICO SII" in text_upper
    checks.append(Check(
        "Leyenda 'Timbre Electrónico SII'",
        has_timbre_label,
        "Presente" if has_timbre_label else "No encontrada"
    ))

    # 7. Leyenda "Verifique documento: www.sii.cl"
    has_verificar = "VERIFIQUE DOCUMENTO" in text_upper and "WWW.SII.CL" in text_upper
    checks.append(Check(
        "Leyenda 'Verifique documento: www.sii.cl'",
        has_verificar,
        "Presente" if has_verificar else "No encontrada"
    ))

    # 8. Resolución mencionada
    has_resol = bool(re.search(r'resoluci[oó]n\s+\d+\s+de\s+\d{4}', text, re.IGNORECASE))
    checks.append(Check(
        "Resolución SII mencionada",
        has_resol,
        "Presente" if has_resol else "No encontrada (ej: Resolución 0 de 2026)"
    ))

    # 9. IVA con tasa explícita (documentos afectos: Factura Electrónica T33/T46
    #    y Notas de Crédito/Débito que no sean explícitamente exentas — las NC/ND
    #    también son documentos afectos a IVA y deben mostrar la tasa).
    #
    #    Ojo: una NC/ND que referencia una Factura la menciona en su tabla de
    #    "Referencias a otros documentos" (ej. "FACTURA ELECTRÓNICA  38  ...")
    #    — buscar "FACTURA ELECTRÓNICA" en todo el texto también matchea ahí,
    #    no solo en el recuadro de tipo propio del documento. Restringir la
    #    búsqueda al encabezado (antes de la tabla de referencias) evita el
    #    falso positivo.
    header_upper = text_upper.split("REFERENCIAS A OTROS DOCUMENTOS")[0]
    # Una NC/ND con CodRef=2 ("Corrige Texto"/Giro) tiene Monto Total=0 por
    # regla SII REF-2-781 — legítimamente no lleva línea de IVA.
    es_monto_cero = bool(re.search(r'MONTO\s+TOTAL:\s*\$?\s*0\b', text_upper))
    is_afecta = ("FACTURA ELECTRÓNICA" in header_upper
                 and "EXENTA" not in header_upper
                 and not es_monto_cero)
    if is_afecta:
        has_tasa = bool(re.search(r'IVA\s*\(\s*\d+\s*%\s*\)', text, re.IGNORECASE))
        checks.append(Check(
            "IVA con tasa explícita (ej: IVA (19%))",
            has_tasa,
            "Presente" if has_tasa else "Falta tasa en campo IVA"
        ))

    # 10. Cedible: verificar que si tiene "CEDIBLE" también tiene acuse de recibo
    is_cedible = "CEDIBLE" in text_upper
    if is_cedible:
        has_acuse = "ACUSE DE RECIBO" in text_upper or "LEY 19.983" in text_upper
        checks.append(Check(
            "Copia cedible: tiene Acuse de Recibo (Ley 19.983)",
            has_acuse,
            "Presente" if has_acuse else "Falta cuadro de Acuse de Recibo"
        ))

    # 11. Presencia de imagen/objeto PDF417 en el PDF, con posición y tamaño
    # dentro de lo exigido por el Manual SII para el Timbre Electrónico:
    # mínimo 2cm del borde izquierdo, tamaño aprox. entre 2x5cm y 4x9cm.
    # generator.py hoy genera el barcode con width_cm=5.0, height_cm=2.0
    # (ver PDF417Barcode en generator.py) y lo posiciona heredando el
    # margin=2.0*cm del documento — este check valida el rango, no el
    # valor exacto, para detectar si alguien rompe margen/tamaño a futuro.
    PT_PER_CM = 72 / 2.54
    MARGIN_MIN_CM = 1.8  # tolerancia sobre los 2cm exigidos
    # El timbre es rectangular (no cuadrado): una dimensión "corta" (~2 a 4cm)
    # y una dimensión "larga" (~5 a 9cm), con tolerancia para no ser frágil.
    SHORT_MIN_CM, SHORT_MAX_CM = 1.5, 4.5
    LONG_MIN_CM, LONG_MAX_CM = 4.0, 9.5

    images_info = page.get_image_info()
    barcode_ok = False
    if not images_info:
        detail = "0 imagen(es) en el documento"
    else:
        # Tomamos la imagen de mayor área como candidata al Timbre/PDF417
        im = max(images_info, key=lambda i: (i["bbox"][2] - i["bbox"][0]) * (i["bbox"][3] - i["bbox"][1]))
        x0, y0, x1, y1 = im["bbox"]
        w_cm = (x1 - x0) / PT_PER_CM
        h_cm = (y1 - y0) / PT_PER_CM
        left_cm = x0 / PT_PER_CM
        short_dim, long_dim = min(w_cm, h_cm), max(w_cm, h_cm)

        margin_ok = left_cm >= MARGIN_MIN_CM
        size_ok = (SHORT_MIN_CM <= short_dim <= SHORT_MAX_CM
                   and LONG_MIN_CM <= long_dim <= LONG_MAX_CM)
        barcode_ok = margin_ok and size_ok

        detail = (f"{len(images_info)} imagen(es); timbre candidato "
                  f"{w_cm:.1f}x{h_cm:.1f}cm a {left_cm:.1f}cm del borde izquierdo")
        if not margin_ok:
            detail += " — margen izquierdo insuficiente (<1.8cm)"
        if not size_ok:
            detail += " — tamaño fuera de rango esperado (~2x5 a 4x9cm)"

    checks.append(Check(
        "Imagen barcode embebida (posición y tamaño Timbre)",
        barcode_ok,
        detail
    ))

    # 12. El texto NO debe ser todo imagen (RUT, folio deben ser texto)
    # Si encontramos RUT y folio como texto, está bien
    checks.append(Check(
        "Datos clave son texto (no imagen)",
        len(ruts) >= 1 and folio_match is not None,
        "RUT y folio extraíbles como texto"
    ))

    doc.close()
    return result


def validate_pdf_file(path: str) -> ValidationResult:
    with open(path, "rb") as f:
        return validate_pdf(f.read(), filename=path.split("/")[-1].split("\\")[-1])

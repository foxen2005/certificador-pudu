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

    # 3. Nombre del tipo de documento en mayúsculas
    tipo_encontrado = any(nombre in text_upper for nombre in TIPO_NOMBRE.values())
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

    # 9. IVA con tasa explícita (solo facturas afectas T33/T46, no notas ni exentas)
    is_afecta = ("FACTURA ELECTRÓNICA" in text_upper
                 and "EXENTA" not in text_upper
                 and "NOTA DE" not in text_upper)
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

    # 11. Presencia de imagen/objeto PDF417 en el PDF
    # Verificamos que haya al menos una imagen embebida (el barcode)
    images = page.get_images(full=True)
    checks.append(Check(
        "Imagen barcode embebida",
        len(images) >= 1,
        f"{len(images)} imagen(es) en el documento"
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

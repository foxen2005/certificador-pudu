"""
Genera PDFs de muestras impresas DTE siguiendo el Manual del SII (versión 4.0).
Layout: formato hoja A4/oficio, con PDF417 barcode del TED.
"""
import io
import re as _re_caf
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, HRFlowable
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus.flowables import Flowable
import pdf417gen

from parser import DTE, TIPO_NOMBRE, CEDIBLE_TIPOS


def _compact_ted(ted_xml: str) -> str:
    """Strip all whitespace between XML tags in the TED.

    Node.js XMLSerializer expands <RNG> and <RSAPK> with newlines when re-signing.
    SII verifies FRMA over compact DA bytes and FRMT over compact DD bytes,
    so the barcode must contain the compacted form. Only inter-tag whitespace
    is stripped — text content (RS, M, etc.) is preserved.
    """
    return _re_caf.sub(r'>\s+<', '><', ted_xml)


MESES = ["enero","febrero","marzo","abril","mayo","junio",
         "julio","agosto","septiembre","octubre","noviembre","diciembre"]


def fmt_rut(rut: str) -> str:
    """77314475-3 → 77.314.475-3"""
    if "-" in rut:
        num, dv = rut.split("-")
        num = f"{int(num):,}".replace(",", ".")
        return f"{num}-{dv}"
    return rut


def fmt_money(v) -> str:
    if v is None:
        return ""
    return f"${int(v):,}".replace(",", ".")


def fmt_date(fecha: str) -> str:
    """2026-04-15 → Miércoles 15 de abril del 2026"""
    try:
        d = datetime.strptime(fecha, "%Y-%m-%d")
        dias = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
        return f"{dias[d.weekday()]} {d.day} de {MESES[d.month-1]} del {d.year}"
    except Exception:
        return fecha


def fmt_date_short(fecha: str) -> str:
    """2026-04-15 → 15/04/2026"""
    try:
        d = datetime.strptime(fecha, "%Y-%m-%d")
        return f"{d.day:02d}/{d.month:02d}/{d.year}"
    except Exception:
        return fecha


class PDF417Barcode(Flowable):
    """Flowable que renderiza un barcode PDF417 desde string XML del TED."""

    def __init__(self, ted_xml: str, width_cm=5.0, height_cm=2.0):
        super().__init__()
        self.ted_xml = ted_xml
        self.bc_width = width_cm * cm
        self.bc_height = height_cm * cm
        self._barcode_image = None
        self._build()

    def _build(self):
        try:
            codes = pdf417gen.encode(self.ted_xml.encode('iso-8859-1', errors='replace'), security_level=2, columns=12)
            image = pdf417gen.render_image(codes, scale=2, ratio=3)
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            buf.seek(0)
            self._barcode_image = buf
        except Exception as e:
            self._barcode_image = None
            self._error = str(e)

    def wrap(self, availWidth, availHeight):
        return self.bc_width, self.bc_height

    def draw(self):
        if self._barcode_image:
            from reportlab.lib.utils import ImageReader
            self._barcode_image.seek(0)
            img = ImageReader(self._barcode_image)
            self.canv.drawImage(img, 0, 0, self.bc_width, self.bc_height,
                                preserveAspectRatio=False)
        else:
            self.canv.rect(0, 0, self.bc_width, self.bc_height)
            self.canv.setFont("Helvetica", 6)
            self.canv.drawString(2, self.bc_height / 2, "[PDF417 error]")


def generate_pdf(dte: DTE, cedible: bool = False) -> bytes:
    buf = io.BytesIO()

    # Tamaño: oficio = 21.59 x 33.02 cm, usamos A4 (~21.0 x 29.7 cm)
    page_w, page_h = A4
    # Manual SII (muestras impresas): el Timbre Electrónico debe ir a una distancia
    # mínima de 2cm del borde izquierdo. usable_w se deriva de este margen, así que
    # subirlo reubica también el timbre (que se agrega al story más abajo).
    margin = 2.0 * cm

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=1.5 * cm,
    )

    styles = getSampleStyleSheet()
    normal = ParagraphStyle("normal", fontName="Helvetica", fontSize=8, leading=10)
    small = ParagraphStyle("small", fontName="Helvetica", fontSize=7, leading=9)
    bold = ParagraphStyle("bold", fontName="Helvetica-Bold", fontSize=8, leading=10)
    bold_lg = ParagraphStyle("bold_lg", fontName="Helvetica-Bold", fontSize=10, leading=12)
    center = ParagraphStyle("center", fontName="Helvetica", fontSize=8, leading=10, alignment=TA_CENTER)
    center_bold = ParagraphStyle("center_bold", fontName="Helvetica-Bold", fontSize=10, leading=12, alignment=TA_CENTER)
    right = ParagraphStyle("right", fontName="Helvetica", fontSize=8, leading=10, alignment=TA_RIGHT)

    usable_w = page_w - 2 * margin
    tipo_nombre = TIPO_NOMBRE.get(dte.tipo, f"DOCUMENTO TIPO {dte.tipo}")

    story = []

    # ─── HEADER: emisor (izq) + recuadro DTE (der) ──────────────────────────
    recuadro_w = 5.5 * cm
    emisor_w = usable_w - recuadro_w - 0.3 * cm

    # Recuadro tipo documento (rojo, borde)
    recuadro_data = [
        [Paragraph(f"R.U.T.: {fmt_rut(dte.rut_emisor)}", bold)],
        [Paragraph(tipo_nombre, center_bold)],
        [Paragraph(f"N° {dte.folio}", center_bold)],
    ]
    recuadro_table = Table(recuadro_data, colWidths=[recuadro_w])
    recuadro_table.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.8, colors.red),
        ("INNERGRID", (0,0), (-1,-1), 0, colors.white),
        ("BACKGROUND", (0,0), (-1,-1), colors.white),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LEFTPADDING", (0,0), (-1,-1), 4),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
    ]))

    # Zona emisor
    emisor_lines = [
        Paragraph(f"<b>{dte.razon_social}</b>", bold_lg),
        Paragraph(dte.giro, normal),
        Paragraph(f"{dte.dir_origen}, {dte.cmna_origen}", normal),
    ]

    header_data = [[emisor_lines, recuadro_table]]
    header_table = Table(header_data, colWidths=[emisor_w, recuadro_w + 0.3*cm])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("TOPPADDING", (0,0), (-1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 0),
    ]))
    story.append(header_table)

    # Unidad SII bajo el recuadro — va pegada con un pequeño spacer
    sii_unit = dte.unidad_sii or dte.cmna_origen
    story.append(Spacer(1, 1*mm))

    # Línea separadora
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.black))
    story.append(Spacer(1, 2*mm))

    # ─── FECHA ──────────────────────────────────────────────────────────────
    story.append(Paragraph(
        f"<b>S.I.I. – {sii_unit.upper()}</b> &nbsp;&nbsp;&nbsp; {fmt_date(dte.fecha_emision)}",
        normal
    ))
    story.append(Spacer(1, 2*mm))

    # ─── RECEPTOR ───────────────────────────────────────────────────────────
    receptor_data = [
        ["Señor(es):", dte.razon_social_receptor],
        ["R.U.T.:", fmt_rut(dte.rut_receptor)],
        ["Giro:", dte.giro_receptor or ""],
        ["Dirección:", f"{dte.dir_receptor or ''}, {dte.cmna_receptor or ''}"],
    ]
    rec_table = Table(receptor_data, colWidths=[2.2*cm, usable_w - 2.2*cm])
    rec_table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
        ("FONTNAME", (1,0), (1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 8),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING", (0,0), (-1,-1), 1),
        ("BOTTOMPADDING", (0,0), (-1,-1), 1),
    ]))
    story.append(rec_table)
    story.append(Spacer(1, 2*mm))

    # ─── REFERENCIAS ────────────────────────────────────────────────────────
    if dte.referencias:
        story.append(Paragraph("<b>Referencias a otros documentos</b>", bold))
        ref_header = [["Tipo Documento", "Folio", "Fecha", "Razón Referencia"]]
        ref_rows = []
        for r in dte.referencias:
            tipo_ref = TIPO_NOMBRE.get(int(r.tipo_doc), r.tipo_doc) if r.tipo_doc.isdigit() else r.tipo_doc
            ref_rows.append([tipo_ref, r.folio, fmt_date_short(r.fecha), r.razon or ""])
        ref_table = Table(ref_header + ref_rows,
                          colWidths=[6*cm, 1.8*cm, 2.2*cm, usable_w - 10*cm])
        ref_table.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTNAME", (0,1), (-1,-1), "Helvetica"),
            ("FONTSIZE", (0,0), (-1,-1), 7),
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("GRID", (0,0), (-1,-1), 0.3, colors.grey),
            ("TOPPADDING", (0,0), (-1,-1), 2),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2),
            ("LEFTPADDING", (0,0), (-1,-1), 3),
        ]))
        story.append(ref_table)
        story.append(Spacer(1, 2*mm))

    # ─── DETALLE ────────────────────────────────────────────────────────────
    if dte.items:
        det_header = [["#", "Descripción", "Cant.", "P. Unitario", "Dscto.", "Total"]]
        det_rows = []
        for it in dte.items:
            dscto = ""
            if it.descuento_pct:
                dscto = f"{it.descuento_pct}%"
                if it.descuento_monto:
                    dscto += f"\n{fmt_money(it.descuento_monto)}"
            elif it.descuento_monto:
                dscto = fmt_money(it.descuento_monto)
            det_rows.append([
                str(it.nro),
                it.nombre,
                f"{it.cantidad:,.0f}" if it.cantidad else "",
                fmt_money(it.precio_unitario) if it.precio_unitario else "",
                dscto,
                fmt_money(it.monto),
            ])
        det_table = Table(
            det_header + det_rows,
            colWidths=[0.7*cm, 7.5*cm, 1.5*cm, 2.5*cm, 2.0*cm, 2.8*cm]
        )
        det_table.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTNAME", (0,1), (-1,-1), "Helvetica"),
            ("FONTSIZE", (0,0), (-1,-1), 8),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#E8E8E8")),
            ("GRID", (0,0), (-1,-1), 0.3, colors.grey),
            ("ALIGN", (2,0), (-1,-1), "RIGHT"),
            ("TOPPADDING", (0,0), (-1,-1), 2),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2),
            ("LEFTPADDING", (0,0), (-1,-1), 3),
        ]))
        story.append(det_table)
        story.append(Spacer(1, 2*mm))

    # ─── TOTALES ────────────────────────────────────────────────────────────
    if dte.totales:
        t = dte.totales
        tot_rows = []

        if t.descuento_global_pct or t.descuento_global_monto:
            label = f"Descuento Global ({t.descuento_global_pct}%)" if t.descuento_global_pct else "Descuento Global"
            tot_rows.append([label, fmt_money(t.descuento_global_monto)])

        # Tipo 34 (exenta) y tipos sin IVA: solo Exento + Total
        if dte.tipo == 34:
            if t.monto_exento:
                tot_rows.append(["Monto Exento:", fmt_money(t.monto_exento)])
            tot_rows.append(["Monto Total:", fmt_money(t.monto_total)])
        else:
            if t.monto_neto:
                tot_rows.append(["Monto Neto:", fmt_money(t.monto_neto)])
            if t.monto_exento:
                tot_rows.append(["Monto Exento:", fmt_money(t.monto_exento)])
            if t.iva is not None:
                tasa = f" ({int(t.tasa_iva)}%)" if t.tasa_iva else ""
                tot_rows.append([f"IVA{tasa}:", fmt_money(t.iva)])
            # Factura de Compra (T46): IVA retenido total (cambio de sujeto).
            # Se resta del total: el proveedor recibe solo el neto.
            if t.iva_retenido:
                tot_rows.append(["IVA Retenido (100%):", f"-{fmt_money(t.iva_retenido)}"])
            tot_rows.append(["Monto Total:", fmt_money(t.monto_total)])

        tot_table = Table(tot_rows, colWidths=[usable_w - 3.5*cm, 3.5*cm])
        tot_table.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,-2), "Helvetica"),
            ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold"),
            ("FONTSIZE", (0,0), (-1,-1), 8),
            ("ALIGN", (0,0), (0,-1), "RIGHT"),
            ("ALIGN", (1,0), (1,-1), "RIGHT"),
            ("LINEABOVE", (0,-1), (-1,-1), 0.5, colors.black),
            ("TOPPADDING", (0,0), (-1,-1), 2),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ]))
        story.append(tot_table)

    story.append(Spacer(1, 3*mm))

    # ─── ACUSE DE RECIBO (solo cedible y tipos que lo requieren) ────────────
    if cedible and dte.tipo in CEDIBLE_TIPOS and dte.tipo not in {52}:
        acuse_text = (
            "El acuse de recibo que se declara en este acto, de acuerdo a lo dispuesto en la "
            "letra b) del Art. 4° y la letra c) del Art. 5° de la Ley 19.983, acredita que la "
            "entrega de mercadería(s) o servicio(s) prestado(s) ha(n) sido recibido(s)."
        )
        acuse_data = [
            [Paragraph("<b>Acuse de Recibo</b>", bold), ""],
            [Paragraph(acuse_text, small), ""],
            ["Nombre: ___________________________", "RUT: ________________"],
            ["Fecha: ____________________________", "Firma: _______________"],
            ["Recinto: __________________________", ""],
        ]
        acuse_table = Table(acuse_data, colWidths=[usable_w * 0.6, usable_w * 0.4])
        acuse_table.setStyle(TableStyle([
            ("BOX", (0,0), (-1,-1), 0.5, colors.black),
            ("SPAN", (0,0), (1,0)),
            ("SPAN", (0,1), (1,1)),
            ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
            ("FONTSIZE", (0,0), (-1,-1), 7),
            ("TOPPADDING", (0,0), (-1,-1), 2),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2),
            ("LEFTPADDING", (0,0), (-1,-1), 4),
        ]))
        story.append(acuse_table)
        story.append(Spacer(1, 2*mm))

    # ─── TIMBRE ELECTRÓNICO ──────────────────────────────────────────────────
    if dte.ted_xml:
        story.append(HRFlowable(width="100%", thickness=0.3, color=colors.grey))
        story.append(Spacer(1, 2*mm))

        ted_for_barcode = _compact_ted(dte.ted_xml)
        barcode = PDF417Barcode(ted_for_barcode, width_cm=5.0, height_cm=2.0)
        nro = dte.nro_resol or "0"
        year = (dte.fch_resol or "2026-01-01").split("-")[0]
        timbre_label = Paragraph(
            f"Timbre Electrónico SII<br/>"
            f"Resolución {nro} de {year} – "
            f"Verifique documento: <b>www.sii.cl</b>",
            ParagraphStyle("timbre", fontName="Helvetica", fontSize=6, leading=8)
        )

        timbre_data = [[barcode, timbre_label]]
        if cedible and dte.tipo in CEDIBLE_TIPOS:
            cedible_label = "CEDIBLE CON SU FACTURA" if dte.tipo == 52 else "CEDIBLE"
            timbre_data[0].append(
                Paragraph(f"<b>{cedible_label}</b>",
                          ParagraphStyle("ced", fontName="Helvetica-Bold", fontSize=10,
                                         alignment=TA_RIGHT))
            )
            col_w = [5.2*cm, usable_w - 9*cm, 2.8*cm]
        else:
            col_w = [5.2*cm, usable_w - 5.2*cm]

        timbre_table = Table([timbre_data], colWidths=col_w)
        timbre_table.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ("TOPPADDING", (0,0), (-1,-1), 0),
            ("BOTTOMPADDING", (0,0), (-1,-1), 0),
        ]))
        story.append(timbre_table)

    doc.build(story)
    return buf.getvalue()

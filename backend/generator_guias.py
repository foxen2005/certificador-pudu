"""PDF de muestras impresas para Guías de Despacho (52) — módulo aparte de
`generator.py`; reutiliza sus helpers aprobados (formato, PDF417, TED compacto).

Manual de Muestras Impresas:
- §"Guía de Despacho Electrónica": se debe señalar el tipo de traslado; en traslado
  interno los datos del receptor coinciden con el emisor; una operación que no
  constituye venta no lleva ejemplar cedible.
- §1.4: el cedible de la guía dice "CEDIBLE CON SU FACTURA" y lleva acuse de recibo.
"""
import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from generator import PDF417Barcode, _compact_ted, fmt_date, fmt_money, fmt_rut
from guias import IND_TRASLADO, TIPO_DESPACHO, GuiaParsed


def generate_pdf_guia(g: GuiaParsed, cedible: bool = False) -> bytes:
    buf = io.BytesIO()
    margin = 2.0 * cm
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=1.5 * cm)
    usable_w = A4[0] - 2 * margin

    normal = ParagraphStyle("normal", fontName="Helvetica", fontSize=8, leading=10)
    small = ParagraphStyle("small", fontName="Helvetica", fontSize=7, leading=9)
    bold = ParagraphStyle("bold", fontName="Helvetica-Bold", fontSize=8, leading=10)
    bold_lg = ParagraphStyle("bold_lg", fontName="Helvetica-Bold", fontSize=10, leading=12)
    center = ParagraphStyle("center", fontName="Helvetica", fontSize=8, leading=10, alignment=TA_CENTER)
    center_bold = ParagraphStyle("center_bold", fontName="Helvetica-Bold", fontSize=10, leading=12, alignment=TA_CENTER)

    story = []
    recuadro_w = 6.0 * cm
    recuadro = Table([
        [Paragraph(f"R.U.T.: {fmt_rut(g.rut_emisor)}", center_bold)],
        [Paragraph("GUÍA DE DESPACHO ELECTRÓNICA", center_bold)],
        [Paragraph(f"N° {g.folio}", center_bold)],
    ], colWidths=[recuadro_w])
    recuadro.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, colors.red), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    header = Table([[
        [Paragraph(f"<b>{g.razon_social}</b>", bold_lg), Paragraph(g.giro, normal), Paragraph(f"{g.dir_origen}, {g.cmna_origen}", normal)],
        [recuadro, Spacer(1, 1 * mm), Paragraph(f"<b>S.I.I. – {g.cmna_origen.upper()}</b>", center)],
    ]], colWidths=[usable_w - recuadro_w - 0.3 * cm, recuadro_w + 0.3 * cm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [header, Spacer(1, 1 * mm), HRFlowable(width="100%", thickness=0.5, color=colors.black), Spacer(1, 2 * mm)]
    story += [Paragraph(f"<b>Fecha de emisión:</b> {fmt_date(g.fecha)}", normal), Spacer(1, 2 * mm)]

    # Tipo de traslado / despacho (obligatorio en la muestra)
    rows = [["Tipo de traslado:", f"{g.ind_traslado} – {IND_TRASLADO.get(g.ind_traslado, '')}"]]
    if g.tipo_despacho:
        rows.append(["Tipo de despacho:", f"{g.tipo_despacho} – {TIPO_DESPACHO.get(g.tipo_despacho, '')}"])
    tr = Table(rows, colWidths=[3.2 * cm, usable_w - 3.2 * cm])
    tr.setStyle(TableStyle([("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
                            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F3F3")), ("BOX", (0, 0), (-1, -1), 0.3, colors.grey),
                            ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    story += [tr, Spacer(1, 2 * mm)]

    rec = Table([
        ["Señor(es):", g.razon_social_receptor],
        ["R.U.T.:", fmt_rut(g.rut_receptor)],
        ["Giro:", g.giro_receptor or ""],
        ["Dirección:", ", ".join(x for x in [g.dir_receptor, g.cmna_receptor] if x)],
    ], colWidths=[2.2 * cm, usable_w - 2.2 * cm])
    rec.setStyle(TableStyle([("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
                             ("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    story += [rec, Spacer(1, 2 * mm)]

    if g.caso:
        story += [Paragraph(f"<b>Referencia:</b> SET – {g.caso}", normal), Spacer(1, 2 * mm)]

    if g.es_venta:
        rows = [["#", "Descripción", "Cant.", "P. Unitario", "Total"]]
        for it in g.items:
            rows.append([str(it.nro), it.nombre, it.cantidad, fmt_money(it.precio) if it.precio else "", fmt_money(it.monto)])
        widths = [0.7 * cm, 9.3 * cm, 1.8 * cm, 2.6 * cm, 2.6 * cm]
    else:
        rows = [["#", "Descripción", "Cantidad"]]
        for it in g.items:
            rows.append([str(it.nro), it.nombre, it.cantidad])
        widths = [0.7 * cm, 13.3 * cm, 3.0 * cm]
    det = Table(rows, colWidths=widths)
    det.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
                             ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8E8E8")), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                             ("ALIGN", (2, 0), (-1, -1), "RIGHT")]))
    story += [det, Spacer(1, 2 * mm)]

    if g.es_venta and g.mnt_total:
        # El parser devuelve "" cuando el elemento no existe (guía de venta solo
        # exenta, o XML de otro emisor): no imprimir esas filas.
        filas = [(lbl, val) for lbl, val in [("Monto Neto:", g.mnt_neto), ("IVA (19%):", g.iva), ("Monto Total:", g.mnt_total)] if val]
        tot = Table([[lbl, fmt_money(val)] for lbl, val in filas], colWidths=[usable_w - 3.5 * cm, 3.5 * cm])
        tot.setStyle(TableStyle([("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
                                 ("ALIGN", (0, 0), (-1, -1), "RIGHT"), ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.black)]))
        story += [tot]
    story.append(Spacer(1, 3 * mm))

    if cedible and g.es_venta:
        acuse = Table([
            [Paragraph("<b>Acuse de Recibo</b>", bold), ""],
            [Paragraph("El acuse de recibo que se declara en este acto, de acuerdo a lo dispuesto en la letra b) del Art. 4° y la letra c) "
                       "del Art. 5° de la Ley 19.983, acredita que la entrega de mercadería(s) o servicio(s) prestado(s) ha(n) sido recibido(s).", small), ""],
            ["Nombre: ___________________________", "RUT: ________________"],
            ["Fecha: ____________________________", "Firma: _______________"],
            ["Recinto: __________________________", ""],
        ], colWidths=[usable_w * 0.6, usable_w * 0.4])
        acuse.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.black), ("SPAN", (0, 0), (1, 0)), ("SPAN", (0, 1), (1, 1)),
                                   ("FONTSIZE", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        story += [acuse, Spacer(1, 2 * mm)]

    if g.ted_xml:
        story += [HRFlowable(width="100%", thickness=0.3, color=colors.grey), Spacer(1, 2 * mm)]
        barcode = PDF417Barcode(_compact_ted(g.ted_xml), width_cm=5.0, height_cm=2.0)
        year = (g.fch_resol or "2026-01-01").split("-")[0]
        label = Paragraph(f"Timbre Electrónico SII<br/>Res. {g.nro_resol or '0'} de {year} – Verifique documento: www.sii.cl",
                          ParagraphStyle("timbre", fontName="Helvetica", fontSize=6, leading=8, alignment=TA_CENTER))
        col = Table([[barcode], [label]], colWidths=[5.2 * cm])
        col.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0)]))
        right = Paragraph("<b>CEDIBLE CON SU FACTURA</b>", ParagraphStyle("ced", fontName="Helvetica-Bold", fontSize=10, alignment=TA_RIGHT)) if (cedible and g.es_venta) else Spacer(0, 0)
        tt = Table([[col, right]], colWidths=[5.2 * cm, usable_w - 5.2 * cm], hAlign="LEFT")
        tt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        story.append(tt)

    doc.build(story)
    return buf.getvalue()

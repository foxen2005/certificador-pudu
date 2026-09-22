"""PDF de muestras impresas para documentos de Exportación (110/111/112).

Módulo aparte de `generator.py` (que queda intacto para el set básico); reutiliza
sus helpers ya aprobados por el SII (formato RUT/fecha, PDF417, compactado del TED).

Manual de Muestras Impresas §"Documentos de Exportación": cuando hay transporte de
mercaderías son obligatorios en la muestra Puerto de Embarque, Puerto de
Desembarque, Total de Bultos, RUT y País receptor y Tipo de Moneda. La factura de
exportación NO está en la lista de documentos con ejemplar cedible (§1.4).
"""
import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from exportacion import COD_CLAU_VENTA, COD_MOD_VENTA, COD_VIA_TRANSP, TIPO_NOMBRE_EXP, DocExpParsed

# Formato DTE — tipos de referencia usados en exportación
REF_NOMBRE = {"801": "ORDEN DE COMPRA", "802": "NOTA DE PEDIDO", "803": "CONTRATO", "804": "RESOLUCIÓN",
              "807": "DUS", "808": "B/L (CONOCIMIENTO DE EMBARQUE)", "809": "AWB (AIR WAYBILL)", "810": "MIC/DTA",
              "811": "CARTA DE PORTE", "812": "RESOLUCIÓN DEL SNA", "813": "PASAPORTE"}
from generator import PDF417Barcode, _compact_ted, fmt_date, fmt_date_short, fmt_rut


def _money(v: str, moneda: str = "") -> str:
    """'1250' → '1.250,00 DOLAR USA' (miles con punto, decimales con coma)."""
    if v in ("", None):
        return ""
    try:
        d = float(v)
    except ValueError:
        return v
    s = f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} {moneda}".strip()


def _clp(v: str) -> str:
    try:
        return "$" + f"{int(float(v)):,}".replace(",", ".")
    except ValueError:
        return v


def generate_pdf_exportacion(dte: DocExpParsed) -> bytes:
    buf = io.BytesIO()
    margin = 2.0 * cm
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=margin, rightMargin=margin,
                            topMargin=margin, bottomMargin=1.5 * cm)
    page_w, _ = A4
    usable_w = page_w - 2 * margin

    normal = ParagraphStyle("normal", fontName="Helvetica", fontSize=8, leading=10)
    small = ParagraphStyle("small", fontName="Helvetica", fontSize=7, leading=9)
    bold = ParagraphStyle("bold", fontName="Helvetica-Bold", fontSize=8, leading=10)
    bold_lg = ParagraphStyle("bold_lg", fontName="Helvetica-Bold", fontSize=10, leading=12)
    center = ParagraphStyle("center", fontName="Helvetica", fontSize=8, leading=10, alignment=TA_CENTER)
    center_bold = ParagraphStyle("center_bold", fontName="Helvetica-Bold", fontSize=10, leading=12, alignment=TA_CENTER)

    story = []

    # ── Encabezado: emisor + recuadro (§1.1.4) ──────────────────────────────
    recuadro_w = 6.0 * cm
    recuadro = Table([
        [Paragraph(f"R.U.T.: {fmt_rut(dte.rut_emisor)}", center_bold)],
        [Paragraph(TIPO_NOMBRE_EXP.get(dte.tipo, f"TIPO {dte.tipo}"), center_bold)],
        [Paragraph(f"N° {dte.folio}", center_bold)],
    ], colWidths=[recuadro_w])
    recuadro.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, colors.red),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    emisor_col = [
        Paragraph(f"<b>{dte.razon_social}</b>", bold_lg),
        Paragraph(dte.giro, normal),
        Paragraph(f"{dte.dir_origen}, {dte.cmna_origen}", normal),
    ]
    recuadro_col = [recuadro, Spacer(1, 1 * mm), Paragraph(f"<b>S.I.I. – {dte.cmna_origen.upper()}</b>", center)]
    header = Table([[emisor_col, recuadro_col]], colWidths=[usable_w - recuadro_w - 0.3 * cm, recuadro_w + 0.3 * cm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [header, Spacer(1, 1 * mm), HRFlowable(width="100%", thickness=0.5, color=colors.black), Spacer(1, 2 * mm)]
    story += [Paragraph(f"<b>Fecha de emisión:</b> {fmt_date(dte.fecha)}", normal), Spacer(1, 2 * mm)]

    # ── Receptor extranjero ─────────────────────────────────────────────────
    pais = dte.aduana.get("CodPaisRecep", "")
    rec = Table([
        ["Señor(es):", dte.razon_social_receptor],
        ["R.U.T.:", fmt_rut(dte.rut_receptor)],
        ["Dirección:", ", ".join(x for x in [dte.dir_receptor, dte.ciudad_receptor] if x)],
        ["País receptor:", f"código Aduana {pais}" if pais else "—"],
    ], colWidths=[2.6 * cm, usable_w - 2.6 * cm])
    rec.setStyle(TableStyle([("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
                             ("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 1),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    story += [rec, Spacer(1, 2 * mm)]

    # ── Datos de exportación / Aduana (obligatorios en la muestra) ─────────
    a = dte.aduana
    exp_rows = [
        ["Moneda:", dte.moneda, "Modalidad de venta:", COD_MOD_VENTA.get(a.get("CodModVenta", ""), a.get("CodModVenta", "—"))],
        ["Cláusula de venta:", COD_CLAU_VENTA.get(a.get("CodClauVenta", ""), a.get("CodClauVenta", "—")),
         "Vía de transporte:", COD_VIA_TRANSP.get(a.get("CodViaTransp", ""), a.get("CodViaTransp", "—"))],
        ["Puerto embarque:", a.get("CodPtoEmbarque", "—"), "Puerto desembarque:", a.get("CodPtoDesemb", "—")],
        ["Total bultos:", a.get("TotBultos", "—"), "Peso bruto:", (a.get("PesoBruto", "") + " (unid. " + a.get("CodUnidPesoBruto", "") + ")") if a.get("PesoBruto") else "—"],
    ]
    exp_t = Table(exp_rows, colWidths=[3.2 * cm, usable_w / 2 - 3.2 * cm, 3.6 * cm, usable_w / 2 - 3.6 * cm])
    exp_t.setStyle(TableStyle([("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                               ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F3F3")),
                               ("BOX", (0, 0), (-1, -1), 0.3, colors.grey), ("TOPPADDING", (0, 0), (-1, -1), 2),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    story += [Paragraph("<b>Datos de exportación</b>", bold), exp_t, Spacer(1, 2 * mm)]

    # ── Referencias ─────────────────────────────────────────────────────────
    if dte.referencias:
        rows = [["Tipo Documento", "Folio", "Fecha", "Razón Referencia"]]
        for r in dte.referencias:
            nombre = REF_NOMBRE.get(r.tipo_doc) or (TIPO_NOMBRE_EXP.get(int(r.tipo_doc), r.tipo_doc) if r.tipo_doc.isdigit() else r.tipo_doc)
            rows.append([nombre, r.folio, fmt_date_short(r.fecha), r.razon or ""])
        ref_t = Table(rows, colWidths=[6.5 * cm, 1.8 * cm, 2.2 * cm, usable_w - 10.5 * cm])
        ref_t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 7),
                                   ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey)]))
        story += [Paragraph("<b>Referencias a otros documentos</b>", bold), ref_t, Spacer(1, 2 * mm)]

    # ── Detalle (ítems exentos, precios en la moneda de la transacción) ────
    rows = [["#", "Descripción", "IE", "Cant.", "Unid.", "P. Unitario", "Dscto./Rec.", "Total"]]
    for it in dte.items:
        ajuste = ""
        if it.descuento_monto:
            ajuste = f"-{_money(it.descuento_monto)}" + (f" ({it.descuento_pct}%)" if it.descuento_pct else "")
        if it.recargo_monto:
            ajuste = (ajuste + " " if ajuste else "") + f"+{_money(it.recargo_monto)}" + (f" ({it.recargo_pct}%)" if it.recargo_pct else "")
        rows.append([str(it.nro), Paragraph(it.nombre, small), "EX", _money(it.cantidad).replace(",00", "") if it.cantidad else "",
                     it.unidad, _money(it.precio) if it.precio else "", Paragraph(ajuste, small), _money(it.monto)])
    det = Table(rows, colWidths=[0.7 * cm, 5.6 * cm, 0.8 * cm, 1.4 * cm, 1.1 * cm, 2.3 * cm, 2.5 * cm, 2.6 * cm])
    det.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
                             ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8E8E8")), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                             ("ALIGN", (3, 0), (-1, -1), "RIGHT")]))
    story += [Paragraph(f"<b>Detalle</b> — montos expresados en {dte.moneda}", small), det, Spacer(1, 2 * mm)]

    # ── Totales: en moneda + conversión a pesos (OtraMoneda) ───────────────
    tot_rows = []
    # Recargos/descuentos globales (flete, seguro, comisiones): parte del Monto Exento
    for rg in dte.recargos:
        signo = "+" if rg.tipo == "R" else "-"
        tot_rows.append([f"{'Recargo' if rg.tipo == 'R' else 'Descuento'} global — {rg.glosa}:", f"{signo}{_money(rg.valor, dte.moneda)}"])
    tot_rows += [
        ["Monto Exento:", _money(dte.mnt_exe, dte.moneda)],
        [f"Total ({dte.moneda}):", _money(dte.mnt_total, dte.moneda)],
        [f"Tipo de cambio (1 {dte.moneda} = CLP):", ("$" + _money(dte.tipo_cambio)) if dte.tipo_cambio else "—"],
        ["Total en pesos (CLP):", _clp(dte.mnt_total_clp) if dte.mnt_total_clp else "—"],
    ]
    tot = Table(tot_rows, colWidths=[usable_w - 5 * cm, 5 * cm])
    fila_total = len(dte.recargos) + 1   # fila "Total (moneda)"
    tot.setStyle(TableStyle([("FONTNAME", (0, fila_total), (-1, fila_total), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
                             ("ALIGN", (0, 0), (-1, -1), "RIGHT"), ("LINEABOVE", (0, fila_total), (-1, fila_total), 0.5, colors.black)]))
    if dte.fma_pag_exp == "21":
        story.append(Paragraph("Forma de pago de exportación: SIN PAGO (código 21) — Monto Total 0 según Formato DTE.", small))
    if dte.ind_servicio:
        story.append(Paragraph(f"Indicador de servicio: {dte.ind_servicio} (3 = servicio de exportación, 4 = hotelería, 5 = transporte internacional)", small))
    story += [tot, Spacer(1, 4 * mm)]

    # ── Timbre (§1.5) — sin cedible ni acuse: no aplica a exportación ──────
    if dte.ted_xml:
        story += [HRFlowable(width="100%", thickness=0.3, color=colors.grey), Spacer(1, 2 * mm)]
        barcode = PDF417Barcode(_compact_ted(dte.ted_xml), width_cm=5.0, height_cm=2.0)
        year = (dte.fch_resol or "2026-01-01").split("-")[0]
        label = Paragraph(f"Timbre Electrónico SII<br/>Res. {dte.nro_resol or '0'} de {year} – Verifique documento: www.sii.cl",
                          ParagraphStyle("timbre", fontName="Helvetica", fontSize=6, leading=8, alignment=TA_CENTER))
        col = Table([[barcode], [label]], colWidths=[5.2 * cm])
        col.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                 ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0)]))
        story.append(Table([[col, Spacer(0, 0)]], colWidths=[5.2 * cm, usable_w - 5.2 * cm], hAlign="LEFT"))

    doc.build(story)
    return buf.getvalue()

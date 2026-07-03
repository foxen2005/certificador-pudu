"""
Test de certificación real con el Set de Pruebas PUDU.
Lee los archivos reales del set (Set de Pruebas, CAFs, P12, DATOS)
y ejecuta el flujo completo de certificación.

Uso:
    cd backend
    python test_certificacion.py

Salida en:  backend/test_output/
"""
import sys
import os
import datetime

PUDU_SET    = r"d:\PUDU\Certificador Pudu\sets\pudu_78392059K"
OUTPUT_BASE = r"d:\PUDU\Certificador Pudu\output"
OUTPUT_DIR = os.path.join(OUTPUT_BASE, datetime.datetime.now().strftime("certificacion_%Y%m%d_%H%M"))
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Módulos del certificador ──────────────────────────────────────────────────
from set_parser import parse_set_pruebas
from dte_builder import CAF, build_dte_xml, build_unsigned_envio_dte
from parser import parse_envio_dte, TIPO_NOMBRE, CEDIBLE_TIPOS
from generator import generate_pdf
from validator import validate_pdf
from libro_builder import build_unsigned_libro_ventas, build_unsigned_libro_compras


LIBRO_SIGNER_JS = r"d:\PUDU\Certificador Pudu\verify\firmar_libro.js"


def _firmar_libro_node(unsigned_xml: bytes, p12_path: str, pfx_password: str, out_dir: str, label: str) -> bytes:
    """Firma un libro (LibroCompraVenta) usando Node.js/signer.js."""
    import subprocess, tempfile
    unsigned_path = os.path.join(out_dir, f"{label}_UNSIGNED.xml")
    signed_path   = os.path.join(out_dir, f"{label}_SIGNED.tmp.xml")
    with open(unsigned_path, "wb") as f:
        f.write(unsigned_xml)
    result = subprocess.run(
        ["node", LIBRO_SIGNER_JS, unsigned_path, signed_path, p12_path, pfx_password],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"Error firmando {label}: {result.stderr}")
    with open(signed_path, "rb") as f:
        signed = f.read()
    os.remove(signed_path)
    os.remove(unsigned_path)
    return signed


def leer_datos(path: str) -> dict:
    with open(path, encoding="iso-8859-1") as f:
        lines = [l.rstrip("\n") for l in f if l.strip()]
    return {
        "rut":        lines[3],
        "rut_envia":  lines[1],
        "razon_social": lines[2],
        "giro":       lines[5] if len(lines) > 5 else "",
        "acteco":     lines[6] if len(lines) > 6 else "999999",
        "dir_origen": lines[7] if len(lines) > 7 else "",
        "cmna_origen":lines[8] if len(lines) > 8 else "",
        "nro_resol":  lines[9] if len(lines) > 9 else "0",
        "fch_resol":  lines[10] if len(lines) > 10 else datetime.date.today().isoformat(),
        "_pfx_pass":  lines[4],
    }


RECEPTOR_PRUEBA = {
    "rut": "77221286-0",
    "razon_social": "C&C SPA",
    "giro": "VENTA AL POR MENOR DE ALIMENTOS EN COMER",
    "dir": "AVDA AUSTRAL 1780 JARDIN ORIENTE II",
    "cmna": "Puerto Montt",
}


def run():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 60)
    print("  SII CERTIFICADOR — TEST CON SET PUDU")
    print("=" * 60)

    # ── 1. Leer archivos del set ──────────────────────────────────────────────
    print("\n[1/6] Leyendo archivos del set PUDU...")

    set_path  = r"d:\PUDU\Certificador Pudu\sets\SIISetDePruebas78392059K-1705.txt"
    datos_path = os.path.join(PUDU_SET, "DATOS.txt")
    p12_path  = os.path.join(PUDU_SET, "15996452-3_2025-11-14.p12")

    with open(set_path, encoding="iso-8859-1") as f:
        set_txt = f.read()
    with open(p12_path, "rb") as f:
        pfx_bytes = f.read()

    emisor_data = leer_datos(datos_path)
    pfx_password = emisor_data.pop("_pfx_pass")

    print(f"      * Set: {os.path.basename(set_path)}")
    print(f"      * Empresa: {emisor_data['razon_social']} ({emisor_data['rut']})")
    print(f"      ✓ Representante: {emisor_data['rut_envia']}")

    # ── 2. Parsear el Set de Pruebas ──────────────────────────────────────────
    print("\n[2/6] Parseando Set de Pruebas...")
    sp = parse_set_pruebas(set_txt)

    tipos_requeridos = {c.tipo_doc for c in sp.casos}
    print(f"      ✓ Casos: {len(sp.casos)}  |  Tipos DTE: {sorted(tipos_requeridos)}")
    for caso in sp.casos:
        ref = f"  → ref caso {caso.referencia_caso}" if caso.referencia_caso else ""
        print(f"        • CASO {caso.numero}  T{caso.tipo_doc}  {len(caso.items)} items{ref}")
    print(f"      ✓ Atención básico:  {sp.nro_atencion_basico}")
    print(f"      ✓ Atención ventas:  {sp.nro_atencion_ventas}")
    print(f"      ✓ Atención compras: {sp.nro_atencion_compras}")
    print(f"      ✓ Compras libro:    {len(sp.libro_compras)} entradas")

    # ── 3. Cargar CAFs ────────────────────────────────────────────────────────
    print("\n[3/6] Cargando CAFs...")
    caf_files = {
        33: "33_1-100.xml",
        56: "56_1-100.xml",
        61: "61_1-100.xml",
    }
    cafs: dict[int, CAF] = {}
    for tipo in sorted(tipos_requeridos):
        fname = caf_files.get(tipo)
        if not fname:
            print(f"      ✗ Sin CAF para T{tipo} — abortando")
            sys.exit(1)
        caf_path = os.path.join(PUDU_SET, fname)
        with open(caf_path, "rb") as f:
            cafs[tipo] = CAF(f.read())
        print(f"      ✓ CAF T{tipo}  folios {cafs[tipo].desde}–{cafs[tipo].hasta}  RUT {cafs[tipo].rut_emisor}")

    # ── 4. Resolver items NC/ND y generar DTEs ────────────────────────────────
    print("\n[4/6] Generando DTEs firmados...")
    import copy as _copy
    caso_by_num = {c.numero: c for c in sp.casos}

    # Resolver items para NC/ND antes de generar
    from dte_builder import _cod_ref as _get_cod_ref
    for caso in sp.casos:
        if not caso.referencia_caso:
            continue
        ref = caso_by_num.get(caso.referencia_caso)
        if not ref:
            continue

        # CodRef=2 (Corrige Texto): el NC no debe tener montos — regla SII REF-2-781.
        # Dejar items con precio=0 para que MntTotal=0.
        if caso.razon_referencia and _get_cod_ref(caso.razon_referencia) == "2":
            if not caso.items:
                from set_parser import ItemSet as _ItemSet
                caso.items = [_ItemSet(nombre=caso.razon_referencia[:80], cantidad=1, precio_unitario=0)]
            else:
                for item in caso.items:
                    item.precio_unitario = 0.0
            continue

        if not caso.items:
            caso.items = _copy.deepcopy(ref.items)
        else:
            ref_by_nombre = {it.nombre.upper(): it for it in ref.items}
            for item in caso.items:
                if item.precio_unitario == 0:
                    ref_it = ref_by_nombre.get(item.nombre.upper())
                    if ref_it:
                        item.precio_unitario = ref_it.precio_unitario
                        if ref_it.descuento_pct is not None:
                            item.descuento_pct = ref_it.descuento_pct
        if not caso.items:
            from set_parser import ItemSet as _ItemSet
            razon = caso.razon_referencia or "REFERENCIA"
            caso.items = [_ItemSet(nombre=razon[:80], cantidad=1, precio_unitario=0)]

    timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # Folios ya enviados al SII (se acumulan con cada envío para evitar DTE-3-100 Repetido)
    # Actualizar después de cada envío exitoso.
    FOLIOS_YA_ENVIADOS: dict[int, set] = {
        33: {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36},
        56: {1, 2, 3, 4, 5, 6, 7, 8, 9},
        61: {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27},
    }
    folios_usados: dict[int, set] = {t: set(FOLIOS_YA_ENVIADOS.get(t, set())) for t in cafs}
    folios_ref:    dict[str, int] = {}
    tipos_ref:     dict[str, int] = {c.numero: c.tipo_doc for c in sp.casos}
    dtes_xml = []

    for caso in sp.casos:
        caf = cafs[caso.tipo_doc]
        folio = caf.next_folio(folios_usados[caso.tipo_doc])
        folios_usados[caso.tipo_doc].add(folio)
        folios_ref[caso.numero] = folio
        dte = build_dte_xml(
            caso, folio, emisor_data, RECEPTOR_PRUEBA,
            caf, timestamp, folios_ref, tipos_ref
        )
        dtes_xml.append(dte)
        ref_info = f"  [ref T{tipos_ref.get(caso.referencia_caso, '?')} F{folios_ref.get(caso.referencia_caso, '?')}]" \
                   if caso.referencia_caso else ""
        print(f"      ✓ CASO {caso.numero}  →  T{caso.tipo_doc} Folio {folio}{ref_info}")

    # ── 5. Firmar EnvioDTE con Node.js/signer.js (misma librería que el pudu server) ──
    print("\n[5/6] Firmando EnvioDTE...")
    rut_clean = emisor_data["rut"].replace("-", "").replace(".", "")

    # 5a. Generar EnvioDTE sin firmas
    unsigned_xml = build_unsigned_envio_dte(dtes_xml, emisor_data, timestamp)
    unsigned_path = os.path.join(OUTPUT_DIR, f"EnvioDTE_UNSIGNED_{rut_clean}.xml")
    with open(unsigned_path, "wb") as f:
        f.write(unsigned_xml)

    # 5b. Firmar con Node.js (xml-crypto, igual que pudu server en producción)
    envio_path = os.path.join(OUTPUT_DIR, f"EnvioDTE_{rut_clean}.xml")
    signer_js   = r"d:\PUDU\Certificador Pudu\verify\firmar_envio.js"
    import subprocess
    result = subprocess.run(
        ["node", signer_js, unsigned_path, envio_path, p12_path, pfx_password],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"      ✗ Error al firmar: {result.stderr}")
        sys.exit(1)
    for line in result.stderr.strip().splitlines():
        print(f"      {line}")

    with open(envio_path, "rb") as f:
        envio_xml = f.read()
    os.remove(unsigned_path)  # limpiar intermedio
    print(f"      ✓ {len(envio_xml):,} bytes  →  {os.path.basename(envio_path)}")

    # ── 6. PDFs + validación + Libros ─────────────────────────────────────────
    print("\n[6/6] Generando PDFs y libros...")
    dtes_parsed = parse_envio_dte(envio_xml)
    resultados  = []

    for dte in dtes_parsed:
        for cedible in ([False, True] if dte.tipo in CEDIBLE_TIPOS else [False]):
            suffix   = "_CEDIBLE" if cedible else ""
            pdf_name = f"DTE_T{dte.tipo}F{dte.folio}{suffix}.pdf"
            pdf_bytes = generate_pdf(dte, cedible=cedible)
            with open(os.path.join(OUTPUT_DIR, pdf_name), "wb") as f:
                f.write(pdf_bytes)

            val   = validate_pdf(pdf_bytes, pdf_name)
            icono = "✓" if val.passed else "✗"
            label = TIPO_NOMBRE.get(dte.tipo, f"T{dte.tipo}")
            extra = "  [cedible]" if cedible else ""
            print(f"      {icono}  {pdf_name:<30}  {label}{extra}")
            if not val.passed:
                for chk in val.checks:
                    if not chk.passed:
                        print(f"               ✗ {chk.name}: {chk.detail}")
            resultados.append({"aprobado": val.passed, "tipo": dte.tipo, "folio": dte.folio})

    libro_v_ok = libro_c_ok = False

    # Libros usan periodo pre-RCV (2000-01) para certificación ESPECIAL.
    # Solo TmstFirma lleva la hora real — se reemplaza después de construir.
    LIBRO_PERIODO_TIMESTAMP = "2000-02-01T00:00:00"

    if sp.nro_atencion_ventas:
        lv_unsigned = build_unsigned_libro_ventas(
            sp.casos, folios_ref, RECEPTOR_PRUEBA, emisor_data,
            LIBRO_PERIODO_TIMESTAMP, sp.nro_atencion_ventas,
        )
        lv_unsigned = lv_unsigned.replace(
            LIBRO_PERIODO_TIMESTAMP.encode("iso-8859-1"),
            timestamp.encode("iso-8859-1"),
        )
        lv = _firmar_libro_node(lv_unsigned, p12_path, pfx_password, OUTPUT_DIR, f"LibroVentas_{rut_clean}")
        lv_path = os.path.join(OUTPUT_DIR, f"LibroVentas_{rut_clean}.xml")
        with open(lv_path, "wb") as f:
            f.write(lv)
        libro_v_ok = True
        print(f"      ✓  LibroVentas_{rut_clean}.xml  ({len(lv):,} bytes)")

    if sp.nro_atencion_compras and sp.libro_compras:
        lc_unsigned = build_unsigned_libro_compras(
            sp.libro_compras, emisor_data,
            LIBRO_PERIODO_TIMESTAMP, sp.nro_atencion_compras,
            fct_prop=sp.fct_prop_iva_uso_comun,
        )
        lc_unsigned = lc_unsigned.replace(
            LIBRO_PERIODO_TIMESTAMP.encode("iso-8859-1"),
            timestamp.encode("iso-8859-1"),
        )
        lc = _firmar_libro_node(lc_unsigned, p12_path, pfx_password, OUTPUT_DIR, f"LibroCompras_{rut_clean}")
        lc_path = os.path.join(OUTPUT_DIR, f"LibroCompras_{rut_clean}.xml")
        with open(lc_path, "wb") as f:
            f.write(lc)
        libro_c_ok = True
        print(f"      ✓  LibroCompras_{rut_clean}.xml  ({len(lc):,} bytes)")

    # ── Resumen ───────────────────────────────────────────────────────────────
    aprobados  = sum(1 for r in resultados if r["aprobado"])
    rechazados = len(resultados) - aprobados

    print("\n" + "=" * 60)
    print("  RESUMEN")
    print("=" * 60)
    print(f"  DTEs generados : {len(dtes_xml)}")
    print(f"  PDFs generados : {len(resultados)}")
    print(f"  PDFs aprobados : {aprobados}  {'✓' if rechazados == 0 else '✗'}")
    print(f"  PDFs rechazados: {rechazados}")
    print(f"  Libro Ventas   : {'✓' if libro_v_ok else '✗'}")
    print(f"  Libro Compras  : {'✓' if libro_c_ok else '✗'}")
    print(f"\n  Archivos listos en: {OUTPUT_DIR}")
    print("=" * 60)

    if rechazados:
        print("\n  ⚠  Hay PDFs rechazados — revisa los checks arriba.")
        sys.exit(1)
    else:
        print("\n  ✓  Certificación de prueba completada sin errores.\n")


if __name__ == "__main__":
    run()

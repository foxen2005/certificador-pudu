"""
Script enfocado: genera y firma SOLO el Libro de Compras usando el pudu server.
No genera DTEs ni libro de ventas — solo el libro de compras listo para subir al SII.

Uso:
    cd backend
    python firmar_libro_compras.py

Salida:
    output/librocompras_YYYYMMDD_HHMM/LibroCompras_<RUT>.xml
"""
import os
import sys
import datetime
import subprocess

PUDU_SET        = r"f:\PUDU\Certificador Pudu\sets\pudu_78392059K"
OUTPUT_BASE     = r"f:\PUDU\Certificador Pudu\output"
LIBRO_SIGNER_JS = r"f:\PUDU\Certificador Pudu\verify\firmar_libro.js"

from set_parser import parse_set_pruebas
from libro_builder import build_unsigned_libro_compras


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


def main():
    timestamp_dir = datetime.datetime.now().strftime("librocompras_%Y%m%d_%H%M")
    output_dir = os.path.join(OUTPUT_BASE, timestamp_dir)
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print("  FIRMAR SOLO LIBRO DE COMPRAS — pudu server")
    print("=" * 60)

    set_path   = os.path.join(PUDU_SET, "SIISetDePruebas78392059K.txt")
    datos_path = os.path.join(PUDU_SET, "DATOS.txt")
    p12_path   = os.path.join(PUDU_SET, "15996452-3_2025-11-14.p12")

    with open(set_path, encoding="iso-8859-1") as f:
        set_txt = f.read()
    emisor_data  = leer_datos(datos_path)
    pfx_password = emisor_data.pop("_pfx_pass")

    print(f"\n[1/3] Set: {os.path.basename(set_path)}")
    print(f"      Empresa: {emisor_data['razon_social']} ({emisor_data['rut']})")

    sp = parse_set_pruebas(set_txt)

    if not sp.nro_atencion_compras:
        print("\n  ✗  El set no contiene número de atención para Libro de Compras.")
        sys.exit(1)
    if not sp.libro_compras:
        print("\n  ✗  El set no contiene entradas de Libro de Compras.")
        sys.exit(1)

    print(f"\n[2/3] Entradas libro compras: {len(sp.libro_compras)}")
    print(f"      Nro atención SII: {sp.nro_atencion_compras}")
    for item in sp.libro_compras:
        print(f"        {item.tipo_doc}  Folio {item.folio}  Total {item.monto_total}")

    timestamp_real = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    LIBRO_PERIODO_TIMESTAMP = "2000-01-01T00:00:00"

    unsigned_xml = build_unsigned_libro_compras(
        sp.libro_compras, emisor_data,
        LIBRO_PERIODO_TIMESTAMP, sp.nro_atencion_compras,
    )
    # TmstFirma debe ser la hora real de firma, no la del periodo
    unsigned_xml = unsigned_xml.replace(
        LIBRO_PERIODO_TIMESTAMP.encode("iso-8859-1"),
        timestamp_real.encode("iso-8859-1"),
    )

    rut_clean    = emisor_data["rut"].replace("-", "").replace(".", "")
    unsigned_path = os.path.join(output_dir, f"LibroCompras_{rut_clean}_UNSIGNED.xml")
    signed_path   = os.path.join(output_dir, f"LibroCompras_{rut_clean}.xml")

    with open(unsigned_path, "wb") as f:
        f.write(unsigned_xml)

    print(f"\n[3/3] Firmando con pudu server (xml-crypto)...")
    result = subprocess.run(
        ["node", LIBRO_SIGNER_JS, unsigned_path, signed_path, p12_path, pfx_password],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"      ✗ Error: {result.stderr}")
        sys.exit(1)
    for line in result.stderr.strip().splitlines():
        print(f"      {line}")

    os.remove(unsigned_path)
    size = os.path.getsize(signed_path)

    print("\n" + "=" * 60)
    print(f"  OK  LibroCompras_{rut_clean}.xml  ({size:,} bytes)")
    print(f"  Listo en: {output_dir}")
    print(f"  Nro atención SII: {sp.nro_atencion_compras}")
    print("=" * 60)


if __name__ == "__main__":
    main()

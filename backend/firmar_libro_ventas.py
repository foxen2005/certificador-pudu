"""
Script enfocado: genera y firma SOLO el Libro de Ventas usando el pudu server.
No genera DTEs ni libro de compras — solo el libro de ventas listo para subir al SII.

Uso:
    python firmar_libro_ventas.py

Salida:
    Carpeta nueva con LibroVentas_<RUT>.xml firmado
"""
import os
import sys
import datetime
import subprocess

PUDU_SET    = r"d:\PUDU\Certificador Pudu\sets\pudu_78392059K"
OUTPUT_BASE = r"d:\PUDU\Certificador Pudu\output"
LIBRO_SIGNER_JS = r"d:\PUDU\Certificador Pudu\verify\firmar_libro.js"

from set_parser import parse_set_pruebas
from dte_builder import CAF, build_dte_xml
from libro_builder import build_unsigned_libro_ventas


RECEPTOR_PRUEBA = {
    "rut": "77221286-0",
    "razon_social": "C&C SPA",
    "giro": "VENTA AL POR MENOR DE ALIMENTOS EN COMER",
    "dir": "AVDA AUSTRAL 1780 JARDIN ORIENTE II",
    "cmna": "Puerto Montt",
}


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


def main():
    timestamp_dir = datetime.datetime.now().strftime("libroventas_%Y%m%d_%H%M")
    output_dir = os.path.join(OUTPUT_BASE, timestamp_dir)
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print("  FIRMAR SOLO LIBRO DE VENTAS — pudu server")
    print("=" * 60)

    set_path  = os.path.join(PUDU_SET, "SIISetDePruebas78392059K.txt")
    datos_path = os.path.join(PUDU_SET, "DATOS.txt")
    p12_path  = os.path.join(PUDU_SET, "15996452-3_2025-11-14.p12")

    with open(set_path, encoding="iso-8859-1") as f:
        set_txt = f.read()
    emisor_data = leer_datos(datos_path)
    pfx_password = emisor_data.pop("_pfx_pass")

    print(f"\n[1/4] Set: {os.path.basename(set_path)}")
    print(f"      Empresa: {emisor_data['razon_social']} ({emisor_data['rut']})")

    # Parsear set
    sp = parse_set_pruebas(set_txt)
    print(f"\n[2/4] Casos: {len(sp.casos)}  |  Atención ventas: {sp.nro_atencion_ventas}")

    # Necesitamos asignar folios a cada caso (para que el libro tenga los folios correctos)
    # Cargar CAFs solo para conocer los rangos
    tipos_requeridos = {c.tipo_doc for c in sp.casos}
    caf_files = {33: "33_1-100.xml", 56: "56_1-100.xml", 61: "61_1-100.xml"}
    cafs = {}
    for tipo in sorted(tipos_requeridos):
        fname = caf_files.get(tipo)
        if not fname:
            print(f"      ✗ Sin CAF para T{tipo}")
            sys.exit(1)
        with open(os.path.join(PUDU_SET, fname), "rb") as f:
            cafs[tipo] = CAF(f.read())

    # Resolver items NC/ND (para que el libro tenga los montos correctos)
    import copy as _copy
    from dte_builder import _cod_ref as _get_cod_ref
    caso_by_num = {c.numero: c for c in sp.casos}
    for caso in sp.casos:
        if not caso.referencia_caso:
            continue
        ref = caso_by_num.get(caso.referencia_caso)
        if not ref:
            continue
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
        if not caso.items:
            from set_parser import ItemSet as _ItemSet
            razon = caso.razon_referencia or "REFERENCIA"
            caso.items = [_ItemSet(nombre=razon[:80], cantidad=1, precio_unitario=0)]

    # Folios ya enviados al SII (no reutilizar) — actualizar tras cada envío exitoso.
    # Fuente de verdad: sets/pudu_78392059K/certificacion_final/RESUMEN_CERTIFICACION.md
    # (última certificación real aceptada por el SII, 2026-05-18: T33 1-37, T56 1-10, T61 1-28).
    FOLIOS_YA_ENVIADOS = {
        33: set(range(1, 38)),   # 1-37 usados
        56: set(range(1, 11)),   # 1-10 usados
        61: set(range(1, 29)),   # 1-28 usados
    }

    folios_usados = {t: set(FOLIOS_YA_ENVIADOS.get(t, set())) for t in cafs}
    folios_ref = {}
    for caso in sp.casos:
        caf = cafs[caso.tipo_doc]
        folio = caf.next_folio(folios_usados[caso.tipo_doc])
        folios_usados[caso.tipo_doc].add(folio)
        folios_ref[caso.numero] = folio

    timestamp_real = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    # Periodo pre-RCV obligatorio para libros ESPECIAL de certificacion.
    # El SII rechaza con CRT-3 si se usa un periodo actual (post-2017).
    # FchDoc debe estar dentro del periodo declarado.
    LIBRO_PERIODO_TIMESTAMP = "2000-01-01T00:00:00"

    print(f"\n[3/4] Folios asignados:")
    for caso in sp.casos:
        print(f"        CASO {caso.numero}  T{caso.tipo_doc}  Folio {folios_ref[caso.numero]}")

    # Generar libro de ventas sin firma
    # Usamos timestamp con periodo 2000-01 para FchDoc y PeriodoTributario,
    # luego reemplazamos TmstFirma con la hora real.
    unsigned_xml = build_unsigned_libro_ventas(
        sp.casos, folios_ref, RECEPTOR_PRUEBA, emisor_data,
        LIBRO_PERIODO_TIMESTAMP, sp.nro_atencion_ventas,
    )
    # TmstFirma debe ser la hora real de firma, no la del periodo
    unsigned_xml = unsigned_xml.replace(
        LIBRO_PERIODO_TIMESTAMP.encode("iso-8859-1"),
        timestamp_real.encode("iso-8859-1"),
    )
    rut_clean = emisor_data["rut"].replace("-", "").replace(".", "")
    unsigned_path = os.path.join(output_dir, f"LibroVentas_{rut_clean}_UNSIGNED.xml")
    signed_path   = os.path.join(output_dir, f"LibroVentas_{rut_clean}.xml")
    with open(unsigned_path, "wb") as f:
        f.write(unsigned_xml)

    # Firmar con Node.js (xml-crypto del pudu server)
    print(f"\n[4/4] Firmando con pudu server (xml-crypto)...")
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
    print(f"  OK  LibroVentas_{rut_clean}.xml  ({size:,} bytes)")
    print(f"  Listo en: {output_dir}")
    print(f"  Nro atención SII: {sp.nro_atencion_ventas}")
    print("=" * 60)


if __name__ == "__main__":
    main()
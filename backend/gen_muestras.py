"""
Regenera los PDFs de muestras impresas para Etapa 4.

Lee los EnvioDTE de las carpetas de Set Básico y Simulación,
genera PDFs con el TED compacto (fix FRMA/FRMT) y los guarda
en output/muestras_YYYYMMDD_HHMM/.

Uso:
    cd backend
    python gen_muestras.py
"""
import os, datetime
from parser import parse_envio_dte, CEDIBLE_TIPOS
from generator import generate_pdf

OUT_BASE = r"d:\PUDU\Certificador Pudu\output"

SOURCES = [
    r"d:\PUDU\Certificador Pudu\output\certificacion_20260517_2009\EnvioDTE_78392059K.xml",
    r"d:\PUDU\Certificador Pudu\output\etapa2_20260517_2318\EnvioDTE_78392059K.xml",
]


def run():
    out_dir = os.path.join(OUT_BASE,
        datetime.datetime.now().strftime("muestras_%Y%m%d_%H%M"))
    os.makedirs(out_dir, exist_ok=True)

    total = 0
    for xml_path in SOURCES:
        with open(xml_path, "rb") as f:
            xml_bytes = f.read()
        dtes = parse_envio_dte(xml_bytes)
        for dte in dtes:
            for cedible in ([False, True] if dte.tipo in CEDIBLE_TIPOS else [False]):
                suffix = "_CEDIBLE" if cedible else ""
                name = f"DTE_T{dte.tipo}F{dte.folio}{suffix}.pdf"
                pdf = generate_pdf(dte, cedible=cedible)
                path = os.path.join(out_dir, name)
                with open(path, "wb") as f:
                    f.write(pdf)
                print(f"OK  {name}")
                total += 1

    print(f"\n{total} PDFs -> {out_dir}")


if __name__ == "__main__":
    run()

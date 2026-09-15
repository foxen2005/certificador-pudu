// Formato del DATOS.txt — espejo de DATOS_LINEAS / _parse_datos en backend/main.py.
// Las 11 líneas son obligatorias: sin NroResol/FchResol (10-11) el SII rechaza el
// envío con CRT-3-19 "Fecha/Numero Resolucion Invalido". Validar aquí evita
// gastar folios en un envío que va a ser rechazado.

export interface DatosLinea {
  n: number;
  nombre: string;
  ejemplo: string;
  nota?: string;
  opcional?: boolean;
}

export const DATOS_LINEAS: DatosLinea[] = [
  {
    n: 1,
    nombre: "Nombre del representante legal",
    ejemplo: "Juan Pérez González",
  },
  {
    n: 2,
    nombre: "RUT del representante (con guión)",
    ejemplo: "11111111-1",
    nota: "Es quien firma el envío (RutEnvia)",
  },
  {
    n: 3,
    nombre: "Razón social de la empresa",
    ejemplo: "EMPRESA TEST LTDA",
    nota: "Tal como aparece en el SII, sin abreviaturas",
  },
  {
    n: 4,
    nombre: "RUT de la empresa (con guión)",
    ejemplo: "76543210-3",
    nota: "Debe coincidir con el RUT de los CAF",
  },
  {
    n: 5,
    nombre: "Clave del certificado .pfx / .p12",
    ejemplo: "clave_pfx_aqui",
  },
  {
    n: 6,
    nombre: "Giro comercial",
    ejemplo: "VENTA AL POR MENOR DE COMPUTADORES Y EQUIPOS",
    nota: "Se imprime en los PDF; el SII pide no abreviar",
  },
  { n: 7, nombre: "Código de actividad económica (Acteco)", ejemplo: "471001" },
  {
    n: 8,
    nombre: "Dirección de origen",
    ejemplo: "Av. Providencia 1234 Of. 501",
  },
  { n: 9, nombre: "Comuna de origen", ejemplo: "Providencia" },
  {
    n: 10,
    nombre: "Número de resolución SII",
    ejemplo: "0",
    nota: "En ambiente de certificación es siempre 0 (Manual SII)",
  },
  {
    n: 11,
    nombre: "Fecha de resolución (YYYY-MM-DD)",
    ejemplo: "2026-05-05",
    nota: "La fecha publicada en los datos de tu empresa en maullin.sii.cl — NO la de hoy",
  },
  {
    n: 12,
    nombre: "Email de contacto (opcional)",
    ejemplo: "contacto@empresa.cl",
    nota: "Va como MailContacto en las respuestas de Intercambio (Etapa 3)",
    opcional: true,
  },
];

// Líneas obligatorias = todas las que no son opcionales (hoy: 11).
export const DATOS_OBLIGATORIAS = DATOS_LINEAS.filter(
  (d) => !d.opcional,
).length;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const RUT_RE = /^\d{7,8}-[\dkK]$/;
const FECHA_RE = /^\d{4}-\d{2}-\d{2}$/;

export function rutValido(rut: string): boolean {
  if (!RUT_RE.test(rut)) return false;
  const [num, dv] = rut.split("-");
  let suma = 0;
  let mul = 2;
  for (let i = num.length - 1; i >= 0; i--) {
    suma += Number(num[i]) * mul;
    mul = mul === 7 ? 2 : mul + 1;
  }
  const resto = 11 - (suma % 11);
  const esperado = resto === 11 ? "0" : resto === 10 ? "K" : String(resto);
  return dv.toUpperCase() === esperado;
}

// Date.parse("2026-02-31") NO falla en V8 (rueda a marzo); el backend sí la
// rechaza con strptime. Validar que la fecha exista de verdad.
export function fechaValida(s: string): boolean {
  if (!FECHA_RE.test(s)) return false;
  const [y, m, d] = s.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return (
    dt.getUTCFullYear() === y &&
    dt.getUTCMonth() === m - 1 &&
    dt.getUTCDate() === d
  );
}

export interface DatosValidacion {
  lineas: string[];
  errores: string[];
}

export function validarDatosTxt(texto: string): DatosValidacion {
  const lineas = texto
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  const errores: string[] = [];

  if (lineas.length < DATOS_OBLIGATORIAS) {
    const faltan = DATOS_LINEAS.slice(lineas.length, DATOS_OBLIGATORIAS).map(
      (d) => `${d.n} (${d.nombre})`,
    );
    errores.push(
      `El archivo tiene ${lineas.length} línea(s) y necesita ${DATOS_OBLIGATORIAS}. Faltan: ${faltan.join(", ")}.`,
    );
    return { lineas, errores };
  }

  if (!rutValido(lineas[1]))
    errores.push(
      `Línea 2: "${lineas[1]}" no es un RUT válido (formato 11111111-1, dígito verificador correcto).`,
    );
  if (!rutValido(lineas[3]))
    errores.push(
      `Línea 4: "${lineas[3]}" no es un RUT válido (formato 76543210-3, dígito verificador correcto).`,
    );
  if (!/^\d+$/.test(lineas[9]))
    errores.push(
      `Línea 10: "${lineas[9]}" debe ser numérico (0 en certificación).`,
    );
  if (!fechaValida(lineas[10])) {
    errores.push(
      `Línea 11: "${lineas[10]}" debe ser una fecha YYYY-MM-DD (ej. 2026-05-05).`,
    );
  }
  if (lineas[11] && !EMAIL_RE.test(lineas[11])) {
    errores.push(
      `Línea 12: "${lineas[11]}" no es un correo válido (o déjala vacía).`,
    );
  }
  return { lineas, errores };
}

// Decodifica como UTF-8 y, si el archivo viene en ANSI/ISO-8859-1 (bytes
// inválidos en UTF-8), como latin1 — igual que _decode_datos en el backend.
export function decodificarDatos(buf: ArrayBuffer): string {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(buf);
  } catch {
    return new TextDecoder("iso-8859-1").decode(buf);
  }
}

export function plantillaDatosTxt(): string {
  // Solo las obligatorias: la 12 (email) se agrega a mano si se quiere.
  return (
    DATOS_LINEAS.filter((d) => !d.opcional)
      .map((d) => d.ejemplo)
      .join("\n") + "\n"
  );
}

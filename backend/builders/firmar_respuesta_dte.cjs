/**
 * Firma un RespuestaDTE (RecepcionDTE o ResultadoDTE) — Etapa 3 Intercambio.
 * Uso: node firmar_respuesta_dte.cjs <input.xml> <output.xml> <p12_path> <p12_pass>
 *
 * Copia de verify/firmar_respuesta_dte.js usando el signer vendorizado
 * (./vendor/signer.js) en vez de d:/PUDU/SII_pudu_Server, para que funcione
 * dentro del Cloud Run de certificador-sii (solo empaqueta backend/).
 * Misma lógica de firma que aprobó el SII el 2026-05-18 (RESUMEN_CERTIFICACION).
 */
const fs = require('fs');
const { DOMParser } = require('@xmldom/xmldom');
const { signInPlace, parseCertificate } = require('./vendor/signer.js');

// signer.js hace console.log al parsear el cert — mandarlo a stderr por consistencia
// con pudu_sign.cjs (stdout queda limpio aunque aquí escribimos a archivo).
console.log = (...args) => process.stderr.write(args.join(' ') + '\n');

const [,,inputPath, outputPath, p12Path, p12Pass] = process.argv;
const NS = 'http://www.sii.cl/SiiDte';
const rawXml = fs.readFileSync(inputPath, 'latin1');
const cert   = parseCertificate(fs.readFileSync(p12Path), p12Pass);
const doc    = new DOMParser().parseFromString(rawXml, 'text/xml');
const resultado = doc.getElementsByTagNameNS(NS, 'Resultado').item(0);
const resultadoId = resultado.getAttribute('ID');
const signed = signInPlace(rawXml, resultadoId,
                            "//*[local-name()='RespuestaDTE']",
                            cert.privateKeyPem, cert.certBase64);
fs.writeFileSync(outputPath, signed, 'latin1');
process.stderr.write(`  RespuestaDTE firmado OK (ID=${resultadoId})\n`);

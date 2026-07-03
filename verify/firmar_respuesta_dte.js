/**
 * Firma un RespuestaDTE (RecepcionDTE o ResultadoDTE).
 * Uso: node firmar_respuesta_dte.js <input.xml> <output.xml> <p12_path> <p12_pass>
 */
const fs = require('fs');
const { DOMParser } = require('@xmldom/xmldom');
const { signInPlace, parseCertificate } = require('d:/PUDU/SII_pudu_Server/src/signer');

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

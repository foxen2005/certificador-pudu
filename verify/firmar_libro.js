/**
 * Firma un Libro Tributario (LibroCompraVenta) usando xml-crypto.
 * El Signature cubre el elemento EnvioLibro (no DTEs como en EnvioDTE).
 *
 * Uso: node firmar_libro.js <input_unsigned.xml> <output_signed.xml> <p12_path> <p12_pass>
 */
const fs = require('fs');
const { DOMParser, XMLSerializer } = require('@xmldom/xmldom');
const { signInPlace, parseCertificate } = require('f:/PUDU/SII_pudu_Server/src/signer');

const [,,inputPath, outputPath, p12Path, p12Pass] = process.argv;
if (!inputPath || !outputPath || !p12Path || !p12Pass) {
  console.error('Uso: node firmar_libro.js <input.xml> <output.xml> <cert.p12> <pass>');
  process.exit(1);
}

const NS_LCV = 'http://www.sii.cl/SiiDte';
const rawXml = fs.readFileSync(inputPath, 'latin1');
const cert   = parseCertificate(fs.readFileSync(p12Path), p12Pass);
const doc    = new DOMParser().parseFromString(rawXml, 'text/xml');

const envio = doc.getElementsByTagNameNS(NS_LCV, 'EnvioLibro').item(0);
const envioId = envio.getAttribute('ID');

// Firmar el EnvioLibro con signInPlace (xml-crypto)
const signed = signInPlace(rawXml, envioId,
                            "//*[local-name()='LibroCompraVenta']",
                            cert.privateKeyPem, cert.certBase64);

fs.writeFileSync(outputPath, signed, 'latin1');
process.stderr.write(`  Libro firmado OK (ID=${envioId})\n`);

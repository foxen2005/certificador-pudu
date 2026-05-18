/**
 * Firma un EnvioRecibos: primero cada DocumentoRecibo, luego el SetRecibos outer.
 * Uso: node firmar_envio_recibos.js <input.xml> <output.xml> <p12_path> <p12_pass>
 */
const fs = require('fs');
const { DOMParser, XMLSerializer } = require('@xmldom/xmldom');
const { signInPlace, parseCertificate } = require('f:/PUDU/SII_pudu_Server/src/signer');

const [,,inputPath, outputPath, p12Path, p12Pass] = process.argv;
const NS = 'http://www.sii.cl/SiiDte';
const rawXml  = fs.readFileSync(inputPath, 'latin1');
const cert    = parseCertificate(fs.readFileSync(p12Path), p12Pass);
const doc     = new DOMParser().parseFromString(rawXml, 'text/xml');
const ser     = new XMLSerializer();

const setRecibos = doc.getElementsByTagNameNS(NS, 'SetRecibos').item(0);
const setId = setRecibos.getAttribute('ID');

// 1. Firmar cada DocumentoRecibo dentro de cada Recibo
const recibos = Array.from(setRecibos.getElementsByTagNameNS(NS, 'Recibo'));
const signedParts = [];
const caratulaEl = setRecibos.getElementsByTagNameNS(NS, 'Caratula').item(0);
const caratulaXml = ser.serializeToString(caratulaEl);
const attrs = Array.from(doc.documentElement.attributes).map(a => `${a.name}="${a.value}"`).join(' ');

for (let i = 0; i < recibos.length; i++) {
  const recibo = recibos[i];
  const docEl  = recibo.getElementsByTagNameNS(NS, 'DocumentoRecibo').item(0);
  const docId  = docEl.getAttribute('ID');
  const reciboXml = ser.serializeToString(recibo);
  const signed = signInPlace(reciboXml, docId,
                              "//*[local-name()='Recibo']",
                              cert.privateKeyPem, cert.certBase64);
  signedParts.push(signed.replace(/<\?xml[^?]*\?>/,'').trim());
  process.stderr.write(`  Recibo[${i+1}] ${docId} OK\n`);
}

// 2. Reconstruir EnvioRecibos con Recibos firmados
const unsignedEnvio = `<?xml version="1.0" encoding="ISO-8859-1"?>
<EnvioRecibos ${attrs}>
<SetRecibos ID="${setId}">
${caratulaXml}
${signedParts.join('\n')}
</SetRecibos>
</EnvioRecibos>`;

// 3. Firmar el SetRecibos outer
const signedEnvio = signInPlace(unsignedEnvio, setId,
                                 "//*[local-name()='EnvioRecibos']",
                                 cert.privateKeyPem, cert.certBase64);
fs.writeFileSync(outputPath, signedEnvio, 'latin1');
process.stderr.write(`  EnvioRecibos OK → ${outputPath}\n`);

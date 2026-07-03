/**
 * Recibe un EnvioDTE sin firmas, firma cada DTE y el SetDTE con signer.js,
 * y escribe el resultado firmado.
 *
 * Uso: node firmar_envio.js <input_unsigned.xml> <output_signed.xml> <p12_path> <p12_pass>
 */
const fs  = require('fs');
const { DOMParser, XMLSerializer } = require('@xmldom/xmldom');
const { signInPlace, parseCertificate } = require('d:/PUDU/SII_pudu_Server/src/signer');

const [,,inputPath, outputPath, p12Path, p12Pass] = process.argv;
if (!inputPath || !outputPath || !p12Path || !p12Pass) {
  console.error('Uso: node firmar_envio.js <input.xml> <output.xml> <cert.p12> <pass>');
  process.exit(1);
}

const NS_SIG = 'http://www.w3.org/2000/09/xmldsig#';
const NS_DTE = 'http://www.sii.cl/SiiDte';

const rawXml = fs.readFileSync(inputPath, 'latin1');
const cert   = parseCertificate(fs.readFileSync(p12Path), p12Pass);
const doc    = new DOMParser().parseFromString(rawXml, 'text/xml');
const ser    = new XMLSerializer();

const root = doc.documentElement;
const set  = root.getElementsByTagNameNS(NS_DTE, 'SetDTE').item(0);
const setId = set.getAttribute('ID');

// 1. Firmar cada DTE
const dtes = Array.from(set.getElementsByTagNameNS(NS_DTE, 'DTE'));
const signedParts = [];

for (let i = 0; i < dtes.length; i++) {
  const dte   = dtes[i];
  const docEl = dte.getElementsByTagNameNS(NS_DTE, 'Documento').item(0);
  const docId = docEl.getAttribute('ID');
  const dteXml = ser.serializeToString(dte);
  const signed = signInPlace(dteXml, docId, "//*[local-name()='DTE']",
                              cert.privateKeyPem, cert.certBase64);
  signedParts.push(signed.replace(/<\?xml[^?]*\?>/,'').trim());
  process.stderr.write(`  DTE[${i+1}] ${docId} OK\n`);
}

// 2. Reconstruir EnvioDTE con DTEs firmados
const caratula = set.getElementsByTagNameNS(NS_DTE, 'Caratula').item(0);
const caratulaXml = ser.serializeToString(caratula);
const attrs = Array.from(root.attributes).map(a => `${a.name}="${a.value}"`).join(' ');

const unsignedEnvio = `<?xml version="1.0" encoding="ISO-8859-1"?>
<EnvioDTE ${attrs}>
<SetDTE ID="${setId}">
${caratulaXml}
${signedParts.join('\n')}
</SetDTE>
</EnvioDTE>`;

// 3. Firmar el SetDTE
const signedEnvio = signInPlace(unsignedEnvio, setId,
                                 "//*[local-name()='EnvioDTE']",
                                 cert.privateKeyPem, cert.certBase64);

fs.writeFileSync(outputPath, signedEnvio, 'latin1');
process.stderr.write(`  EnvioDTE OK → ${outputPath}\n`);

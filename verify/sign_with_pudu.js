/**
 * Toma los DTEs generados por Python (sin firma), los firma con el pudu server
 * (xml-crypto, exactamente como produccion), y genera un EnvioDTE listo para subir.
 *
 * Si este EnvioDTE pasa el SII → el contenido DTE está bien, el problema era la firma Python.
 * Si falla → el problema es el contenido del DTE.
 */
const fs   = require('fs');
const path = require('path');
const { DOMParser, XMLSerializer } = require('@xmldom/xmldom');
const { signInPlace, parseCertificate } = require('f:/PUDU/SII_pudu_Server/src/signer');

const NS_SIG = 'http://www.w3.org/2000/09/xmldsig#';
const NS_DTE = 'http://www.sii.cl/SiiDte';

const outDir = 'f:/PUDU/Certificador Pudu/output';
const last   = fs.readdirSync(outDir).filter(d => d.startsWith('certificacion_')).sort().at(-1);
const xmlPath = path.join(outDir, last, 'EnvioDTE_78392059K.xml');
const p12Path = 'f:/PUDU/Certificador Pudu/sets/pudu_78392059K/15996452-3_2025-11-14.p12';

console.log('Base:', last);
const rawXml = fs.readFileSync(xmlPath, 'latin1');
const cert   = parseCertificate(fs.readFileSync(p12Path), '2409');
const doc    = new DOMParser().parseFromString(rawXml, 'text/xml');
const ser    = new XMLSerializer();

// 1. Obtener el SetDTE con toda la Caratula (sin firmas)
const root = doc.documentElement;
const set  = root.getElementsByTagNameNS(NS_DTE, 'SetDTE').item(0);

// 2. Para cada DTE: quitar la firma Python, re-firmar con pudu server
const dtes = Array.from(set.getElementsByTagNameNS(NS_DTE, 'DTE'));
const signedDteParts = [];

for (let i = 0; i < dtes.length; i++) {
  const dte   = dtes[i];
  const docEl = dte.getElementsByTagNameNS(NS_DTE, 'Documento').item(0);
  const docId = docEl.getAttribute('ID');

  // Quitar firma Python
  const sig = dte.getElementsByTagNameNS(NS_SIG, 'Signature').item(0);
  if (sig) dte.removeChild(sig);

  // Serializar DTE sin firma
  const dteXml = ser.serializeToString(dte);

  // Firmar con pudu server (xml-crypto)
  const signedDte = signInPlace(dteXml, docId, "//*[local-name()='DTE']",
                                 cert.privateKeyPem, cert.certBase64);
  signedDteParts.push(signedDte.replace(/<\?xml[^?]*\?>/,'').trim());
  console.log(`  ✓ DTE[${i+1}] ${docId} firmado con pudu server`);
}

// 3. Reconstruir el EnvioDTE con los DTEs re-firmados
// Obtener la Caratula original
const caratula = set.getElementsByTagNameNS(NS_DTE, 'Caratula').item(0);
const caratulaXml = ser.serializeToString(caratula);
const setId = set.getAttribute('ID');

const rootAttribs = Array.from(root.attributes).map(a => `${a.name}="${a.value}"`).join(' ');

const envioSinFirma = `<?xml version="1.0" encoding="ISO-8859-1"?>
<EnvioDTE ${rootAttribs}>
<SetDTE ID="${setId}">
${caratulaXml}
${signedDteParts.join('\n')}
</SetDTE>
</EnvioDTE>`;

// 4. Firmar el SetDTE con pudu server
const envioFirmado = signInPlace(envioSinFirma, setId,
                                  "//*[local-name()='EnvioDTE']",
                                  cert.privateKeyPem, cert.certBase64);

// 5. Guardar
const outPath = path.join(outDir, last, 'EnvioDTE_PUDU_FIRMADO.xml');
fs.writeFileSync(outPath, envioFirmado, 'latin1');
console.log(`\n✓ EnvioDTE firmado con pudu server guardado en:`);
console.log(`  ${outPath}`);
console.log('\nSi este pasa el SII → contenido DTE correcto, problema era firma Python');
console.log('Si falla → problema en contenido del DTE');

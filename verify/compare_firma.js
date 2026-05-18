/**
 * Compara la firma de nuestro Python con la del pudu server (xml-crypto).
 * Toma el DTE generado, le quita la Signature, lo re-firma con signer.js,
 * y compara el DigestValue + SignatureValue para confirmar que son idénticos.
 */
const fs   = require('fs');
const path = require('path');
const { DOMParser, XMLSerializer } = require('@xmldom/xmldom');

// Importar signer.js del pudu server (usa xml-crypto + node-forge)
const { signInPlace } = require('f:/PUDU/SII_pudu_Server/src/signer');

const NS_SIG = 'http://www.w3.org/2000/09/xmldsig#';
const NS_DTE = 'http://www.sii.cl/SiiDte';

// Último output generado
const outDir = 'f:/PUDU/Certificador Pudu/output';
const last   = fs.readdirSync(outDir).filter(d => d.startsWith('certificacion_')).sort().at(-1);
const xmlPath = path.join(outDir, last, 'EnvioDTE_78392059K.xml');
const p12Path = 'f:/PUDU/Certificador Pudu/sets/pudu_78392059K/15996452-3_2025-11-14.p12';
const p12Pass = '2409';

console.log('Certificacion:', last);
console.log('XML:', path.basename(xmlPath));
console.log();

const rawXml = fs.readFileSync(xmlPath, 'latin1');
const doc    = new DOMParser().parseFromString(rawXml, 'text/xml');
const ser    = new XMLSerializer();

// Cargar certificado
const { parseCertificate } = require('f:/PUDU/SII_pudu_Server/src/signer');
const p12Buf  = fs.readFileSync(p12Path);
const cert    = parseCertificate(p12Buf, p12Pass);

const dtes = Array.from(doc.getElementsByTagNameNS(NS_DTE, 'DTE'));
let ok = 0, fail = 0;

for (let i = 0; i < dtes.length; i++) {
  const dte = dtes[i];
  const docEl = dte.getElementsByTagNameNS(NS_DTE, 'Documento').item(0);
  const docId = docEl.getAttribute('ID');

  // Extraer Signature generada por Python
  const pythonSig = dte.getElementsByTagNameNS(NS_SIG, 'Signature').item(0);
  const pythonSI  = pythonSig.getElementsByTagNameNS(NS_SIG, 'SignedInfo').item(0);
  const pythonDV  = pythonSI.getElementsByTagNameNS(NS_SIG, 'DigestValue').item(0).textContent.trim();
  const pythonSV  = pythonSig.getElementsByTagNameNS(NS_SIG, 'SignatureValue').item(0).textContent.replace(/\s/g,'');

  // Quitar la Signature del DTE para re-firmar
  dte.removeChild(pythonSig);
  const dteXml = ser.serializeToString(dte);

  // Re-firmar con signer.js del pudu server (mismo método que producción)
  let signedXml;
  try {
    signedXml = signInPlace(dteXml, docId, "//*[local-name()='DTE']", cert.privateKeyPem, cert.certBase64);
  } catch(e) {
    console.log(`  ✗ DTE[${i+1}] ${docId}: ERROR firmando - ${e.message}`);
    fail++;
    continue;
  }

  // Extraer SignedInfo del XML re-firmado
  const signedDoc  = new DOMParser().parseFromString(signedXml, 'text/xml');
  const puduSig    = signedDoc.getElementsByTagNameNS(NS_SIG, 'Signature').item(0);
  const puduSI     = puduSig.getElementsByTagNameNS(NS_SIG, 'SignedInfo').item(0);
  const puduDV     = puduSI.getElementsByTagNameNS(NS_SIG, 'DigestValue').item(0).textContent.trim();
  const puduSV     = puduSig.getElementsByTagNameNS(NS_SIG, 'SignatureValue').item(0).textContent.replace(/\s/g,'');

  const dvMatch = pythonDV === puduDV;
  const svMatch = pythonSV === puduSV;

  const icon = (dvMatch && svMatch) ? '✓' : '✗';
  console.log(`  ${icon} DTE[${i+1}] ${docId}`);
  if (!dvMatch) console.log(`    DigestValue PYTHON: ${pythonDV}`);
  if (!dvMatch) console.log(`    DigestValue PUDU:   ${puduDV}`);
  if (!svMatch && dvMatch) console.log(`    SignatureValue difiere (DV OK, SV diferente)`);
  if (dvMatch && svMatch) ok++;
  else fail++;
}

console.log();
console.log(`=== TOTAL: ${ok} idénticos  ${fail} distintos ===`);

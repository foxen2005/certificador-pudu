const fs = require('fs');
const path = require('path');
const { SignedXml } = require('xml-crypto');
const { DOMParser, XMLSerializer } = require('@xmldom/xmldom');

let xmlPath = process.argv[2];
if (!xmlPath) {
  const outDir = 'f:/PUDU/Certificador Pudu/output';
  const last = fs.readdirSync(outDir).filter(d => d.startsWith('certificacion_')).sort().at(-1);
  xmlPath = path.join(outDir, last, 'EnvioDTE_78392059K.xml');
}

console.log('Verificando:', xmlPath, '\n');
const rawXml = fs.readFileSync(xmlPath, 'latin1');
const doc = new DOMParser().parseFromString(rawXml, 'text/xml');

const NS_SIG = 'http://www.w3.org/2000/09/xmldsig#';
const NS_DTE = 'http://www.sii.cl/SiiDte';

function getCert(sigNode) {
  const el = sigNode.getElementsByTagNameNS(NS_SIG, 'X509Certificate').item(0);
  if (!el) return null;
  return `-----BEGIN CERTIFICATE-----\n${el.textContent.replace(/\s/g,'')}\n-----END CERTIFICATE-----`;
}

function verify(sigNode, label, xmlStr) {
  const pem = getCert(sigNode);
  if (!pem) { console.log(`  ? ${label}: sin certificado`); return false; }
  try {
    const sv = new SignedXml({ publicCert: pem });
    sv.loadSignature(sigNode);
    const ok = sv.checkSignature(xmlStr);
    const errs = ok ? '' : ': ' + (Array.isArray(sv.validationErrors) ? sv.validationErrors.join(' | ') : 'failed');
    console.log(`  ${ok ? '✓' : '✗'} ${label}${errs}`);
    return ok;
  } catch(e) {
    console.log(`  ✗ ${label}: ERROR ${e.message}`);
    return false;
  }
}

const dtes = Array.from(doc.getElementsByTagNameNS(NS_DTE, 'DTE'));
console.log(`[Firmas DTE — ${dtes.length} docs]`);
let ok = 0, fail = 0;
dtes.forEach((dte, i) => {
  const sig = dte.getElementsByTagNameNS(NS_SIG, 'Signature').item(0);
  if (!sig) { console.log(`  ? DTE[${i+1}]: sin firma`); return; }
  const docEl = dte.getElementsByTagNameNS(NS_DTE, 'Documento').item(0);
  const docId = docEl ? docEl.getAttribute('ID') : '?';
  const r = verify(sig, `DTE[${i+1}] ID=${docId}`, rawXml);
  r ? ok++ : fail++;
});

console.log('\n[Firma SetDTE — outer]');
const root = doc.documentElement;
const allSigs = Array.from(root.getElementsByTagNameNS(NS_SIG, 'Signature'));
const outer = allSigs.find(n => n.parentNode === root);
if (outer) {
  const r = verify(outer, 'SetDTE', rawXml);
  r ? ok++ : fail++;
}

console.log(`\n=== TOTAL: ${ok} OK  ${fail} FAIL ===`);

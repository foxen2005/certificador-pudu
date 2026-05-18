#!/usr/bin/env node
/**
 * Firma un XML invocando el signer.js del SII_pudu_Server (xml-crypto).
 *
 * Uso (vía stdin/stdout):
 *   node pudu_sign.js < input.json > signed.xml
 *
 * Input JSON (stdin):
 * {
 *   "xml":            "...unsigned XML string...",
 *   "pfx_path":       "/abs/path/to/cert.pfx",
 *   "pfx_password":   "...",
 *   "signatures": [
 *     { "ref_id": "LibreDTE_T33F17", "location_xpath": "//*[local-name()='DTE'][1]" },
 *     { "ref_id": "LibreDTE_T33F18", "location_xpath": "//*[local-name()='DTE'][2]" },
 *     ...
 *     { "ref_id": "LibreDTE_SetDoc", "location_xpath": "//*[local-name()='SetDTE']/.." }
 *   ]
 * }
 *
 * Las firmas se aplican en orden. Cada `location_xpath` indica el elemento
 * dentro del cual se hará `append` del <Signature>. El `ref_id` es el ID del
 * elemento que se referenciará (vía URI=#ref_id) y cuyo digest se firmará.
 *
 * Output: el XML firmado (stdout). Errores → stderr + exit code != 0.
 */
const fs = require('fs');
const path = require('path');

// Redirigir console.log → stderr. signer.js llama console.log al parsear el
// cert; si va a stdout contamina la salida (donde devolvemos el XML firmado).
console.log = (...args) => process.stderr.write(args.join(' ') + '\n');

const PUDU_SERVER = path.resolve(__dirname, '../../../SII_pudu_Server');

// Cargar signer.js del SII_pudu_Server (usa sus node_modules)
const { parseCertificate, signInPlace } = require(
  path.join(PUDU_SERVER, 'src/signer.js')
);

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => { data += chunk; });
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

(async () => {
  try {
    const input = JSON.parse(await readStdin());
    const { xml, pfx_path, pfx_password, signatures } = input;

    if (!xml || !pfx_path || !signatures) {
      throw new Error('Faltan parámetros (xml/pfx_path/signatures)');
    }

    const pfxBuf = fs.readFileSync(pfx_path);
    const { privateKeyPem, certBase64 } = parseCertificate(pfxBuf, pfx_password);

    // Aplicar firmas en orden
    let signed = xml;
    for (const sig of signatures) {
      signed = signInPlace(
        signed,
        sig.ref_id,
        sig.location_xpath,
        privateKeyPem,
        certBase64
      );
    }

    process.stdout.write(signed);
  } catch (err) {
    process.stderr.write(`pudu_sign error: ${err.message}\n${err.stack || ''}`);
    process.exit(1);
  }
})();

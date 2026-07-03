/**
 * Copia vendorizada de SII_pudu_Server/src/signer.js — NO es una referencia en vivo.
 * Certificador Pudu no debe depender de SII_pudu_Server en tiempo de ejecución
 * (ni en el Cloud Run de certificador-sii, que solo empaqueta esta carpeta backend/,
 * ni en general, para no acoplar el certificador al servidor de producción de DTEs).
 *
 * Si SII_pudu_Server corrige un bug de firma, hay que replicarlo aquí a mano.
 */
const forge = require('node-forge');
const crypto = require('crypto');
const { SignedXml } = require('xml-crypto');

// Parsear certificado .p12/.pfx
function parseCertificate(p12Buffer, password) {
  const p12Asn1 = forge.asn1.fromDer(forge.util.createBuffer(p12Buffer));
  const p12 = forge.pkcs12.pkcs12FromAsn1(p12Asn1, false, password);

  let privateKey = null;
  const certificates = [];

  for (const safeContent of p12.safeContents) {
    for (const safeBag of safeContent.safeBags) {
      if (safeBag.type === forge.pki.oids.pkcs8ShroudedKeyBag || safeBag.type === forge.pki.oids.keyBag) {
        privateKey = safeBag.key;
      } else if (safeBag.type === forge.pki.oids.certBag) {
        if (safeBag.cert) {
          certificates.push(safeBag.cert);
        }
      }
    }
  }

  if (!privateKey) {
    throw new Error('No se encontró la clave privada en el certificado');
  }
  if (certificates.length === 0) {
    throw new Error('No se encontró el certificado en el archivo .p12/.pfx');
  }

  // Seleccionar el certificado del usuario (leaf cert), no el CA
  // Prioridad: 1) cert que NO sea CA y tenga serialNumber (RUT)
  //            2) cert que NO sea CA
  //            3) el primer cert que tenga clave privada asociada
  let certificate = null;

  // Buscar cert que no sea CA y tenga RUT en serialNumber
  for (const cert of certificates) {
    const isCA = cert.extensions?.find(e => e.name === 'basicConstraints')?.cA;
    const hasRut = cert.subject.attributes.some(a =>
      (a.shortName === 'serialNumber' || a.name === 'serialNumber') && a.value
    );
    if (!isCA && hasRut) {
      certificate = cert;
      break;
    }
  }

  // Si no encontró, buscar cert que no sea CA
  if (!certificate) {
    for (const cert of certificates) {
      const isCA = cert.extensions?.find(e => e.name === 'basicConstraints')?.cA;
      if (!isCA) {
        certificate = cert;
        break;
      }
    }
  }

  // Si no encontró, buscar cert cuya clave pública coincida con la privada
  if (!certificate) {
    const pubKeyFromPriv = forge.pki.setRsaPublicKey(privateKey.n, privateKey.e);
    const pubPem = forge.pki.publicKeyToPem(pubKeyFromPriv);
    for (const cert of certificates) {
      const certPubPem = forge.pki.publicKeyToPem(cert.publicKey);
      if (certPubPem === pubPem) {
        certificate = cert;
        break;
      }
    }
  }

  // Último recurso: primer certificado
  if (!certificate) {
    certificate = certificates[0];
  }

  console.log('  [parseCert] Total certs en .p12:', certificates.length);
  console.log('  [parseCert] Cert seleccionado CN:', certificate.subject.getField('CN')?.value);
  console.log('  [parseCert] Cert issuer CN:', certificate.issuer.getField('CN')?.value);

  // Convertir a PEM
  const privateKeyPem = forge.pki.privateKeyToPem(privateKey);
  const certPem = forge.pki.certificateToPem(certificate);

  // Obtener datos del certificado
  const subject = certificate.subject;
  let rut = '';
  let nombre = '';
  for (const attr of subject.attributes) {
    if (attr.shortName === 'serialNumber' || attr.name === 'serialNumber') {
      rut = attr.value;
    }
    if (attr.shortName === 'CN' || attr.name === 'commonName') {
      nombre = attr.value;
    }
  }
  // Certs chilenos a veces ponen el RUT con prefijo "CL-" o embebido en el CN
  if (rut && rut.startsWith('CL-')) rut = rut.slice(3);
  if (!rut && nombre) {
    const m = nombre.match(/\d{7,8}-[\dkK]/);
    if (m) rut = m[0];
  }

  // Obtener el certificado X509 en base64 (sin headers PEM)
  const certBase64 = certPem
    .replace('-----BEGIN CERTIFICATE-----', '')
    .replace('-----END CERTIFICATE-----', '')
    .replace(/\r?\n/g, '');

  return {
    privateKeyPem,
    certPem,
    certBase64,
    rut,
    nombre,
    privateKeyForge: privateKey,
    certificateForge: certificate
  };
}

// Firmar el <DD> del TED con la clave privada del CAF (SHA1withRSA)
// Según instructivo SII: se eliminan espacios/tabs/newlines entre tags antes de firmar
function signTED(ddXml, cafPrivateKeyPem) {
  // Limpiar DD: eliminar whitespace entre tags (instructivo SII A.2.4)
  const cleanedDD = ddXml.replace(/>\s+</g, '><');

  // Limpiar la clave privada del CAF
  let keyPem = cafPrivateKeyPem.trim();
  if (!keyPem.includes('-----BEGIN RSA PRIVATE KEY-----')) {
    keyPem = '-----BEGIN RSA PRIVATE KEY-----\n' + keyPem + '\n-----END RSA PRIVATE KEY-----';
  }

  const sign = crypto.createSign('SHA1');
  // Encode as latin1 bytes — the CAF's RS field may contain accented chars (e.g. "REPOSTERÍA").
  // crypto.createSign.update(string) defaults to UTF-8, which encodes Í as [0xC3,0x8D].
  // The SII receives and verifies the XML as latin1, where Í is [0xCD].
  // Passing a latin1 Buffer ensures both sides hash identical bytes.
  sign.update(Buffer.from(cleanedDD, 'latin1'));
  sign.end();

  const signature = sign.sign(keyPem, 'base64');
  return signature;
}

// Construir el TED completo
function buildTED(ddXmlTemplate, cafXml, cafPrivateKeyPem) {
  // Insertar el CAF real dentro del DD (reemplazar placeholder)
  const ddXml = ddXmlTemplate.replace('<CAF_PLACEHOLDER/>', cafXml);

  // Firmar el DD
  const frmt = signTED(ddXml, cafPrivateKeyPem);

  const ted = '<TED version="1.0">' +
    ddXml +
    '<FRMT algoritmo="SHA1withRSA">' + frmt + '</FRMT>' +
    '</TED>';

  return ted;
}

// Extraer Modulus y Exponent de la clave privada para KeyValue
function getRsaKeyValueXml(privateKeyPem) {
  const privateKey = forge.pki.privateKeyFromPem(privateKeyPem);
  // Convertir BigInteger a hex, luego a Buffer (sin leading zero de two's complement)
  let modHex = privateKey.n.toString(16);
  if (modHex.length % 2 !== 0) modHex = '0' + modHex;
  const modulusB64 = Buffer.from(modHex, 'hex').toString('base64');

  let expHex = privateKey.e.toString(16);
  if (expHex.length % 2 !== 0) expHex = '0' + expHex;
  const exponentB64 = Buffer.from(expHex, 'hex').toString('base64');

  return '<KeyValue><RSAKeyValue>' +
    '<Modulus>' + modulusB64 + '</Modulus>' +
    '<Exponent>' + exponentB64 + '</Exponent>' +
    '</RSAKeyValue></KeyValue>';
}

function buildKeyInfoXml(privateKeyPem, certBase64) {
  return getRsaKeyValueXml(privateKeyPem) +
    '<X509Data><X509Certificate>' + certBase64 + '</X509Certificate></X509Data>';
}

// Firma XML con xml-crypto (usado para Documento y SetDTE)
function signInPlace(xml, referenceId, locationXpath, privateKeyPem, certBase64) {
  const sig = new SignedXml();
  sig.signingKey = privateKeyPem;
  sig.signatureAlgorithm = 'http://www.w3.org/2000/09/xmldsig#rsa-sha1';
  sig.canonicalizationAlgorithm = 'http://www.w3.org/TR/2001/REC-xml-c14n-20010315';

  sig.addReference(
    "//*[@ID='" + referenceId + "']",
    ['http://www.w3.org/TR/2001/REC-xml-c14n-20010315'],
    'http://www.w3.org/2000/09/xmldsig#sha1'
  );

  const keyInfoContent = buildKeyInfoXml(privateKeyPem, certBase64);
  sig.keyInfoProvider = {
    getKeyInfo: function() {
      return keyInfoContent;
    }
  };

  sig.computeSignature(xml, {
    location: { reference: locationXpath, action: 'append' }
  });

  return sig.getSignedXml();
}

module.exports = {
  parseCertificate,
  signTED,
  buildTED,
  signInPlace
};

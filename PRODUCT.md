# Product

## Register

product

## Users

Contadores, desarrolladores y proveedores de software externos (no solo PUDU) que necesitan
certificar a una empresa como emisor de DTE ante el SII de Chile. Llegan con los archivos que
entrega el SII (certificado .pfx, set de pruebas .txt, CAF .xml) y su objetivo es salir con los
XML firmados y los PDF listos para subir al portal de certificación (maullin.sii.cl), sin
conocer el detalle del formato XML ni de las reglas de firma. Se usa en escritorio, con el
portal del SII abierto en otra pestaña.

## Product Purpose

Wizard paso a paso que genera todo lo que pide la certificación SII: Set Básico (EnvioDTE +
Libros), Simulación, Intercambio (3 XML de respuesta) y Muestras Impresas (PDF con PDF417),
más módulos adicionales por tipo de documento (Exportación, Factura de Compra, Guías, Exenta).
Éxito = cada envío al SII sale aceptado sin reparos a la primera, y cuando el SII rechaza
algo, la web ya le dijo al usuario por qué antes de gastar folios.

## Brand Personality

Técnica, sobria, confiable. Voz de consola de operaciones: cada texto es una instrucción o
un dato verificable (código de error del SII, folio, N° de atención), nunca relleno. Explica
lo justo para que un usuario sin contexto no se equivoque, en español chileno técnico.

## Anti-references

- Landing/SaaS: héroes, métricas grandes, tarjetas idénticas con icono + título + texto.
- Wizards "amigables" que esconden los códigos reales del SII detrás de mensajes vagos.
- Cualquier dato de ejemplo hardcodeado de un cliente (folios de PUDU, RUT de prueba)
  presentado como si fuera genérico.

## Design Principles

1. **El código de error del SII es la interfaz**: cada validación previa y cada mensaje de
   error nombra el código del SII que evita o explica (CRT-3-19, DTE-3-100, LRH…).
2. **Prevenir antes que enviar**: validar DATOS.txt, CAF, folios y XSD en la web; un folio
   quemado no se recupera.
3. **Una corrida, un ZIP**: XML, libros y PDF deben salir de la misma descarga; la UI lo
   recuerda donde importa.
4. **Densidad de operaciones, no de marketing**: formularios compactos, tablas, badges de
   estado; el morado PUDU solo como acento.
5. **Separación por set**: cada certificación adicional (exportación, guías…) es un módulo
   aparte que no puede romper el set básico ya probado.

## Accessibility & Inclusion

Escritorio primero (≥1024 px), sin requisito móvil. Contraste de texto ≥4.5:1, foco visible
en inputs y botones, estados de error con icono + texto (no solo color).

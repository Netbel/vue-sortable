# Contexto de vue-sortable para PR-Agent

Este repositorio público contiene un plugin JavaScript para Vue 1 que registra
la directiva `v-sortable` como wrapper de SortableJS. El manifiesto declara
Vue `^1.0.26`, SortableJS `^1.4.2`, Babel 6 y Webpack 1.

## Superficie pública y compatibilidad

- `vue-sortable.js` exporta el plugin y su método `install` para `Vue.use`.
  Contempla CommonJS, AMD y carga mediante globals del navegador.
- La directiva recibe opciones y puede exponer una instancia con el argumento
  de la directiva bajo `vm.sortable`. Conservar el contrato documentado.
- Revisar registro de la directiva, opciones, referencias a instancias y manejo
  de identificadores duplicados cuando el diff modifique esos flujos.
- No asumir APIs de Vue 2/3 ni una versión moderna de SortableJS: cualquier
  sugerencia debe ser compatible con el código y versiones declarados.
- `demo/*.vue`, README e `index.html` muestran la API del plugin. Comprobar
  coherencia entre ejemplos y comportamiento modificado.

## Pruebas y revisión

- `test/Sortable.spec.js` usa Jasmine; Karma con PhantomJS ejecuta `npm test`.
  Los tests cubren instalación, directiva, argumentos y opciones.
- Evaluar regresiones de inicialización y contratos observables, sin afirmar
  haber ejecutado ese entorno legacy desde la revisión automática.
- `demo/dist/` contiene bundles generados y se excluye del análisis.
- Evitar migraciones generales de framework, modernizaciones masivas y cambios
  cosméticos ajenos al problema concreto de la PR.
- No agregar contexto de otros proyectos: el análisis se limita a este plugin
  público y a evidencia disponible en sus archivos.

Fuentes: package.json, README, vue-sortable.js y test/Sortable.spec.js.
Escribir en español: evidencia, escenario, impacto y corrección acotada.

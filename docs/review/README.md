# Revisión automática con PR-Agent

El workflow `PR Agent` analiza PRs dirigidas a `Netbel/vue-sortable` al crearse,
reabrirse, recibir commits, editarse o pasar de draft a listas para revisión.
Las PRs draft se omiten. Volver a draft cancela la ejecución anterior mediante
la concurrencia del workflow. El runner vuelve a consultar el estado y SHA antes
de cada herramienta para omitir eventos viejos o PRs que ya no son revisables.

Ejecuta `review` e `improve`: resumen de riesgo, seguridad y pruebas, más sugerencias
concretas de alto valor. Los comentarios son persistentes y en español. No aprueba
ni fusiona PRs. Incluye PRs desde forks: solo lee su diff por API, sin ejecutar
código de la PR.

## Activación

1. Integrar estos archivos en `master`, rama predeterminada del repositorio.
2. En **Settings → Secrets and variables → Actions**, crear el secreto
   `GEMINI_API_KEY` con una API key de Google AI Studio.
3. Por defecto está habilitado con `gemini/gemini-3.5-flash-lite`, como modelo inicial de esta integración.
   Se puede cambiar con la variable `PR_AGENT_MODEL=gemini/<modelo>`.
   Establecer `PR_AGENT_ENABLED=false` para desactivar revisiones automáticas.

`GITHUB_TOKEN` lo proporciona GitHub. No copiar claves al código, a `.env`, a los
logs o a una PR. Si falta la API key, el job falla con un diagnóstico explícito.
El runner conserva soporte alternativo para `zai/<modelo>` y `ZAI_API_KEY`, pero
no hay fallback entre proveedores: el proveedor activo lo determina el modelo.

Para comprobarlo después de integrar y configurar el secreto: **Actions → PR Agent
→ Run workflow**, rama `master`, número de PR abierta y no draft.
`publish=false` genera reportes sin publicar comentarios; `true` publica.
Crear o actualizar una PR no draft dispara la revisión automáticamente.

## Configuración y seguridad

- `.pr_agent.toml`: idioma, criterios, exclusiones y límites.
- `project-context.md`: contexto verificado de vue-sortable y sus criterios de revisión.
- `.github/pr-agent/`: runner y adaptador de la integración con pruebas sin credenciales.
- El checkout obtiene únicamente configuración y scripts de `master`, nunca
  código de la PR. No se cargan instrucciones/configuración desde su rama.
- PR-Agent 0.47.0 está fijado por digest; las Actions, por SHA. El contenedor
  recibe solo los archivos confiables y las credenciales necesarias.
- El diff se envía a Gemini para analizarse. Las exclusiones reducen ruido y
  omiten rutas sensibles conocidas, pero no son un detector general de secretos.
- Una ejecución por PR: los eventos nuevos cancelan la anterior. Timeout de 30
  minutos por job y 12 por herramienta; hasta 3 chunks por herramienta, contexto
  máximo de 32 000 tokens y salida de 4096. No es un tope monetario estricto.
- Reportes de ejecución en Actions durante 7 días. Los hallazgos requieren
  revisión humana y complementan tests y análisis estático.

## Validación local sin credenciales

```sh
python -B -m unittest discover -s .github/pr-agent/tests -v
actionlint .github/workflows/pr-agent.yml .github/workflows/pr-agent-tests.yml
```

El workflow `PR Agent tests` valida el runner con dobles de API y contenedor, sin
secretos ni llamadas al LLM. Puede correr en una PR draft porque solo comprueba
la integración; el workflow de revisión con Gemini sigue excluyendo drafts.

Referencias: [integración oficial de PR-Agent](https://docs.pr-agent.ai/installation/github/)
y [eventos de GitHub Actions](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request_target).

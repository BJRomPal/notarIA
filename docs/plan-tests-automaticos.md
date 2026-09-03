# Tests automáticos de NotarIA

Versión resumida de `docs/plan-tests-automaticos.html`. Decide cómo se mide lo que el chat
recupera y lo que el chat contesta, y dónde entran Ragas y LangSmith.

---

## 1. Punto de partida

No hay ningún test automático: ni `pytest`, ni `conftest.py`, ni un solo `assert` en el repo.

Lo que existe son dos scripts de generación batch, `tests/lmjudge_dinamico.py` y
`tests/lmjudgeLS.py`. **No tienen juez** —el `LS` es «Ley de Sociedades»—, ni ground truth, ni
métricas: corren 30 preguntas cableadas contra una copia del pipeline y vuelcan la respuesta a un
`.txt` para leerla a ojo.

| | |
|---|---|
| Tests automáticos | 0 |
| Preguntas de referencia | 30, cableadas, sin respuesta ni artículos esperados |
| Última corrida | 5 de junio de 2026 |

Después de esa fecha entraron el CCyCN completo, el Código Penal, el Código Fiscal CABA, las DTR
y las IT. **Las respuestas guardadas describen un corpus que ya no existe, y no hay forma de
darse cuenta salvo leyéndolas una por una.**

---

## 2. Qué hay que medir: son dos fallas distintas

El pipeline tiene siete fases y se rompe en dos lugares que no se diagnostican igual.

- **Recuperación (fases 1 a 6)** — análisis, vectorial, remisiones, gate de suficiencia, Cypher
  condicional, remisiones. Produce `ctx.ids` y `ctx.textos`.
  Se mide: *¿está entre esos IDs el artículo que la pregunta necesitaba?*
- **Generación (fase 7)** — `answer_chain` con `gemini-2.5-flash` sobre ese contexto.
  Se mide: *¿dice solo lo que dicen esos artículos, y los cita como corresponde?*

La primera falla envenena a la segunda: **si el artículo nunca entró al contexto, ningún juez de
generación lo va a decir.** Va a decir que la respuesta es fiel al contexto que recibió, y va a
tener razón.

---

## 3. El bloqueo: el contexto no sale del pipeline

`api/pipeline.py` expone una sola función pública, `responder_stream()`.

| | |
|---|---|
| **Sí sale** | El evento `fuentes`: `id`, `numero` y `norma` por artículo. Alcanza para medir recuperación por ID. |
| **No sale** | `ContextoAcumulado` (`api/pipeline.py:131-152`): `ctx.ids` y `ctx.textos` son locales al generador. Sin el texto no hay fidelidad ni precisión del contexto. |

`tests/testRagDinamicoV3.py` tiene un `responder()`, pero devuelve solo el string final y **ya
divergió de producción** (citas canónicas, stopwords ampliadas, esquema Cypher multi-rama):
evaluar contra V3 mide algo que no es lo que se sirve.

---

## 4. Fase 0 — la costura

Es el paso cero y no depende de qué herramienta se elija después.

- `recuperar_contexto(pregunta)` — concentra las fases 1 a 6 y devuelve el `ContextoAcumulado`
  entero: IDs, textos y de qué fase vino cada artículo. `responder_stream()` pasa a consumirla,
  así producción y evaluación miden **el mismo código**. Además habilita correr solo recuperación,
  sin redactar: la capa determinista no gasta un token.
- `responder(pregunta)` — envoltorio sin streaming que devuelve la respuesta, los IDs, los textos
  y los tiempos por fase. Es la firma única que consumen `pytest`, Ragas y LangSmith por igual.

Se toca un solo archivo: `api/pipeline.py`. `tests/RagDinamicoOriginal.py` y V3 quedan intactos.

**Verificación:** `responder()` tiene que devolver exactamente los mismos IDs que hoy emite el
evento `fuentes`. Si difieren, la refactorización cambió el comportamiento.

---

## 5. El golden set

Archivo versionado en el repo, `evals/golden/*.jsonl`, un objeto por línea:

| Campo | Qué es |
|---|---|
| `pregunta` | La consulta tal como la escribiría un escribano |
| `articulos_esperados` | IDs canónicos del grafo (`Art_77_Ley_19550`). Ground truth objetivo y barato |
| `respuesta_referencia` | La respuesta modelo. El campo caro, y el único que habilita medir corrección |
| `rama` / `tipo` | Para cortar resultados por dominio y por forma de pregunta |

Cobertura actual:

| Rama | Preguntas hoy |
|---|---|
| Societario e IGJ | 30 |
| Civil (CCyCN) | 0 |
| Registral y notarial | 0 |
| Penal | 0 |
| Fiscal CABA | 0 |

Las 30 existentes sirven de semilla, pero hay que completarlas con los dos campos de referencia.
**Son 100% societario: el corpus creció a cinco ramas y la evaluación se quedó en una.**
Objetivo: ~65 preguntas.

> El golden set es el único activo irremplazable de todo el esquema. Ragas y LangSmith se cambian
> en una tarde; sesenta y cinco preguntas con su respuesta modelo escritas por un escribano, no.

---

## 6. Capa 1 — recuperación, sin un solo modelo

En derecho la unidad de verdad es el ID del artículo, no el fragmento de texto. Eso convierte la
métrica en una operación de conjuntos: exacta, gratis y reproducible.

| Métrica | Qué contesta | Qué regresión ataja |
|---|---|---|
| Recall | ¿Entró el artículo que hacía falta? | Una reingesta que cambió los IDs |
| Precisión | ¿Cuánto de lo traído sobraba? | Ruido que le tapa la señal al redactor |
| Rango | ¿En qué puesto apareció el primer acierto? | Degradación silenciosa del embedding |
| Atribución por fase | ¿Lo trajo el vector, la remisión o el Cypher? | Una fase que dejó de aportar |
| Disparo del gate | ¿Con qué frecuencia se va al grafo? | Un cambio de prompt que apagó el Cypher |

**Ninguna herramienta del mercado da la atribución por fase**: todas asumen un recuperador de un
solo paso. Acá el contexto lo arman seis fases, y saber cuál dejó de aportar es la mitad del
diagnóstico. Son media docena de líneas escritas a mano.

---

## 7. Capa 2 — generación verificable sin juez

Tres chequeos de coste cero:

1. **Cita fantasma** — todo artículo citado en la respuesta tiene que estar entre los IDs
   recuperados. Se extrae la cita del texto y se compara contra `ctx.ids`.
2. **Nombre canónico** — la norma se cita como la arma `NOMBRE_NORMA` (`api/pipeline.py:57-74`):
   «Ley 19.550», «CCyCN», «DTR 6/2019». Nunca por `titulo`, que 100 normas no tienen.
3. **Vigencia transcripta** — si el artículo recuperado tiene `modificado=True`, la respuesta trae
   la `nota_vigencia` tal cual, no una inferida del cuerpo del texto.

La cita fantasma es el error de mayor consecuencia jurídica: la respuesta suena correcta y parece
verificable, hasta que alguien va a buscar el artículo. El commit `89d3508` ya arregló una vez la
cita por el nombre canónico; sin un test que lo fije, vuelve en el próximo cambio de prompt.

**Es el mejor retorno de todo el plan.**

---

## 8. Capa 3 — lo que sí exige un juez

Fidelidad, corrección contra la referencia y relevancia solo las puede juzgar un modelo. Tres
reparos:

- **Cuesta**: la fidelidad descompone la respuesta en afirmaciones y verifica cada una. Varias
  llamadas por pregunta y por métrica.
- **Oscila**: el mismo par pregunta-respuesta puede dar 0,78 y 0,91 en dos corridas.
- **El pipeline tampoco es determinista**: el gate de suficiencia (`_evaluar_suficiencia`,
  `api/pipeline.py:469`) decide si se va al grafo, así que dos corridas de la misma pregunta
  pueden recuperar distinto.

De ahí la regla: **las capas 1 y 2 pueden frenar un commit; la 3 no.** El juez sirve para leer la
tendencia entre corridas, no para poner un umbral duro sobre una sola.

---

## 9. Ragas

Biblioteca de métricas. No corre nada ni guarda nada: recibe pregunta, contexto, respuesta y
referencia, y devuelve números.

**A favor**

- Ya trae escritos los prompts de juez: fidelidad, precisión y exhaustividad del contexto,
  relevancia, corrección factual.
- Tiene variantes con y sin referencia. Con el golden set completo quedan habilitadas también las
  que comparan contra la respuesta modelo.
- Habla Gemini de fábrica (proveedor `google`, adaptador LiteLLM) y la `GOOGLE_API_KEY` ya está
  en el `.env`.
- Genera preguntas de prueba desde el corpus: útil para poblar las cuatro ramas en cero.

**En contra**

- La v0.4 rompió la API de la v0.3 y casi todo lo que se encuentra buscando sigue siendo v0.3.
- Arrastra `pandas` y `datasets` sobre un entorno de diez paquetes, y apunta al LangChain clásico
  mientras el proyecto ya corre `langchain 1.3.1` / `langchain-core 1.4.0`.
- Sus métricas son genéricas: no saben de cita canónica, de `nota_vigencia` ni de artículo
  derogado. Eso hay que escribirlo igual.
- Para medir recuperación le pide a un modelo que juzgue si un fragmento es relevante, cuando ver
  si el ID está en la lista lo contesta exacto, gratis y siempre igual.

**Ragas está bien para la capa 3 y sobra para la capa 1.**

### El cambio de API que decide

| Qué | v0.3 (lo que se encuentra buscando) | v0.4 (lo que hay que usar) |
|---|---|---|
| Evaluación | `evaluate(dataset, metrics, llm)` | decorador `@experiment`; `evaluate()` deprecado |
| Importación | `from ragas.metrics import …` | `from ragas.metrics.collections import …` |
| Puntaje | `single_turn_ascore(sample)` → float | `ascore(**kwargs)` → `MetricResult` con `.value` y `.reason` |
| Modelo juez | `LangchainLLMWrapper(...)`, deprecado | `llm_factory(...)`; `instructor_llm_factory` eliminado |
| Referencia | `ground_truths`, una lista | `reference`, un string |
| Métrica propia | heredar de `MetricWithLLM` | heredar de `BaseMetric` o `@discrete_metric` |

Consecuencias: **pinear la versión exacta y leer los docs de esa versión, no el primer resultado
de búsqueda**; y declararla en un archivo de dependencias aparte, porque el entorno que sirve la
API no tiene por qué cargar con pandas.

---

## 10. LangSmith

No es una biblioteca de métricas: es el registro.

**A favor**

- **Ya está instalado**: `langsmith 0.8.5` entró como dependencia de `langchain-core`, sin
  declarar en `requirements.txt` y sin usar en una sola línea.
- El pipeline es LCEL entero: dos variables de entorno dan trazas con entradas, salidas, latencia
  y tokens sin tocar código.
- Datasets y experimentos versionados: es lo que faltó cuando el corpus cambió y los resultados de
  junio quedaron huérfanos.
- Se monta sobre `pytest` con un decorador (`@pytest.mark.langsmith`, requiere `langsmith>=0.3.4`)
  y cachea las llamadas HTTP: repetir una corrida sale casi gratis.
- Colas de anotación: el ground truth lo pone un escribano, y esa es la herramienta para ponerlo
  sobre consultas reales.

**En contra**

- Es un servicio ajeno: las preguntas de los clientes y el texto de los artículos salen a los
  servidores de LangChain.
- Autohospedarlo es un agregado del plan Enterprise (licencia, Kubernetes, 16 vCPU y 64 GB):
  **no es opción en la GX10**.
- No trae ni una métrica. Es el arnés y el archivo; el puntaje lo ponés vos o lo pone Ragas.
- El set de referencia no puede vivir solo ahí: el archivo del repo manda y LangSmith lo espeja.

### La cuenta, con producción traceada

| | |
|---|---|
| Capa gratuita | 5.000 trazas/mes, 1 asiento, 14 días de retención |
| Plan Plus | US$ 39 por asiento/mes, 10.000 trazas incluidas |
| Excedente | US$ 0,50 cada 1.000 trazas |

Una consulta del chat no es una traza: es la raíz más una anidada por cada llamada al modelo —
entre cuatro y siete con el gate y el Cypher. Una corrida del golden set (65 preguntas) son del
orden de 400 trazas: trece corridas y se agotó el mes. Y eso **sin contar producción**, donde el
volumen no lo decide el equipo.

Recomendación: arrancar con la capa gratuita para la evaluación sola y encender producción cuando
el harness ya esté probado.

---

## 11. No compiten: se componen

| Capa | Herramienta | Naturaleza |
|---|---|---|
| 1 · recuperación por ID | `pytest` | determinista, segundos, frena el commit |
| 2 · citas y vigencia | `pytest` | determinista, milisegundos, frena el commit |
| 3 · juez sobre la respuesta | Ragas + Gemini | ruidosa, minutos y pesos, marca tendencia |
| Registro transversal | LangSmith | traza, versiona, compara; no puntúa nada |

Los puntajes de Ragas se cargan como feedback de LangSmith: uno pone el número, el otro lo guarda
y lo compara con la corrida anterior.

### Dimensión por dimensión

| | pytest a mano | Ragas | LangSmith | Langfuse |
|---|---|---|---|---|
| Mide la recuperación | exacta, por ID | con modelo, sobre texto | no | no |
| Mide la generación | solo lo verificable | métricas ya escritas | no | básico |
| Guarda y compara | un `.txt` | no guarda | experimentos versionados | experimentos versionados |
| Coste por corrida | cero | llamadas a Gemini | trazas del plan | cero si es propio |
| Datos fuera de casa | no | no | sí, servicio ajeno | no, si se autohospeda |
| Trabajo para arrancar | escribir las métricas | pinear versión, entorno aparte | dos variables de entorno | levantar el servicio |

---

## 12. Alternativas descartadas

- **Langfuse** — *en reserva.* Núcleo abierto y autohospedable; en registro hace casi lo mismo que
  LangSmith con menos integración nativa con LangChain. Es la salida si algún día las consultas de
  los clientes no pueden salir de la máquina.
- **DeepEval** — *duplica.* Cubre lo mismo que `pytest` más Ragas juntos y agrega un vocabulario
  propio.
- **promptfoo** — *otro problema.* La unidad que evalúa es la llamada al modelo, no el recorrido de
  seis fases.
- **No hacer nada, seguir con `lmjudge_*`** — no es una base: sin juez, sin métricas, con el
  pipeline duplicado y ya divergido. Lo único aprovechable son las 30 preguntas.

---

## 13. Plan por fases

| Fase | Qué deja andando | Cómo se verifica | Qué suma al entorno |
|---|---|---|---|
| **0 · La costura** | `recuperar_contexto()` y `responder()` en `api/pipeline.py`, y el golden set con las 30 semillas completadas | `responder()` devuelve los mismos IDs que hoy emite el evento `fuentes` | nada |
| **1 · Determinista** | Recuperación por ID y los tres chequeos de cita y vigencia, como tests que frenan el commit | El set completo corre en menos de un minuto y sin gastar un token | `pytest` |
| **2 · Registro** | Trazas encendidas, dataset espejado desde el repo, cada corrida guardada como experimento | Dos corridas seguidas aparecen comparables sobre el mismo dataset | ya instalado |
| **3 · Juez** | Cuatro métricas de Ragas con Gemini, cargadas como feedback de LangSmith | Tres corridas de la misma pregunta caen en una banda conocida; si no, el umbral es ruido | entorno aparte |

El orden no es por dificultad sino por relación entre lo que cuesta y el error que ataja. **Las
fases 0 y 1 no dependen de ninguna decisión de herramienta y cubren las dos fallas más caras: el
artículo que nunca entró al contexto y la cita que el modelo inventó.**

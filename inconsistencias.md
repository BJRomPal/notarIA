# Inconsistencias del grafo

Registro de huecos de vinculación **artículo → entidad de ontología** detectados después de
la ingesta. Su propósito es doble:

1. Anotar qué artículos quedaron mal o incompletamente vinculados, para corregirlos.
2. **Anotar qué entidades quedaron con el `resumen` mal cargado** — el resumen se genera a
   partir de los artículos conectados a la entidad, así que si faltaban artículos al momento
   de generarlo, el texto quedó incompleto y hay que **regenerarlo con `qwen3.8:latest`**
   (ver la sección final).

La auditoría que produjo estos hallazgos se corrió con `auditar_cobertura_entidades.py`, que
se eliminó en la limpieza de `exploration/`. Es recuperable con
`git checkout 439fcc2 -- exploration/auditar_cobertura_entidades.py`, y su consulta central
está transcripta en la sección 2.

---

## 1. Corregido — Decreto 2080/80, Capítulo IX "Del Tracto"

**Fecha: 2026-08-31.**

Los cuatro artículos del Capítulo IX regulan el tracto abreviado, pero solo dos estaban
vinculados a `TractoSucesivo`:

| Artículo | Antes | Ahora |
|---|---|---|
| Art. 34 | `REGULA` → TractoSucesivo | sin cambios |
| Art. 35 | `MENCIONA` → TractoSucesivo | sin cambios |
| Art. 36 | solo `Dominio`, `AsientoRegistral` | **+ `REGULA` → TractoSucesivo** |
| Art. 37 | solo `DerechoRealSobreInmueble` | **+ `REGULA` → TractoSucesivo** |

El Art. 36 define las "instrumentaciones simultáneas" del art. 16 inc. d) de la Ley 17.801 y
el Art. 37 abre literalmente con "En el caso previsto por el artículo anterior": son parte
del mismo instituto. El hueco era de extracción, no de diseño — la etiqueta existía en la
ontología cerrada y el LLM eligió otras entidades (también correctas) sin agregar esta.

Consecuencia práctica que lo hizo visible: una consulta sobre tracto abreviado que llegaba
por la entidad recuperaba los Arts. 34 y 35 y no el 36 ni el 37.

> **`TractoSucesivo` necesita que se regenere su resumen**: se generó con 14 artículos y
> ahora tiene 16.

---

## 2. Método de la auditoría y su precisión

La heurística: dentro de un mismo `(:Norma, ubicacion)` con ≥ 2 artículos, si una entidad
cubre a la mayoría de los artículos pero no a todos, los no cubiertos son candidatos.

```cypher
MATCH (n:Norma)-[:CONTIENE]->(a:Articulo)
WHERE a.vigente = true AND a.ubicacion IS NOT NULL
WITH n, a.ubicacion AS ubi, collect(a) AS arts
WHERE size(arts) >= 2
UNWIND arts AS art
OPTIONAL MATCH (art)-[]-(e)
WHERE NOT e:Norma AND NOT e:Articulo AND NOT e:VersionHistorica
WITH n, ubi, arts, e, collect(DISTINCT art.id) AS con_entidad
WHERE e IS NOT NULL AND size(con_entidad) < size(arts)
WITH n.id AS norma, ubi, labels(e)[0] AS entidad,
     size(con_entidad) AS con, size(arts) AS total,
     toFloat(size(con_entidad)) / size(arts) AS cobertura,
     [x IN [a IN arts | a.id] WHERE NOT x IN con_entidad] AS faltantes
WHERE cobertura >= 0.8
RETURN norma, ubi, entidad, con, total, cobertura, faltantes
ORDER BY cobertura DESC, total DESC
```

El corte que separa señal de ruido es si el artículo candidato tiene **alguna** entidad o
**ninguna**: los huérfanos casi siempre son huecos reales, los que ya tienen otra entidad
casi siempre están bien clasificados.

**La precisión es baja y hay que leerla con cuidado.** Sobre 7 candidatos verificados a mano,
solo 2 eran huecos reales. El grueso del ruido son artículos que tienen otra entidad *más
específica y correcta*:

| Artículo | Entidad "faltante" | Lo que realmente tiene | ¿Hueco? |
|---|---|---|---|
| Art. 287 CCyCN | `InstrumentoPublico` | `InstrumentoPrivado` | No — el artículo trata instrumentos privados |
| Art. 2291 CCyCN | `AceptacionHerencia` | `DerechoDeOpcion` | No — clasificación más precisa |
| Art. 1910 CCyCN | `Posesion` | `Tenencia (DEFINE)` | No — define tenencia, no posesión |
| Art. 21 RG 242/2023 | `DebidaDiligencia` | `SujetoObligado`, `UIF` | Dudoso |
| Art. 2128 CCyCN | `Superficie` | `DominioRevocable` | **Sí** — es "Normas aplicables a la propiedad superficiaria" |
| Art. 82 Ley 404 | `ActaNotarial` | ninguna | **Sí** |
| Art. 236 CP | `Rebelion` / `Sedicion` | ninguna | Dudoso — es una regla de concurso de cierre |

Por eso el script separa los candidatos en dos grupos: el corte útil es si el artículo tiene
**alguna** entidad o **ninguna**.

---

## 3. Candidatos HUÉRFANOS — resueltos (2026-08-31)

Artículos **sin ninguna entidad** en un capítulo donde ≥ 80% de sus vecinos sí la tienen.
Se leyó el texto completo de los cuatro antes de decidir:

| Artículo | Norma | Decisión | Motivo |
|---|---|---|---|
| Art. 82 | Ley 404 | **`DEFINE` → `ActaNotarial`** | "Las actas constituyen documentos matrices que deben extenderse en el protocolo": es la definición |
| Art. 99 | Ley 404 | **`REGULA` → `Certificado`** | Deber del notario de denegar la autenticación de impresiones digitales; está en el Cap. de Certificados |
| Art. 236 | Ley 11.179 (CP) | **`MENCIONA` → `Rebelion` y `Sedicion`** | Regla de concurso aplicable a los delitos del Título X. `MENCIONA` y no `REGULA`: no regula la rebelión, regula el concurso |
| Art. 5 | DTR 7/24 | **DESCARTADO** | Falso positivo: su texto completo es "Deróguense la DTR 7/2022 y su modificatoria, DTR 18/2023". Es una cláusula de derogación pura, sin relación con `DocumentoRegistrable` |

> **Pendiente derivado**: el Art. 5 de la DTR 7/24 no necesita una entidad de ontología, pero
> sí le falta la relación estructural `DEROGA_A` hacia la DTR 7/2022 y la DTR 18/2023.
>
> **Pendiente derivado**: el Art. 236 CP regula en rigor el concurso de hechos punibles.
> Evaluar agregarle `REGULA` → `ConcursoReal` (implicaría regenerar también ese resumen).

---

## 4. Candidatos CLASIFICADOS DISTINTO (revisar, mayormente ruido)

26 grupos, 25 entidades. Se listan completos en la salida del script. El único verificado
como hueco real ya fue corregido:

| Artículo | Decisión | Motivo |
|---|---|---|
| Art. 2128 CCyCN | **`REGULA` → `Superficie`** (2026-08-31) | Está en el Tít. VII "Superficie" y se titula "Normas aplicables a la propiedad superficiaria"; solo tenía `DominioRevocable` |

El resto requiere lectura artículo por artículo antes de tocar nada.

---

## 4 bis. Citas con el id interno en los resúmenes

Detectado el 2026-08-31. `exploration/generar_resumenes_entidades.py` armaba el contexto del
prompt encabezando cada artículo con su **id interno** (`[Art_83_Ley_404]`), única forma en
que el modelo veía el artículo. La regla del prompt le pedía citar norma y artículo, pero no
tenía de dónde sacarlos: 21 líneas del master `resumenes_entidades_completo.txt` quedaron con
ids crudos (`Art_83_Ley_404`, `Art_311_CCyCN`, `Art_47_Decreto_1624_2000`).

Corregido en el generador: `citar()` arma la cita legible desde el grafo y el prompt prohíbe
explícitamente escribir el id interno.

Criterio de cita:

| Tipo de norma | Forma | Ejemplo |
|---|---|---|
| Códigos | nombre corto de uso forense | `art. 2128, CCyCN` · `art. 226, Código Penal` · `art. 322, Código Fiscal CABA` |
| Ley | `Ley <número>` | `art. 82, Ley 404` · `art. 16, Ley 17.801` |
| Decreto | `Decreto <número>` | `art. 36, Decreto 2080/80` |
| RG / DTR / IT | sigla + número | `art. 5, DTR 7/24` · `art. 1, IT 8/2016` |

Los Códigos van por id (`_NOMBRE_CORTO`) y no por `tipo='Codigo'`, porque el Código Penal
(Ley 11.179) y el Código Fiscal de CABA (Ley 6926) están cargados con `tipo='Ley'`. Se usa el
nombre corto y no el título completo: repetir "Código Civil y Comercial de la Nación" en cada
cita hace el texto pesado de leer y la abreviatura no es ambigua para el lector.

**Resuelto el 2026-08-31.** Barrido de los 858 resúmenes de Neo4j y del archivo master con
seis patrones (id de artículo, id de norma, id de entidad, cabecera `ENTIDAD`/`(id: X)`/
`N directos`, separador `=====`, bloque de contexto `[Art_...]`):

- Neo4j: 2 ids crudos restantes → corregidos (`CesionDerechos`: `Art_1628_CCyCN`;
  `AgenteDeRetencion`: `Art_36_RG_2139_2006`), con embedding recalculado.
- Archivo master: 39 ocurrencias de 22 ids distintos → convertidas a cita legible,
  resolviendo cada una contra el grafo con `citar()`.
- **Estado final: 0 ids crudos en ambos lados.**

---

## 4 ter. Resumen contaminado con el bloque de otra entidad

Detectado el 2026-08-31 en el mismo barrido. `SituacionAdoptabilidad` tenía **26.740
caracteres**, de los cuales solo los primeros 7.957 eran suyos: a partir de ahí seguía con
`NTIDAD: SociedadAnonima (id: SOCIEDAD_ANONIMA) — 291 directos...` y el resumen completo de
`SociedadAnonima` pegado adentro (18.783 caracteres de sobra). La `E` faltante en `NTIDAD`
delata un corte de bloque mal hecho en una carga vieja.

Lo grave no era el texto sino el **embedding**: se había calculado sobre esa mezcla, así que
el vector de una entidad de derecho de familia estaba contaminado con derecho societario.

Un chequeo estructural lo confirmó por otra vía: era el resumen más largo de todo el grafo
con solo 11 artículos conectados, cuando el segundo más largo (`Contrato`) tiene 122.

**Corregido**: resumen reemplazado por el texto limpio del archivo master (7.957 car.) y
embedding recalculado. **Es el único caso** de los 858. No es un bug vivo del parser: el
archivo actual tiene sus 556 cabeceras bien formadas y parsearía correctamente.

---

## 5. El grafo es la fuente de verdad, no el archivo

Al comparar el master contra Neo4j aparecieron 12 entidades con textos distintos. No son
corrupción: son **generaciones sucesivas** del mismo resumen — cada vez que se corrigen
vinculaciones y se regenera, la versión buena se carga al grafo y el archivo conserva la
anterior. Se distinguen por el estilo de apertura (`## Concepto y Naturaleza Jurídica` vs
`# La X en el Derecho Argentino…`).

Por eso el flujo correcto es **volcar desde el grafo**, no editar el archivo:

```
python exploration/exportar_resumenes_y_contexto.py
```

Genera `resumenes_entidades_<fecha>.txt` y `contexto_entidades_<fecha>.txt` en
`input/entidades/`, con el formato de bloques de siempre (legible por
`cargar_resumenes_entidades.py`) y las citas ya en formato corto.

---

## 5. Artículos vigentes sin ninguna entidad de ontología: 567

No todos son errores (hay artículos de forma, vigencias, cláusulas de cierre), pero la
concentración por norma señala dónde la extracción rindió menos:

| Norma | Artículos sin entidad |
|---|---|
| RG 6/2017 | 44 |
| Decreto 1493/82 | 39 |
| Decreto 1624/2000 | 28 |
| Ley 11.179 (CP) | 25 |
| Decreto 2080/80 | 24 |
| Ley 22.315 | 23 |
| Ley 404 | 23 |
| RG 15/2024 | 22 |
| Ley 17.801 | 21 |
| RG 4/2026 | 15 |
| Decreto 70/2023 | 15 |
| Ley 27.551 | 12 |
| RG 2139/2006 | 11 |
| Ley 25.246 | 10 |
| RG 9/2026 | 10 |

Para el listado completo, la misma consulta de la sección 2 sin la condición de cobertura:
artículos vigentes sin ninguna entidad de ontología, agrupados por norma.

---

## 6. Resúmenes de entidades a regenerar con `qwen3.8:latest`

Cada vez que se agregue o corrija una vinculación artículo → entidad, el `resumen` y el
`embedding` de esa entidad quedan desactualizados. Se ponen al día con:

```
python exploration/regenerar_resumen_entidad.py <Entidad> [<Entidad> ...]
```

Reutiliza la lógica de `generar_resumenes_entidades.py` (prompt, `num_ctx` dinámico, citas)
y escribe directamente en Neo4j. Después, para dejar los archivos master al día:
`python exploration/exportar_resumenes_y_contexto.py`.

**Modelo obligatorio: `qwen3.8:latest`.** No usar otro salvo indicación expresa.

### Lotes A, B y C — HECHOS el 2026-08-31

Regenerados con qwen3.8:latest (7m51s) y cargados a Neo4j con resumen + embedding nuevos:

| Entidad | Lote | Motivo | Antes → Después |
|---|---|---|---|
| `TractoSucesivo` | A | +Arts. 36 y 37 Decreto 2080/80 | 10.577 → 8.966 car. |
| `ActaNotarial` | B | +Art. 82 Ley 404 | 9.663 → 9.812 car. |
| `Certificado` | B | +Art. 99 Ley 404 | 5.682 → 6.578 car. |
| `Rebelion` | B | +Art. 236 CP | 5.847 → 6.661 car. |
| `Sedicion` | B | +Art. 236 CP | 7.117 → 6.280 car. |
| `Superficie` | C | +Art. 2128 CCyCN | 11.151 → 11.822 car. |

`DocumentoRegistrable` quedó fuera: su candidato (Art. 5 DTR 7/24) era el falso positivo de
la sección 3, así que su contexto no cambió.

Cero ids crudos en los 51.729 caracteres generados. Queda una sola cita con el título largo
("el artículo 2127 del Código Civil y Comercial de la Nación", en `Superficie`): deriva de
redacción del modelo, no del prompt — el bloque de contexto decía `[art. 2127, CCyCN]`.

### Pendiente — las 25 entidades "clasificadas distinto"

No deben regenerarse hasta haber revisado los artículos uno por uno: regenerar un resumen
sobre un contexto que no cambió solo gasta tiempo de GPU.

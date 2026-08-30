# Pendientes y mejoras opcionales

Registro de tareas que quedaron diferidas y pueden o no hacerse más adelante.

---

## Grafo — Ontología

---

## Grafo — Ontología (continuación)

### Entidades Bien/Cosa para Arts. 225-241 CCyCN
Al ingresar el Título III (Bienes), Arts. 225-241 son definiciones de categorías jurídicas
(inmueble, mueble, fungible, divisible, fruto, dominio público, etc.). No se crearon entidades
ontológicas para ellas. Evaluar si conviene crear nodos como `BienInmueble`, `BienMueble`,
`BienFungible`, etc. que apunten a esos artículos, especialmente si normas registrales o
notariales del grafo los referencian.

## Resúmenes de entidades

### Incorporar resumen de entidad padre (ES_TIPO_DE) en Hipoteca, Anticresis y Prenda
`generar_resumenes_entidades.py` arma el contexto con `directos` + remisiones (`REMITE_A`), pero no
hace traversal de `ES_TIPO_DE` hacia la entidad padre. Hipoteca, Anticresis y Prenda son
`ES_TIPO_DE` `DerechoRealDeGarantia` (Arts. 2184-2204 CCyCN, disposiciones comunes a las tres).
Cuando se cargue el resumen maestro de entidades, agregar lógica para que el prompt de estas 3
entidades incluya también el resumen ya generado de `DerechoRealDeGarantia` como contexto adicional,
y regenerar los resúmenes de Hipoteca, Anticresis y Prenda con ese agregado.

### Incorporar resumen de entidad relacionada vía remisión (REMITE_A)
Recordatorio, mismo criterio que el punto anterior pero para entidades vinculadas a través de
artículos con relación `REMITE_A` (no solo `ES_TIPO_DE`). Cuando el contexto de una entidad
incluye artículos "adicionales" traídos por remisión y esos artículos pertenecen a otra entidad
de ontología, evaluar si conviene incorporar también el resumen ya generado de esa otra entidad,
además del texto de los artículos. Resolver junto con la carga del resumen maestro.

## Ingesta — Normas pendientes

*(Completar a medida que se identifiquen normas relevantes fuera del inventario actual)*

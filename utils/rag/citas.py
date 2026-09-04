"""Convención única para nombrar una norma en una cita legal, en sus dos representaciones:
Cypher (`NOMBRE_NORMA`, para queries que arman el nombre dentro del propio grafo) y Python
(`nombre_norma()` / `citar()`, para código que ya trajo las propiedades de la norma a memoria).

Si se toca una representación, tocar la otra: son la misma convención en dos lenguajes.
"""

# --- Nombre con el que se identifica una norma en las citas ---
# `titulo` no sirve para citar: 100 normas (DTR e IT) no lo tienen, y entre las que sí, unas
# traen el prefijo identificatorio ("Resolución General IGJ 15/2024 - ...") y otras solo el
# tema ("Personas Expuestas Políticamente Extranjeras", que es la RG 35/2023 y no se puede
# saber). El nombre canónico se arma con tipo + numero.
#
# Las DTR e IT toman el año del `id` y no de `numero`: 109 normas guardan el año con dos
# dígitos ("6/19") y solo el id tiene los cuatro ("DTR_6_2019").
NOMBRE_NORMA = """coalesce(
    CASE norma.id
        WHEN 'CCyCN'     THEN 'CCyCN'
        WHEN 'Ley_11179' THEN 'Código Penal'
        WHEN 'Ley_6926'  THEN 'Código Fiscal CABA'
        ELSE CASE norma.tipo
            WHEN 'Ley'                         THEN 'Ley ' + norma.numero
            WHEN 'Decreto'                     THEN 'Decreto ' + norma.numero
            WHEN 'ResolucionGeneral'           THEN 'RG ' + norma.numero
            WHEN 'Resolución'                  THEN 'RG ' + norma.numero
            WHEN 'DisposicionTecnicoRegistral' THEN 'DTR ' + split(norma.id, '_')[1] + '/' + split(norma.id, '_')[2]
            WHEN 'InstruccionDeTrabajo'        THEN 'IT ' + split(norma.id, '_')[1] + '/' + split(norma.id, '_')[2]
        END
    END,
    norma.titulo,
    norma.id,
    'Norma no identificada'
)"""

# Códigos: se citan por su nombre corto de uso forense. El título completo ("Código Civil y
# Comercial de la Nación") repetido en cada cita hace el texto pesado de leer, y el lector
# entiende la forma abreviada sin ambigüedad.
_NOMBRE_CORTO = {
    "CCyCN": "CCyCN",
    "Ley_11179": "Código Penal",
    "Ley_6926": "Código Fiscal CABA",
}

# Cómo nombrar cada tipo de norma en una cita a partir de su número. El id (Ley_404,
# DTR_7_2024) es interno y nunca debe llegar al texto de la cita. Las DTR e IT quedan
# afuera: van por norma_id (ver nombre_norma), igual que en NOMBRE_NORMA.
_ETIQUETA_NORMA = {
    "Ley": "Ley {numero}",
    "Decreto": "Decreto {numero}",
    "ResolucionGeneral": "RG {numero}",
    "Resolución": "RG {numero}",
}


def nombre_norma(tipo, numero, norma_id, titulo=None) -> str:
    """Nombre canónico de una norma para citarla. Misma convención que `NOMBRE_NORMA` en Cypher."""
    if norma_id in _NOMBRE_CORTO:
        return _NOMBRE_CORTO[norma_id]
    if tipo in ("DisposicionTecnicoRegistral", "InstruccionDeTrabajo") and norma_id:
        partes = norma_id.split("_")
        if len(partes) >= 3:
            prefijo = "DTR" if tipo == "DisposicionTecnicoRegistral" else "IT"
            return f"{prefijo} {partes[1]}/{partes[2]}"
    if tipo in _ETIQUETA_NORMA and numero:
        return _ETIQUETA_NORMA[tipo].format(numero=numero)
    return titulo or norma_id


def citar(art: dict) -> str:
    """Cita legible de un artículo: 'art. 82, Ley 404'. Nunca el id interno.

    `art` trae las propiedades de la norma con los alias ya usados en el proyecto:
    tipo, norma_numero, norma_id, norma_titulo, numero.
    """
    norma = nombre_norma(art.get("tipo"), art.get("norma_numero"), art.get("norma_id"), art.get("norma_titulo"))
    return f"art. {art.get('numero') or '?'}, {norma}"

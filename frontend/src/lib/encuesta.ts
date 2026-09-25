// La encuesta de la beta: cuándo aparece y qué pregunta.
//
// CUÁNDO. En 1 de cada 4 respuestas, en promedio, para que no se vuelva pesada. Se sortea con
// probabilidad 1/3 y nunca en dos respuestas seguidas: en régimen eso da exactamente 1/4
// (r = p / (1 + p)). Al azar y no «cada 4 respuestas» porque una regla fija cae siempre en la
// misma posición de la conversación —la cuarta pregunta suele ser una repregunta— y la muestra
// dejaría de representar al resto.
//
// QUÉ. La rúbrica viaja con su versión (`RUBRICA`) y el backend la guarda con cada nota. Si se
// cambia la redacción de una pregunta, hay que subir la versión: las notas de antes y de después
// dejan de ser comparables.

export const PROBABILIDAD = 1 / 3;

export const RUBRICA = "v1";

export type Dimension = "exactitud" | "pertinencia" | "completitud" | "fundamentacion";

export const DIMENSIONES: { clave: Dimension; nombre: string; pregunta: string; bajo: string; alto: string }[] = [
  {
    clave: "exactitud",
    nombre: "Exactitud",
    pregunta: "¿Lo que afirma es jurídicamente correcto?",
    bajo: "errores graves",
    alto: "sin errores",
  },
  {
    clave: "pertinencia",
    nombre: "Pertinencia",
    pregunta: "¿Responde lo que preguntaste?",
    bajo: "habla de otra cosa",
    alto: "va directo a la consulta",
  },
  {
    clave: "completitud",
    nombre: "Completitud",
    pregunta: "¿Cubre todo lo necesario para resolver el caso?",
    bajo: "omite lo esencial",
    alto: "no falta nada relevante",
  },
  {
    clave: "fundamentacion",
    nombre: "Fundamentación",
    pregunta: "¿Las normas y fallos citados son los que corresponden y dicen lo que la respuesta afirma?",
    bajo: "citas equivocadas o ausentes",
    alto: "citas exactas",
  },
];

// Vive a nivel de módulo: vale para toda la sesión del navegador, también entre conversaciones.
let laAnteriorTuvo = false;

/** ¿A esta respuesta le toca encuesta? Llamar UNA vez por respuesta terminada. */
export function sortearEncuesta(): boolean {
  const toca = !laAnteriorTuvo && Math.random() < PROBABILIDAD;
  laAnteriorTuvo = toca;
  return toca;
}

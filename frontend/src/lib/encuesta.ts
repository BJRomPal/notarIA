// La encuesta de la beta: cuándo aparece y qué pregunta.
//
// CUÁNDO. En 1 de cada 3 respuestas, en promedio. Se sortea con probabilidad 1/2 y nunca en dos
// respuestas seguidas: en régimen eso da exactamente 1/3 (r = p / (1 + p)). Al azar y no «cada 3
// respuestas» porque una regla fija cae siempre en la misma posición de la conversación —la
// tercera pregunta suele ser una repregunta— y la muestra dejaría de representar al resto.
//
// Empezó en 1 de cada 4 y en la prueba de Mariano (8 respuestas, 1 encuesta) resultó poco. Si
// 1/3 tampoco alcanza, para llegar a 1/2 NO basta con subir p: con la regla de «nunca dos
// seguidas» el máximo es 1/2 con p = 1, que ya no es azar sino alternar. Hay que sacar la regla y
// sortear con p = 1/2.
//
// Además, cada respuesta tiene un botón «Evaluar» para calificarla cuando el escribano quiera.
// Esas notas viajan con origen «voluntaria» y no cuentan para la muestra: ver OrigenEncuesta.
//
// QUÉ. La rúbrica viaja con su versión (`RUBRICA`) y el backend la guarda con cada nota. Si se
// cambia la redacción de una pregunta, hay que subir la versión: las notas de antes y de después
// dejan de ser comparables.

export const PROBABILIDAD = 1 / 2;

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

// Elimina la Resolución General IGJ 1/2018 del grafo.
// Motivo: derogada por RG IGJ 30/2020 (art. 7°).
// Ejecutar DESPUÉS de haber ingresado RG_30_2020.
//
// Los nodos de ontología compartidos (SociedadAnonima, Director, etc.) NO se eliminan
// porque pertenecen a otras normas ya ingresadas (Ley_19550, Ley_27349, etc.).

// 1. Eliminar todos los artículos de RG_1_2018 y sus relaciones
MATCH (art:Articulo)
WHERE art.id ENDS WITH '_RG_1_2018'
DETACH DELETE art;

// 2. Eliminar el nodo Norma y sus relaciones (CONTIENE, REGLAMENTA_TRAMITES, etc.)
MATCH (n:Norma {id: 'RG_1_2018'})
DETACH DELETE n;

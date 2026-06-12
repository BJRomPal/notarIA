// Remisiones explícitas de la RG IGJ 17/2022 a artículos de otras normas.
// Art. 1° cita: art. 6°, inc. f) de Ley 22315 y art. 267 de Ley 19550.

MATCH (origen:Articulo {id: 'Art_1_RG_17_2022'})
MATCH (dest1:Articulo  {id: 'Art_6_Ley_22315'})
MERGE (origen)-[:REMITE_A]->(dest1);

MATCH (origen:Articulo {id: 'Art_1_RG_17_2022'})
MATCH (dest2:Articulo  {id: 'Art_267_Ley_19550'})
MERGE (origen)-[:REMITE_A]->(dest2);

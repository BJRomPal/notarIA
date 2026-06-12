// Remisiones explícitas de la RG IGJ 12/2024 a artículos de la RG IGJ 6/2017.
// Art. 1° y 2° citan el art. 7° del Anexo A de la RG 6/2017.
// Art. 3°  cita el art. 32 del Anexo A de la RG 6/2017.

MATCH (a:Articulo {id: 'Art_1_RG_12_2024'})
MATCH (b:Articulo {id: 'Art_7_RG_6_2017'})
MERGE (a)-[:REMITE_A]->(b);

MATCH (a:Articulo {id: 'Art_2_RG_12_2024'})
MATCH (b:Articulo {id: 'Art_7_RG_6_2017'})
MERGE (a)-[:REMITE_A]->(b);

MATCH (a:Articulo {id: 'Art_3_RG_12_2024'})
MATCH (b:Articulo {id: 'Art_32_RG_6_2017'})
MERGE (a)-[:REMITE_A]->(b);

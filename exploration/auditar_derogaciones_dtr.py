"""Barrido de las DTR en busca de derogaciones no registradas en el grafo.

Detecta en el texto de cada artículo las fórmulas derogatorias habituales (derógase,
déjase sin efecto, quedan derogados) e identifica la norma o el artículo alcanzado.
Después contrasta contra Neo4j: si existe la relación DEROGA_A y si el destino quedó
marcado como no vigente y sin embedding.

No modifica nada: solo detecta y reporta.
"""
import os
import re
import sys
import glob

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "extractors"))
import ingest_dtr as ing

RUTA_INFORME = os.path.join(BASE_DIR, "input", "normas", "registral", "dtr",
                            "informe_derogaciones_dtr.md")

RE_DEROGA = re.compile(
    r'(der[óo]g(?:a|ue|an|uen)se|der[óo]ga(?:da|do|das|dos)s?|'
    r'quedan?\s+derogad|d[ée]j(?:a|e|an|en)se\s+sin\s+efecto|'
    r'sin\s+efecto\s+(?:l[ao]s?\s+)?(?:disposici|art))',
    re.IGNORECASE
)

RE_DTR_OBJ = re.compile(
    r'(?:D\.?\s?T\.?\s?R\.?|Disposici[óo]n(?:es)?\s+T[ée]cnico\s+Registral(?:es)?)'
    r'[^\d]{0,25}(\d{1,3})\s*[/\-]\s*(\d{2,4})',
    re.IGNORECASE
)
# Formato antiguo: "Disposición Técnico Registral Nro. 2 del 22 de julio de 1998"
_MESES = ("enero febrero marzo abril mayo junio julio agosto "
          "septiembre setiembre octubre noviembre diciembre").split()
RE_DTR_FECHA = re.compile(
    r'(?:D\.?\s?T\.?\s?R\.?|Disposici[óo]n(?:es)?\s+T[ée]cnico\s+Registral(?:es)?)'
    r'[^\d]{0,25}(\d{1,3})\s+del?\s+\d{1,2}\s+de\s+(' + "|".join(_MESES) + r')\s+de\s+(\d{4})',
    re.IGNORECASE
)

RE_LEY_OBJ = re.compile(r'[Ll]ey\s*N?[°º]?\.?\s*(\d{1,2}[\.\s]?\d{3})')
RE_DEC_OBJ = re.compile(r'[Dd]ecreto\s*N?[°º]?\.?\s*(\d{2,4})\s*[/\-]\s*(\d{2,4})')
RE_ART_OBJ = re.compile(r'art[íi]culos?\s+((?:\d{1,4}(?:\s*(?:bis|ter))?)'
                        r'(?:\s*(?:,|y)\s*\d{1,4}(?:\s*(?:bis|ter))?)*)', re.IGNORECASE)

VENTANA = 260


def norm_anio(raw: str) -> int:
    a = int(raw)
    if len(raw) == 2:
        return a + (1900 if a >= 70 else 2000)
    if len(raw) == 3:
        return a + 1000
    return a


def main():
    hallazgos = []
    for anio in sorted([d for d in os.listdir(ing.DTR_DIR)
                        if os.path.isdir(os.path.join(ing.DTR_DIR, d))], key=int):
        for path in sorted(glob.glob(os.path.join(ing.DTR_DIR, anio, "*.txt"))):
            m = re.match(r'dtr\s+(\d+)-(\d+)\.txt', os.path.basename(path), re.IGNORECASE)
            if not m:
                continue
            norma_origen = f"DTR_{m.group(1)}_{anio}"
            crudo = open(path, encoding="utf-8").read()
            if not crudo.strip():
                continue
            for numero, txt in ing.parsear_dtr(crudo)[2]:
                art_id = f"Art_{numero}_{norma_origen}"
                for d in RE_DEROGA.finditer(txt):
                    frag = txt[d.start(): d.start() + VENTANA]
                    objetivos = []
                    for om in RE_DTR_OBJ.finditer(frag):
                        objetivos.append(("DTR", f"DTR_{om.group(1)}_{norm_anio(om.group(2))}"))
                    for om in RE_DTR_FECHA.finditer(frag):
                        objetivos.append(("DTR", f"DTR_{om.group(1)}_{om.group(3)}"))
                    for om in RE_LEY_OBJ.finditer(frag):
                        objetivos.append(("Ley", f"Ley_{re.sub(r'\\D', '', om.group(1))}"))
                    for om in RE_DEC_OBJ.finditer(frag):
                        objetivos.append(("Decreto",
                                          f"Decreto_{om.group(1)}_{norm_anio(om.group(2))}"))
                    arts = RE_ART_OBJ.findall(frag)
                    hallazgos.append({
                        "origen": art_id,
                        "norma_origen": norma_origen,
                        "frag": re.sub(r'\s+', ' ', frag).strip()[:200],
                        "objetivos": list(dict.fromkeys(objetivos)),
                        "arts_citados": arts[0] if arts else None,
                    })

    # --- contrastar contra el grafo ---
    filas = []
    with ing.driver.session() as s:
        for h in hallazgos:
            for tipo, norma_dest in h["objetivos"]:
                r = s.run("MATCH (n:Norma {id:$i}) OPTIONAL MATCH (n)-[:CONTIENE]->(a:Articulo) "
                          "RETURN n.vigente AS vig, count(a) AS arts, "
                          "sum(CASE WHEN a.embedding IS NOT NULL THEN 1 ELSE 0 END) AS emb",
                          i=norma_dest).single()
                if r is None or r["arts"] is None and r["vig"] is None:
                    estado, vig, emb = "NORMA NO CARGADA", None, None
                else:
                    vig, emb = r["vig"], r["emb"]
                    estado = "cargada"
                tiene_der = s.run(
                    "MATCH (:Articulo {id:$o})-[:DEROGA_A]->(t) "
                    "WHERE t.id = $n OR t.id ENDS WITH $suf RETURN count(*) AS c",
                    o=h["origen"], n=norma_dest, suf=f"_{norma_dest}").single()["c"]
                filas.append({**h, "tipo": tipo, "destino": norma_dest,
                              "estado": estado, "vigente": vig, "con_emb": emb,
                              "deroga_a": tiene_der})

    pendientes = [f for f in filas if f["estado"] == "cargada"
                  and (f["deroga_a"] == 0 or f["vigente"] is not False)]
    ok = [f for f in filas if f["estado"] == "cargada" and f["deroga_a"] > 0
          and f["vigente"] is False]
    no_cargadas = [f for f in filas if f["estado"] == "NORMA NO CARGADA"]
    sin_objetivo = [h for h in hallazgos if not h["objetivos"]]

    print(f"Fórmulas derogatorias detectadas : {len(hallazgos)}")
    print(f"  con norma objetivo identificada: {len(filas)}")
    print(f"  sin objetivo normativo claro   : {len(sin_objetivo)}\n")
    print(f"YA REGISTRADAS CORRECTAMENTE     : {len(ok)}")
    print(f"PENDIENTES (norma cargada)       : {len(pendientes)}")
    print(f"OBJETIVO NO CARGADO EN EL GRAFO  : {len(no_cargadas)}\n")

    if pendientes:
        print("=" * 78)
        print("DEROGACIONES PENDIENTES")
        print("=" * 78)
        for f in pendientes:
            arts = f" (arts. {f['arts_citados']})" if f["arts_citados"] else " (norma completa)"
            print(f"\n  {f['origen']}  ->  {f['destino']}{arts}")
            print(f"     vigente={f['vigente']}  embeddings={f['con_emb']}  DEROGA_A={f['deroga_a']}")
            print(f"     \"{f['frag'][:150]}\"")

    with open(RUTA_INFORME, "w", encoding="utf-8") as fh:
        fh.write("# Informe — derogaciones detectadas en las DTR\n\n")
        fh.write(f"- Fórmulas derogatorias detectadas: {len(hallazgos)}\n")
        fh.write(f"- Ya registradas correctamente: {len(ok)}\n")
        fh.write(f"- **Pendientes (norma cargada): {len(pendientes)}**\n")
        fh.write(f"- Objetivo no cargado en el grafo: {len(no_cargadas)}\n")
        fh.write(f"- Sin objetivo normativo claro: {len(sin_objetivo)}\n\n")
        for titulo, grupo in (("Pendientes", pendientes), ("Ya registradas", ok),
                              ("Objetivo no cargado", no_cargadas)):
            fh.write(f"\n## {titulo} ({len(grupo)})\n\n")
            for f in grupo:
                arts = f" — arts. {f['arts_citados']}" if f["arts_citados"] else " — norma completa"
                fh.write(f"- `{f['origen']}` → `{f['destino']}`{arts}\n")
                fh.write(f"  - vigente={f['vigente']}, embeddings={f['con_emb']}, "
                         f"DEROGA_A={f['deroga_a']}\n  - \"{f['frag'][:180]}\"\n")
        fh.write(f"\n## Sin objetivo normativo claro ({len(sin_objetivo)})\n\n")
        for h in sin_objetivo:
            fh.write(f"- `{h['origen']}`\n  - \"{h['frag'][:180]}\"\n")
    print(f"\nInforme escrito en {os.path.relpath(RUTA_INFORME, BASE_DIR)}")


if __name__ == "__main__":
    main()

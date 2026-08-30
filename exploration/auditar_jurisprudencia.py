"""Auditoría previa a la ingesta de jurisprudencia: deduplica por hash de contenido y
reporta qué fallos no tienen el encabezado completo (tribunal / carátula / fecha / expediente).

Los duplicados NO se borran: se mueven a `_duplicados/` (input/ está en .gitignore, así que
un borrado sería irreversible). El nombre de cada archivo es metadata — el mismo fallo
archivado bajo varios nombres indica los distintos temas por los que interesa —, así que
los nombres descartados quedan registrados en el reporte como alias.

Uso:
    python exploration/auditar_jurisprudencia.py           # solo reporta, no toca nada
    python exploration/auditar_jurisprudencia.py --aplicar # mueve los duplicados
"""
import hashlib
import os
import re
import shutil
import sys
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_FALLOS = os.path.join(BASE_DIR, "input", "Jurisprudencia")
DIR_DUPLICADOS = os.path.join(DIR_FALLOS, "_duplicados")
RUTA_REPORTE = os.path.join(BASE_DIR, "input", "Jurisprudencia", "_auditoria.md")

APLICAR = "--aplicar" in sys.argv

# --- Detección de los 4 componentes del encabezado ---
# Se busca en las primeras líneas no vacías: los exports de La Ley ponen
# tribunal / carátula / fecha / expediente en ese orden, pero solo ~2/3 de los
# archivos lo respetan, así que cada componente se busca por patrón y no por posición.
VENTANA = 8  # líneas no vacías iniciales donde se busca el encabezado

RE_TRIBUNAL = re.compile(
    r'c[áa]mara|corte|tribunal|juzgado|suprem|CNACiv|CSJN|CNCom|CNCiv|sala\s|'
    r'superior\s+de\s+justicia|fiscal\s+de\s+la\s+naci[óo]n',
    re.IGNORECASE,
)
# La carátula se escribe de formas muy distintas según el origen: "A c/ B s/ objeto",
# "A contra B sobre objeto", "A v. B", o "A s/sucesión" sin espacios. Los casos de parte
# única (sumarios disciplinarios, apelaciones fiscales) no llevan contraparte y son válidos.
RE_CARATULA = re.compile(
    r'\sc/|\sc\.\s|\ss/|\svs?\.\s|\scontra\s|\ssobre\s|s/suc',
    re.IGNORECASE,
)

# La fecha aparece en cuatro formatos según el origen del archivo: numérica con barras
# (exports de La Ley), numérica con guiones (recursos registrales), en prosa, y en prosa
# con el año escrito en letras. Detectar solo el primero daba ~80 falsos positivos.
_MES = r'(?:ene|feb|mar|abr|may|jun|jul|ago|sep|set|oct|nov|dic)[a-z]*'
RE_FECHA = re.compile(
    r'\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b'
    rf'|\b\d{{1,2}}\s+de\s+{_MES}\s+de\s+\d{{4}}'
    rf'|\b{_MES}\s+\d{{1,2}}\s+de\s+\d{{4}}'
    rf'|\b{_MES}\s+de\s+(?:dos\s+mil|mil\s+novecientos)\b'
    rf'|\bde\s+{_MES}\s+de\s+(?:dos\s+mil|mil\s+novecientos)\b',
    re.IGNORECASE,
)
RE_EXPTE = re.compile(
    r'expte|expediente|actuaciones\s+n|causa\s+n|'
    r'\bn[°º]\s*\d|\bnro\.?\s*\d|\bCIV\s+\d|\bCNT\s+\d|\bCOM\s+\d',
    re.IGNORECASE,
)


def analizar_encabezado(texto: str) -> dict:
    lineas = [l.strip() for l in texto.split("\n")]
    cabeza = [l for l in lineas if l][:VENTANA]
    bloque = "\n".join(cabeza)
    return {
        "tribunal": bool(RE_TRIBUNAL.search(bloque)),
        "caratula": bool(RE_CARATULA.search(bloque)),
        "fecha":    bool(RE_FECHA.search(bloque)),
        "expte":    bool(RE_EXPTE.search(bloque)),
        "primeras": cabeza[:4],
    }


def main():
    archivos = []
    for root, dirs, files in os.walk(DIR_FALLOS):
        dirs[:] = [d for d in dirs if not d.startswith("_")]
        for fn in sorted(files):
            if fn.endswith(".txt"):
                archivos.append(os.path.join(root, fn))

    por_hash = defaultdict(list)
    datos = {}
    for ruta in archivos:
        with open(ruta, encoding="utf-8", errors="replace") as f:
            contenido = f.read()
        rel = os.path.relpath(ruta, DIR_FALLOS)
        por_hash[hashlib.md5(contenido.strip().encode()).hexdigest()].append(rel)
        datos[rel] = {"ruta": ruta, "chars": len(contenido), **analizar_encabezado(contenido)}

    # --- Deduplicación: se conserva el nombre más descriptivo (el más largo) ---
    grupos = {h: sorted(rels, key=lambda r: (-len(os.path.basename(r)), r))
              for h, rels in por_hash.items() if len(rels) > 1}
    canonicos = {h: rels[0] for h, rels in grupos.items()}
    a_mover = [(h, r) for h, rels in grupos.items() for r in rels[1:]]

    print(f"Archivos analizados : {len(archivos)}")
    print(f"Fallos únicos       : {len(por_hash)}")
    print(f"Grupos duplicados   : {len(grupos)}  ({len(a_mover)} archivos redundantes)")
    print()

    print("=" * 78)
    print("DEDUPLICACIÓN — se conserva el nombre más descriptivo; el resto queda como alias")
    print("=" * 78)
    for h, rels in sorted(grupos.items(), key=lambda kv: canonicos[kv[0]]):
        print(f"\n  CONSERVA : {canonicos[h]}")
        for r in rels[1:]:
            print(f"  alias    : {r}")

    if APLICAR:
        os.makedirs(DIR_DUPLICADOS, exist_ok=True)
        for _, rel in a_mover:
            destino = os.path.join(DIR_DUPLICADOS, rel.replace(os.sep, "__"))
            shutil.move(datos[rel]["ruta"], destino)
        print(f"\n  -> {len(a_mover)} archivos movidos a {os.path.relpath(DIR_DUPLICADOS, BASE_DIR)}/")
    else:
        print(f"\n  (simulación — usar --aplicar para mover los {len(a_mover)} archivos)")

    # --- Encabezados incompletos, solo sobre los fallos que quedan ---
    descartados = {r for _, r in a_mover}
    vigentes = [r for r in sorted(datos) if r not in descartados]
    incompletos = [r for r in vigentes
                   if not all(datos[r][c] for c in ("tribunal", "caratula", "fecha", "expte"))]

    print()
    print("=" * 78)
    print(f"ENCABEZADO INCOMPLETO — {len(incompletos)} de {len(vigentes)} fallos")
    print("=" * 78)

    faltantes = defaultdict(list)
    for r in incompletos:
        falta = tuple(c for c in ("tribunal", "caratula", "fecha", "expte") if not datos[r][c])
        faltantes[falta].append(r)

    for falta, rels in sorted(faltantes.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        print(f"\n--- Falta: {', '.join(falta)}  ({len(rels)} fallos) ---")
        for r in rels:
            print(f"  {r}   [{datos[r]['chars']} chars]")
            for l in datos[r]["primeras"][:2]:
                print(f"      | {l[:100]}")

    # --- Reporte en disco ---
    with open(RUTA_REPORTE, "w", encoding="utf-8") as f:
        f.write("# Auditoría de la carpeta Jurisprudencia\n\n")
        f.write(f"- Archivos analizados: {len(archivos)}\n")
        f.write(f"- Fallos únicos: {len(por_hash)}\n")
        f.write(f"- Grupos duplicados: {len(grupos)} ({len(a_mover)} archivos redundantes)\n")
        f.write(f"- Encabezado incompleto: {len(incompletos)} de {len(vigentes)}\n\n")
        f.write("## Duplicados (el alias indica bajo qué otros temas se archivó el mismo fallo)\n\n")
        for h, rels in sorted(grupos.items(), key=lambda kv: canonicos[kv[0]]):
            f.write(f"- **{canonicos[h]}**\n")
            for r in rels[1:]:
                f.write(f"  - alias: {r}\n")
        f.write("\n## Encabezado incompleto\n\n")
        for falta, rels in sorted(faltantes.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            f.write(f"\n### Falta: {', '.join(falta)} ({len(rels)})\n\n")
            for r in rels:
                f.write(f"- `{r}` — {datos[r]['chars']} chars\n")
                for l in datos[r]["primeras"][:2]:
                    f.write(f"  - `{l[:120]}`\n")
    print(f"\n\nReporte escrito en {os.path.relpath(RUTA_REPORTE, BASE_DIR)}")


if __name__ == "__main__":
    main()

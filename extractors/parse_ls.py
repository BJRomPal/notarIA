"""Extrae artículos individuales de la Ley General de Sociedades (19.550) desde un
archivo de texto plano y los guarda como archivos .txt separados. Variante de
extractor_cc.py adaptada a la estructura CAPÍTULO/SECCIÓN/SUBSECCIÓN de la LSC;
incorpora lookahead para asociar epígrafes al artículo correcto y maneja el sufijo 'bis'."""
import re
import os

def extraer_articulos_lsc(ruta_archivo_entrada, directorio_salida):
    # Crear el directorio de salida si no existe
    if not os.path.exists(directorio_salida):
        os.makedirs(directorio_salida)

    # Leer el archivo completo
    with open(ruta_archivo_entrada, 'r', encoding='utf-8') as f:
        lineas = f.readlines()

    # Diccionario para mantener el contexto jerárquico actual
    jerarquia = {
        "CAPITULO": "",
        "SECCION": "",
        "SUBSECCION": ""
    }
    
    ultimo_marcador = None
    numero_articulo_actual = None
    texto_articulo_actual = []
    titulo_pendiente = None

    def guardar_articulo():
        """Guarda el artículo acumulado en un archivo y resetea las variables."""
        nonlocal numero_articulo_actual, texto_articulo_actual
        
        if numero_articulo_actual:
            # Reemplazamos espacios por guiones bajos para casos como "94 bis"
            num_limpio = numero_articulo_actual.replace(" ", "_")
            nombre_archivo = os.path.join(directorio_salida, f"Articulo_{num_limpio}.txt")
            
            with open(nombre_archivo, 'w', encoding='utf-8') as f:
                # Escribir la jerarquía como contexto
                for nivel, valor in jerarquia.items():
                    if valor:
                        f.write(f"{nivel}: {valor}\n")
                f.write("-" * 50 + "\n")
                
                # Escribir el cuerpo del artículo
                f.write("\n".join(texto_articulo_actual))
            
            # --- CLAVE: Resetear para evitar arrastre de datos ---
            numero_articulo_actual = None
            texto_articulo_actual = []

    i = 0
    # Regex para detectar el inicio del artículo (tolera "ARTÍCULO 94 bis. —")
    regex_articulo = r'^ART[IÍ]CULO\s+(\d+(?:\s+bis)?)[°º\.]?\s*[—\-]'

    while i < len(lineas):
        linea = lineas[i].strip()
        if not linea:
            i += 1
            continue

        # 1. Detectar marcadores de jerarquía
        es_marcador = False
        
        if re.match(r'^CAPITULO\s+[IVXLC]+', linea, re.IGNORECASE):
            guardar_articulo() # Cierra el artículo anterior
            jerarquia["CAPITULO"] = linea
            jerarquia["SECCION"] = ""
            jerarquia["SUBSECCION"] = ""
            ultimo_marcador = "CAPITULO"
            es_marcador = True
        elif re.match(r'^SECCION\s+[IVXLC]+', linea, re.IGNORECASE):
            guardar_articulo() # Cierra el artículo anterior
            jerarquia["SECCION"] = linea
            jerarquia["SUBSECCION"] = ""
            ultimo_marcador = "SECCION"
            es_marcador = True
        elif re.match(r'^\d+[°º]\.\s+', linea): # Detecta "1º. De la naturaleza..."
            guardar_articulo() # Cierra el artículo anterior
            jerarquia["SUBSECCION"] = linea
            ultimo_marcador = None 
            es_marcador = True

        if es_marcador:
            i += 1
            continue

        # 2. Detectar si la línea actual es el epígrafe del artículo siguiente (lookahead)
        es_titulo = False
        match_articulo = re.match(regex_articulo, linea, re.IGNORECASE)
        
        if not match_articulo:
            # Miramos las siguientes líneas ignorando las vacías
            j = i + 1
            while j < len(lineas) and not lineas[j].strip():
                j += 1
            if j < len(lineas):
                next_line = lineas[j].strip()
                if re.match(regex_articulo, next_line, re.IGNORECASE):
                    es_titulo = True

        if es_titulo:
            guardar_articulo() # Cierra el artículo anterior, este título pertenece al nuevo
            titulo_pendiente = linea
            i += 1
            continue

        # 3. Procesar el inicio de un Artículo
        if match_articulo:
            guardar_articulo() # Por seguridad, forzamos cierre si no hubo epígrafe
            numero_articulo_actual = match_articulo.group(1) 
            
            # Si teníamos un título pendiente detectado en la iteración anterior, lo agregamos primero
            if titulo_pendiente:
                texto_articulo_actual.append(titulo_pendiente)
                titulo_pendiente = None
                
            texto_articulo_actual.append(linea)
            ultimo_marcador = None # Ya pasamos la declaración de la jerarquía
            i += 1
            continue

        # 4. Procesar texto intermedio (nombres descriptivos de Capítulos/Secciones o el cuerpo del artículo)
        if ultimo_marcador and not numero_articulo_actual:
            jerarquia[ultimo_marcador] += f" - {linea}"
            ultimo_marcador = None
        elif numero_articulo_actual:
            texto_articulo_actual.append(linea)
        
        i += 1

    # Guardar el último artículo procesado al llegar al final del documento
    guardar_articulo()
    print(f"Extracción finalizada con éxito. Archivos guardados en la carpeta: {directorio_salida}/")

# --- Ejecución del script ---
if __name__ == "__main__":
    archivo_texto_original = "projects/notaria/input/normas/sociedades/Ley/19550.txt" 
    carpeta_destino = "projects/notaria/input/normas/sociedades/Ley/articulos_lsc"
    
    if not os.path.exists(archivo_texto_original):
        print(f"Por favor, asegúrate de que el archivo '{archivo_texto_original}' exista en el directorio.")
    else:
        extraer_articulos_lsc(archivo_texto_original, carpeta_destino)
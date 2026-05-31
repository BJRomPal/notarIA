"""Extrae artículos individuales de un texto legal plano (Código Civil y Comercial)
y los guarda como archivos .txt separados. Incluye en la cabecera de cada archivo el
contexto jerárquico (LIBRO, TÍTULO, CAPÍTULO, etc.) vigente al momento del artículo."""
import re
import os

def extraer_articulos(ruta_archivo_entrada, directorio_salida):
    # Crear el directorio de salida si no existe
    if not os.path.exists(directorio_salida):
        os.makedirs(directorio_salida)

    # Leer el archivo completo
    with open(ruta_archivo_entrada, 'r', encoding='utf-8') as f:
        lineas = f.readlines()

    # Diccionario para mantener el contexto jerárquico actual
    jerarquia = {
        "LIBRO": "", 
        "PARTE": "",
        "TITULO": "", 
        "CAPITULO": "", 
        "SECCION": "", 
        "PARAGRAFO": ""
    }
    
    ultimo_marcador = None
    numero_articulo_actual = None
    texto_articulo_actual = []

    def guardar_articulo():
        """Guarda el artículo acumulado en un archivo de texto con su contexto."""
        if numero_articulo_actual:
            # El archivo se guardará como Articulo_1.txt, Articulo_10.txt, etc.
            nombre_archivo = os.path.join(directorio_salida, f"Articulo_{numero_articulo_actual}.txt")
            with open(nombre_archivo, 'w', encoding='utf-8') as f:
                # Escribir la jerarquía como contexto en la cabecera del archivo
                for nivel, valor in jerarquia.items():
                    if valor:
                        f.write(f"{nivel}: {valor}\n")
                f.write("-" * 50 + "\n")
                
                # Escribir el cuerpo del artículo
                f.write("\n".join(texto_articulo_actual))
                
    for linea in lineas:
        linea = linea.strip()
        if not linea:
            continue

        # 1. Detectar marcadores de jerarquía (normalizando a mayúsculas para evitar fallos)
        es_marcador = False
        marcadores_claves = ["LIBRO", "PARTE", "TITULO", "CAPITULO", "SECCION", "PARAGRAFO"]
        
        for clave in marcadores_claves:
            # Convertimos la línea a mayúsculas y eliminamos acentos comunes para la comparación
            linea_limpia = linea.upper().replace('Í', 'I').replace('Ó', 'O').replace('Á', 'A')
            
            if linea_limpia.startswith(clave):
                jerarquia[clave] = linea  # Guardamos la línea original (ej. "TITULO PRELIMINAR")
                
                # Al entrar a un nivel jerárquico nuevo, limpiamos los niveles inferiores
                niveles = list(jerarquia.keys())
                idx = niveles.index(clave)
                for nivel_inferior in niveles[idx+1:]:
                    jerarquia[nivel_inferior] = ""
                
                ultimo_marcador = clave
                es_marcador = True
                break
        
        if es_marcador:
            continue

        # 2. Detectar inicio de un nuevo Artículo
        # La regex ahora tolera "ARTICULO", "ARTÍCULO", el símbolo "°", el ordinal "º" y el punto ".-"
        match_articulo = re.match(r'^ART[IÍ]CULO\s+(\d+)[°º]?', linea, re.IGNORECASE)
        if match_articulo:
            # Si ya estábamos procesando un artículo, lo guardamos antes de empezar el nuevo
            guardar_articulo()
            
            numero_articulo_actual = match_articulo.group(1) # Extrae solo el número limpio
            texto_articulo_actual = [linea]
            ultimo_marcador = None # Ya no estamos esperando el nombre de un título
            continue

        # 3. Procesar texto intermedio (nombres de capítulos/títulos o contenido de artículos)
        if ultimo_marcador and not numero_articulo_actual:
            # Añade el texto al marcador actual (ej: concatena "CAPITULO 1" con "Derecho")
            jerarquia[ultimo_marcador] += f" - {linea}"
            ultimo_marcador = None 
        elif numero_articulo_actual:
            # Si ya estamos dentro de un artículo, agregamos la línea al cuerpo
            texto_articulo_actual.append(linea)

    # Guardar el último artículo procesado al llegar al final del archivo
    guardar_articulo()
    print(f"Extracción finalizada con éxito. Archivos guardados en: {directorio_salida}/")

# --- Ejecución del script ---
if __name__ == "__main__":
    # Define aquí la ruta de tu archivo de texto original
    archivo_texto_original = "./ccyc/TITULO PRELIMINAR.txt" 
    
    # Define la carpeta donde se guardarán los archivos txt resultantes
    carpeta_destino = "./civil_extracted"
    
    # Crea un archivo de prueba si no existe para que puedas probar el script inmediatamente
    if not os.path.exists(archivo_texto_original):
        print(f"Por favor, asegúrate de que el archivo '{archivo_texto_original}' exista en el directorio.")
    else:
        extraer_articulos(archivo_texto_original, carpeta_destino)
"""Utilidades genéricas de formato de texto, compartidas por el pipeline RAG."""
import unicodedata


def normalizar(texto: str) -> str:
    """Minúsculas sin tildes ni diacríticos, para comparaciones tolerantes a acentos."""
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii").lower()


def formato_articulo(fuente: str, numero: str, texto: str) -> str:
    """Formato canónico de un artículo para el contexto del LLM.
    Replica el mismo layout que arma `retrieval_query` en Cypher."""
    return f"FUENTE: {fuente}\nARTICULO: {numero}\nTEXTO: {texto}"

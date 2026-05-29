"""Funciones de fábrica centralizadas para los servicios externos del proyecto:
Neo4j (grafo), Gemini (embeddings y LLM de generación RAG) y Ollama (LLM de extracción).
Todas leen credenciales del .env en la raíz del proyecto."""
import os, requests, logging
from dotenv import load_dotenv
from neo4j import GraphDatabase
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_ollama import ChatOllama

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

_log = logging.getLogger("connectors")


def get_neo4j_driver():
    uri = os.getenv("NEO4J_URI") or ""
    user = os.getenv("NEO4J_USERNAME") or ""
    password = os.getenv("NEO4J_PASSWORD") or ""
    return GraphDatabase.driver(uri, auth=(user, password))


def get_gemini_embeddings():
    return GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")


def get_gemini_llm(model: str = "gemini-2.5-flash-lite", temperature: float = 0.0):
    return ChatGoogleGenerativeAI(model=model, temperature=temperature)


# format="json" fuerza a Ollama a emitir JSON puro sin texto adicional;
# imprescindible porque el pipeline parsea la respuesta con json.loads() directamente.
def get_ollama_llm(model: str = "gemma4:e4b", temperature: float = 0.0):
    return ChatOllama(model=model, temperature=temperature, format="json")


def enviar_alerta(mensaje: str) -> None:
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        _log.warning("Telegram: credenciales no configuradas en .env — notificación omitida.")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": mensaje}, timeout=10)
        if not resp.ok:
            _log.error(f"Telegram respondió con error {resp.status_code}: {resp.text}")
    except Exception as e:
        _log.error(f"Error enviando notificación Telegram: {e}")

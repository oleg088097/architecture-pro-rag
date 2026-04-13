from __future__ import annotations

import argparse
import hashlib
import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

import chromadb
import tiktoken
import torch
from chromadb import Collection
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL_ID = "BAAI/bge-m3"
ENCODING_NAME = "cl100k_base"
CHUNK_TOKENS = 700
CHUNK_OVERLAP_TOKENS = 100

ROOT = Path(__file__).resolve().parent
DEFAULT_KB_DIR = ROOT.parent / "task2" / "knowledge_base"
DEFAULT_CHROMA_DIR = ROOT / "chroma_data"
COLLECTION_NAME = "pokemon_kb"

def read_title_and_body(raw: str) -> tuple[str, str]:
    """Первая строка вида '# Title' -> заголовок; тело без изменений для позиций чанков."""
    lines = raw.splitlines()
    title = ""
    if lines and lines[0].lstrip().startswith("#"):
        title = lines[0].lstrip("#").strip()
    return title, raw


def stable_chunk_id(source_rel: str, chunk_index: int) -> str:
    h = hashlib.sha256(f"{source_rel}:{chunk_index}".encode()).hexdigest()[:24]
    return f"chunk_{h}"


def build_chunks_for_file(path: Path, kb_root: Path, splitter: RecursiveCharacterTextSplitter) -> list[dict]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    title, body = read_title_and_body(raw)
    rel = str(path.relative_to(kb_root))
    if not title:
        title = path.stem.replace("_", " ")

    docs = splitter.create_documents([body], metadatas=[{"source": rel}])
    chunks: list[dict] = []
    for i, doc in enumerate(docs):
        start = doc.metadata.get("start_index")
        if start is None:
            start = body.find(doc.page_content)
        end = start + len(doc.page_content) if start >= 0 else -1
        chunks.append(
            {
                "text": doc.page_content,
                "metadata": {
                    "source_path": rel,
                    "source_file": path.name,
                    "title": title,
                    "chunk_index": i,
                    "chunk_total_hint": len(docs),
                    "char_start": int(start) if start >= 0 else -1,
                    "char_end": int(end) if end >= 0 else -1,
                },
            }
        )
    return chunks


def load_embedding_model() -> SentenceTransformer:
    return SentenceTransformer(
        EMBEDDING_MODEL_ID, 
        device="cuda" if torch.cuda.is_available() else "cpu", 
        trust_remote_code=True
    )


def embed_texts(model: SentenceTransformer, texts: list[str], batch_size: int = 16) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        emb = model.encode(
            batch,
            normalize_embeddings=True,
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        out.extend(emb.tolist())
    return out


def get_or_create_collection(
    chroma_dir: Path,
    reset: bool,
) -> Collection:
    client = chromadb.PersistentClient(path=str(chroma_dir))
    if reset:
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
    )


def cmd_index(args: argparse.Namespace) -> None:
    t_total = time.perf_counter()
    kb_dir: Path = args.kb_dir
    if not kb_dir.is_dir():
        print(f"Каталог базы знаний не найден: {kb_dir}", file=sys.stderr)
        sys.exit(1)

    enc = tiktoken.get_encoding(ENCODING_NAME)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_TOKENS,
        chunk_overlap=CHUNK_OVERLAP_TOKENS,
        length_function=lambda text: len(enc.encode(text)),
        separators=["\n\n", "\n", ". ", " ", ""],
        is_separator_regex=False,
        add_start_index=True,
    )

    t0 = time.perf_counter()
    all_records: list[dict] = []
    for md in sorted(p for p in kb_dir.glob("*.md") if p.is_file()):
        all_records.extend(build_chunks_for_file(md, kb_dir, splitter))
    logger.info("Чанкование: %.3f с", time.perf_counter() - t0)

    if not all_records:
        print("Нет .md файлов для индексации.", file=sys.stderr)
        sys.exit(1)

    t0 = time.perf_counter()
    model = load_embedding_model()
    logger.info("Загрузка модели эмбеддингов: %.3f с", time.perf_counter() - t0)

    texts = [r["text"] for r in all_records]
    print(f"Чанков: {len(texts)}; считаем эмбеддинги…")
    t0 = time.perf_counter()
    embeddings = embed_texts(model, texts, batch_size=args.batch_size)
    logger.info("Генерация эмбеддингов (%d чанков): %.3f с", len(texts), time.perf_counter() - t0)

    ids = [stable_chunk_id(r["metadata"]["source_path"], r["metadata"]["chunk_index"]) for r in all_records]
    metadatas = []
    for r in all_records:
        m = r["metadata"].copy()
        # Chroma хранит метаданные как str / int / float / bool; списки — через сериализацию строкой при необходимости
        m["chunk_index"] = int(m["chunk_index"])
        m["char_start"] = int(m["char_start"])
        m["char_end"] = int(m["char_end"])
        m["chunk_total_hint"] = int(m["chunk_total_hint"])
        metadatas.append(m)

    collection = get_or_create_collection(args.chroma_dir, reset=args.reset)
    t0 = time.perf_counter()
    collection.upsert(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)
    logger.info("Запись в Chroma (upsert): %.3f с", time.perf_counter() - t0)

    logger.info("Итого построение индекса: %.3f с", time.perf_counter() - t_total)
    print(f"Готово. Коллекция «{COLLECTION_NAME}» в {args.chroma_dir.resolve()}")
    print(f"Документов (чанков): {collection.count()}")


def cmd_query(args: argparse.Namespace) -> None:
    client = chromadb.PersistentClient(path=str(args.chroma_dir))
    collection = client.get_collection(COLLECTION_NAME)
    model = load_embedding_model()
    q_emb = embed_texts(model, [args.query], batch_size=1)[0]
    res = collection.query(
        query_embeddings=[q_emb],
        n_results=args.top_k,
        include=["documents", "metadatas", "distances"],
    )
    ids = res["ids"][0] if res["ids"] else []
    docs = res["documents"][0] if res["documents"] else []
    metas = res["metadatas"][0] if res["metadatas"] else []
    dists = res["distances"][0] if res["distances"] else []
    print(f"Запрос: {args.query!r}\n")
    for rank, (cid, doc, meta, dist) in enumerate(zip(ids, docs, metas, dists), start=1):
        src = meta.get("source_path", "?")
        title = meta.get("title", "")
        ci = meta.get("chunk_index", "")
        print(f"--- {rank}. id={cid}  distance={dist:.4f}")
        print(f"    source: {src}  title: {title}  chunk_index: {ci}")
        preview = doc.replace("\n", " ")[:320]
        print(f"    text: {preview}…\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="build_index.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="Проиндексировать markdown в ChromaDB")
    p_index.add_argument("--kb-dir", type=Path, default=DEFAULT_KB_DIR, help="Каталог с .md")
    p_index.add_argument("--chroma-dir", type=Path, default=DEFAULT_CHROMA_DIR, help="Персистентное хранилище Chroma")
    p_index.add_argument("--batch-size", type=int, default=16)
    p_index.add_argument("--reset", action="store_true", help="Удалить коллекцию перед загрузкой")
    p_index.set_defaults(func=cmd_index)

    p_q = sub.add_parser("query", help="Поиск по индексу")
    p_q.add_argument("query", type=str, help="Текст запроса")
    p_q.add_argument("--chroma-dir", type=Path, default=DEFAULT_CHROMA_DIR)
    p_q.add_argument("--top-k", type=int, default=5)
    p_q.set_defaults(func=cmd_query)

    args = parser.parse_args()
    if args.command == "index":
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    args.func(args)


if __name__ == "__main__":
    main()

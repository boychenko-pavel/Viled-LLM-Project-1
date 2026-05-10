from __future__ import annotations

import hashlib
import time
import re
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from openai import OpenAI
import requests

from sql_agent.config import (
    HR_OCR_LANGUAGES,
    HR_TESSERACT_CMD,
    LM_STUDIO_BASE_URL,
    LM_STUDIO_EMBEDDING_MODEL,
    LM_STUDIO_MANAGE_MODELS_DURING_EMBEDDING,
    MEMORY_DIR,
)
from sql_agent.langchain_factory import build_llm
from sql_agent.memory import SqlAgentMemory, SqlAgentMemoryRepository


HR_MEMORY_DIR = MEMORY_DIR / "hr"
HR_DOCUMENTS_DIR = HR_MEMORY_DIR / "documents"
HR_CHROMA_DIR = HR_MEMORY_DIR / "chroma"
HR_CHAT_MEMORY_FILE = HR_MEMORY_DIR / "chat_memory.json"


@dataclass(frozen=True)
class DocumentChunk:
    text: str
    source: str
    page: int
    chunk_index: int


@dataclass(frozen=True)
class LoadedLmStudioModel:
    instance_id: str
    model_id: str
    config: dict


class LmStudioModelManager:
    def __init__(self) -> None:
        self.api_base_url = LM_STUDIO_BASE_URL.removesuffix("/v1")

    @contextmanager
    def embedding_memory_window(self):
        if not LM_STUDIO_MANAGE_MODELS_DURING_EMBEDDING:
            yield
            return

        loaded_llms = self._loaded_llms()
        for model in loaded_llms:
            self._unload(model.instance_id)

        embedding_instance_id = self._load(LM_STUDIO_EMBEDDING_MODEL)
        try:
            yield
        finally:
            self._unload(embedding_instance_id, ignore_errors=True)
            for model in loaded_llms:
                self._load(model.model_id, model.config)

    def _loaded_llms(self) -> list[LoadedLmStudioModel]:
        response = requests.get(f"{self.api_base_url}/api/v1/models", timeout=30)
        response.raise_for_status()
        loaded = []
        for model in response.json().get("models", []):
            if model.get("type") != "llm":
                continue
            model_id = model.get("selected_variant") or model.get("key")
            if not model_id:
                continue
            for instance in model.get("loaded_instances", []):
                instance_id = instance.get("id")
                if not instance_id:
                    continue
                loaded.append(
                    LoadedLmStudioModel(
                        instance_id=instance_id,
                        model_id=model_id,
                        config=self._load_config(instance.get("config", {})),
                    )
                )
        return loaded

    def _load(self, model_id: str, config: dict | None = None) -> str:
        payload = {"model": model_id}
        if config:
            payload.update(config)
        response = requests.post(
            f"{self.api_base_url}/api/v1/models/load",
            json=payload,
            timeout=300,
        )
        response.raise_for_status()
        instance_id = str(response.json().get("instance_id") or model_id)
        self._wait_for_loaded(model_id)
        return instance_id

    def _unload(self, instance_id: str, ignore_errors: bool = False) -> None:
        response = requests.post(
            f"{self.api_base_url}/api/v1/models/unload",
            json={"instance_id": instance_id},
            timeout=120,
        )
        if ignore_errors and response.status_code in {400, 404, 409}:
            return
        response.raise_for_status()

    def _wait_for_loaded(self, model_id: str) -> None:
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if self._has_loaded_instance(model_id):
                return
            time.sleep(0.5)
        raise RuntimeError(f"LM Studio model was not loaded in time: {model_id}")

    def _has_loaded_instance(self, model_id: str) -> bool:
        response = requests.get(f"{self.api_base_url}/api/v1/models", timeout=30)
        response.raise_for_status()
        for model in response.json().get("models", []):
            identifiers = {
                value
                for value in [
                    model.get("key"),
                    model.get("selected_variant"),
                    *(model.get("variants") or []),
                ]
                if value
            }
            if model_id in identifiers and model.get("loaded_instances"):
                return True
        return False

    def _load_config(self, config: dict) -> dict:
        allowed_keys = {
            "context_length",
            "eval_batch_size",
            "parallel",
            "flash_attention",
            "num_experts",
            "offload_kv_cache_to_gpu",
        }
        return {key: value for key, value in config.items() if key in allowed_keys}


class LmStudioEmbeddings:
    def __init__(self) -> None:
        self.client = OpenAI(base_url=LM_STUDIO_BASE_URL, api_key="lm-studio")
        self.model_manager = LmStudioModelManager()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        with self.model_manager.embedding_memory_window():
            return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        with self.model_manager.embedding_memory_window():
            return self._embed([text])[0]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(
            model=LM_STUDIO_EMBEDDING_MODEL,
            input=texts,
        )
        return [item.embedding for item in response.data]


class HrAgent:
    def __init__(self) -> None:
        self.memory_repository = SqlAgentMemoryRepository(HR_CHAT_MEMORY_FILE)
        self.embeddings = LmStudioEmbeddings()
        self._lock = Lock()

    def ask(self, message: str) -> str:
        cleaned_message = message.strip()
        if not cleaned_message:
            raise ValueError("Message is empty.")

        with self._lock:
            collection = self._collection()
            if collection.count() == 0:
                return (
                    "В HR-памяти пока нет обработанных документов. "
                    "Загрузите PDF с положением о премировании и повторите вопрос."
                )

            query_embedding = self.embeddings.embed_query(cleaned_message)
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=5,
                include=["documents", "metadatas"],
            )
            context = self._format_context(results)
            if not context:
                return "В HR-памяти не найден релевантный фрагмент по этому вопросу."

            memory = self.memory_repository.load()
            prompt = self._build_prompt(memory, cleaned_message, context)
            response = build_llm().invoke(prompt)
            answer = getattr(response, "content", response)
            if isinstance(answer, list):
                answer = "\n".join(str(item) for item in answer)
            answer = str(answer).strip()
            memory.add_turn(cleaned_message, answer)
            self.memory_repository.save(memory)
            return answer

    def load_conversation(self) -> list[dict[str, str]]:
        return self.memory_repository.load().conversation

    def reset_memory(self) -> str:
        with self._lock:
            self.memory_repository.save(SqlAgentMemory())
            return "HR chat memory cleared. Document embeddings are preserved."

    def list_documents(self) -> list[dict[str, object]]:
        collection = self._collection()
        rows = collection.get(include=["metadatas"])
        documents: dict[str, dict[str, object]] = {}
        for metadata in rows.get("metadatas") or []:
            if not metadata:
                continue
            source = str(metadata.get("source") or "unknown")
            page = int(metadata.get("page") or 0)
            item = documents.setdefault(
                source,
                {
                    "source": source,
                    "chunk_count": 0,
                    "pages": set(),
                },
            )
            item["chunk_count"] = int(item["chunk_count"]) + 1
            if page:
                item["pages"].add(page)

        result = []
        for item in documents.values():
            pages = sorted(item["pages"])
            result.append(
                {
                    "source": item["source"],
                    "chunk_count": item["chunk_count"],
                    "pages": pages,
                    "page_count": len(pages),
                }
            )
        return sorted(result, key=lambda item: str(item["source"]).lower())

    def list_chunks(self, source: str | None = None, limit: int = 100) -> list[dict[str, object]]:
        where = {"source": source} if source else None
        rows = self._collection().get(
            where=where,
            limit=max(1, min(limit, 500)),
            include=["documents", "metadatas"],
        )
        return self._format_chunk_rows(rows)

    def search_memory(self, query: str, limit: int = 10) -> list[dict[str, object]]:
        cleaned_query = query.strip()
        if not cleaned_query:
            return []

        collection = self._collection()
        if collection.count() == 0:
            return []

        query_embedding = self.embeddings.embed_query(cleaned_query)
        rows = collection.query(
            query_embeddings=[query_embedding],
            n_results=max(1, min(limit, 25)),
            include=["documents", "metadatas", "distances"],
        )
        return self._format_search_rows(rows)

    def ingest_pdf(self, source_file: Path) -> str:
        if source_file.suffix.lower() != ".pdf":
            raise ValueError("HR memory accepts PDF files only.")

        with self._lock:
            HR_DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
            target_file = self._unique_document_path(source_file.name)
            shutil.copy2(source_file, target_file)

            chunks = self._read_pdf_chunks(target_file)
            if not chunks:
                target_file.unlink(missing_ok=True)
                raise ValueError(
                    "PDF text was not found. The PDF likely contains scanned pages. "
                    "Install Tesseract OCR with Russian language data and try again."
                )

            texts = [chunk.text for chunk in chunks]
            vectors = self.embeddings.embed_documents(texts)
            ids = [
                self._chunk_id(chunk.source, chunk.page, chunk.chunk_index, chunk.text)
                for chunk in chunks
            ]
            metadatas = [
                {
                    "source": chunk.source,
                    "page": chunk.page,
                    "chunk_index": chunk.chunk_index,
                }
                for chunk in chunks
            ]

            self._collection().add(
                ids=ids,
                documents=texts,
                metadatas=metadatas,
                embeddings=vectors,
            )
            return f"PDF processed: {target_file.name}. Added chunks: {len(chunks)}."

    def _collection(self):
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError("Install chromadb to use HR document memory.") from exc

        HR_CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(HR_CHROMA_DIR))
        return client.get_or_create_collection(name="hr_bonus_policies")

    def _read_pdf_chunks(self, pdf_path: Path) -> list[DocumentChunk]:
        chunks = self._read_pdf_text_chunks(pdf_path)
        if chunks:
            return chunks
        return self._read_pdf_ocr_chunks(pdf_path)

    def _read_pdf_text_chunks(self, pdf_path: Path) -> list[DocumentChunk]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("Install pypdf to process HR PDF documents.") from exc

        reader = PdfReader(str(pdf_path))
        chunks: list[DocumentChunk] = []
        for page_index, page in enumerate(reader.pages, start=1):
            text = self._normalize_text(page.extract_text() or "")
            for chunk_index, chunk_text in enumerate(self._split_text(text), start=1):
                chunks.append(
                    DocumentChunk(
                        text=chunk_text,
                        source=pdf_path.name,
                        page=page_index,
                        chunk_index=chunk_index,
                    )
                )
        return chunks

    def _read_pdf_ocr_chunks(self, pdf_path: Path) -> list[DocumentChunk]:
        try:
            import fitz
            import pytesseract
            from PIL import Image
            from pytesseract import TesseractNotFoundError
        except ImportError as exc:
            raise RuntimeError(
                "Install PyMuPDF and pytesseract to process scanned HR PDF documents."
            ) from exc

        if HR_TESSERACT_CMD.exists():
            pytesseract.pytesseract.tesseract_cmd = str(HR_TESSERACT_CMD)
        ocr_languages = self._available_ocr_languages(pytesseract)

        chunks: list[DocumentChunk] = []
        try:
            document = fitz.open(pdf_path)
            for page_index, page in enumerate(document, start=1):
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                text = self._normalize_text(
                    pytesseract.image_to_string(image, lang=ocr_languages)
                )
                for chunk_index, chunk_text in enumerate(self._split_text(text), start=1):
                    chunks.append(
                        DocumentChunk(
                            text=chunk_text,
                            source=pdf_path.name,
                            page=page_index,
                            chunk_index=chunk_index,
                        )
                    )
        except TesseractNotFoundError as exc:
            raise ValueError(
                "Scanned PDF requires Tesseract OCR. Install Tesseract and make sure "
                "tesseract.exe is available in PATH."
            ) from exc
        except RuntimeError as exc:
            message = str(exc)
            if "Failed loading language" in message or "Error opening data file" in message:
                raise ValueError(
                    f"Tesseract OCR language data is missing for '{HR_OCR_LANGUAGES}'. "
                    "Install Russian and English language data or change HR_OCR_LANGUAGES."
                ) from exc
            raise
        finally:
            if "document" in locals():
                document.close()

        return chunks

    def _available_ocr_languages(self, pytesseract_module) -> str:
        requested = [language for language in HR_OCR_LANGUAGES.split("+") if language]
        try:
            installed = set(pytesseract_module.get_languages(config=""))
        except Exception:
            return HR_OCR_LANGUAGES

        available = [language for language in requested if language in installed]
        if available:
            return "+".join(available)
        if "eng" in installed:
            return "eng"
        raise ValueError(
            f"Tesseract OCR language data is missing for '{HR_OCR_LANGUAGES}'. "
            "Install Russian and English language data or change HR_OCR_LANGUAGES."
        )

    def _split_text(self, text: str, chunk_size: int = 1200, overlap: int = 180) -> list[str]:
        if not text:
            return []

        chunks = []
        start = 0
        while start < len(text):
            end = min(len(text), start + chunk_size)
            if end < len(text):
                boundary = text.rfind(". ", start, end)
                if boundary > start + chunk_size // 2:
                    end = boundary + 1
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start = max(end - overlap, start + 1)
        return chunks

    def _build_prompt(self, memory: SqlAgentMemory, question: str, context: str) -> str:
        history_lines = []
        for item in memory.conversation[-8:]:
            role = item.get("role", "user").upper()
            content = item.get("content", "")
            history_lines.append(f"{role}: {content}")
        history = "\n".join(history_lines) if history_lines else "No prior conversation."
        return (
            "You are HR, a company HR policy assistant. "
            "Answer in Russian unless the user asks otherwise. "
            "Use only the provided HR document context about company bonus policies. "
            "If the context does not contain the answer, say that the available HR documents do not contain it. "
            "When possible, cite the source file and page.\n\n"
            f"Conversation history:\n{history}\n\n"
            f"HR document context:\n{context}\n\n"
            f"User question:\n{question}"
        )

    def _format_context(self, results: dict) -> str:
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        lines = []
        for index, document in enumerate(documents, start=1):
            metadata = metadatas[index - 1] if index - 1 < len(metadatas) else {}
            source = metadata.get("source", "unknown")
            page = metadata.get("page", "?")
            lines.append(f"[{index}] Source: {source}, page: {page}\n{document}")
        return "\n\n".join(lines)

    def _format_chunk_rows(self, rows: dict) -> list[dict[str, object]]:
        ids = rows.get("ids") or []
        documents = rows.get("documents") or []
        metadatas = rows.get("metadatas") or []
        chunks = []
        for index, document in enumerate(documents):
            metadata = metadatas[index] if index < len(metadatas) and metadatas[index] else {}
            chunks.append(
                {
                    "id": ids[index] if index < len(ids) else "",
                    "source": metadata.get("source", "unknown"),
                    "page": metadata.get("page"),
                    "chunk_index": metadata.get("chunk_index"),
                    "text": document,
                }
            )
        return sorted(
            chunks,
            key=lambda item: (
                str(item.get("source") or ""),
                int(item.get("page") or 0),
                int(item.get("chunk_index") or 0),
            ),
        )

    def _format_search_rows(self, rows: dict) -> list[dict[str, object]]:
        ids = (rows.get("ids") or [[]])[0]
        documents = (rows.get("documents") or [[]])[0]
        metadatas = (rows.get("metadatas") or [[]])[0]
        distances = (rows.get("distances") or [[]])[0]
        chunks = []
        for index, document in enumerate(documents):
            metadata = metadatas[index] if index < len(metadatas) and metadatas[index] else {}
            distance = distances[index] if index < len(distances) else None
            chunks.append(
                {
                    "id": ids[index] if index < len(ids) else "",
                    "source": metadata.get("source", "unknown"),
                    "page": metadata.get("page"),
                    "chunk_index": metadata.get("chunk_index"),
                    "distance": distance,
                    "text": document,
                }
            )
        return chunks

    def _unique_document_path(self, filename: str) -> Path:
        safe_name = re.sub(r"[^A-Za-z0-9_. -]+", "_", Path(filename).name).strip()
        if not safe_name:
            safe_name = "hr_document.pdf"
        candidate = HR_DOCUMENTS_DIR / safe_name
        if not candidate.exists():
            return candidate
        stem = candidate.stem
        suffix = candidate.suffix
        index = 2
        while True:
            candidate = HR_DOCUMENTS_DIR / f"{stem}_{index}{suffix}"
            if not candidate.exists():
                return candidate
            index += 1

    def _chunk_id(self, source: str, page: int, chunk_index: int, text: str) -> str:
        digest = hashlib.sha1(f"{source}:{page}:{chunk_index}:{text}".encode("utf-8")).hexdigest()
        return f"{source}:{page}:{chunk_index}:{digest[:12]}"

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

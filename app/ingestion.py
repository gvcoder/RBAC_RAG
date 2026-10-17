import os
import pypdf
from typing import List, Tuple
from openai import OpenAI
from app.config import OPENAI_API_KEY, OPENAI_EMBEDDING_MODEL, UPLOAD_DIR
from app.db import get_session, Document, DocumentChunk

def get_openai_client():
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not configured in .env")
    return OpenAI(api_key=OPENAI_API_KEY)

def extract_text_from_file(file_path: str, file_type: str) -> str:
    """Extract raw text from PDF or TXT files."""
    if file_type.lower() == "pdf":
        reader = pypdf.PdfReader(file_path)
        text = ""
        for page in reader.pages:
            content = page.extract_text()
            if content:
                text += content + "\n"
        return text
    elif file_type.lower() == "txt":
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    else:
        raise ValueError(f"Unsupported file type: {file_type}")

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """Simple sliding-window character chunking respecting paragraph breaks where possible."""
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk.strip():
            chunks.append(chunk.strip())
        i += (chunk_size - overlap)
    return chunks

def generate_embeddings(texts: List[str]) -> List[List[float]]:
    """Compute embeddings using OpenAI text-embedding-3-small."""
    client = get_openai_client()
    # Batch if necessary
    all_embeddings = []
    batch_size = 64
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        res = client.embeddings.create(input=batch, model=OPENAI_EMBEDDING_MODEL)
        all_embeddings.extend([item.embedding for item in res.data])
    return all_embeddings

def index_document(document_id: int) -> Tuple[bool, str]:
    """Extract, chunk, embed, and store document chunks in PGVector."""
    session = get_session()
    try:
        doc = session.query(Document).filter(Document.id == document_id).first()
        if not doc:
            return False, "Document not found"

        file_path = os.path.join(UPLOAD_DIR, doc.filename)
        if not os.path.exists(file_path):
            return False, f"File {doc.filename} missing on disk"

        text = extract_text_from_file(file_path, doc.file_type)
        if not text.strip():
            return False, "Extracted text is empty"

        chunks = chunk_text(text)
        if not chunks:
            return False, "No chunks generated from document"

        embeddings = generate_embeddings(chunks)

        # Clear any prior chunks for this doc
        session.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete()

        # Insert new chunks
        for idx, (content, emb) in enumerate(zip(chunks, embeddings)):
            chunk_record = DocumentChunk(
                document_id=doc.id,
                chunk_index=idx,
                content=content,
                access_role=doc.access_role,
                embedding=emb
            )
            session.add(chunk_record)

        doc.is_indexed = True
        doc.chunk_count = len(chunks)
        session.commit()
        return True, f"Successfully indexed {len(chunks)} chunks."
    except Exception as e:
        session.rollback()
        return False, str(e)
    finally:
        session.close()

def reindex_all_documents() -> Tuple[int, List[str]]:
    """Re-index all documents marked in the database."""
    session = get_session()
    results = []
    indexed_count = 0
    try:
        docs = session.query(Document).all()
        for doc in docs:
            success, msg = index_document(doc.id)
            if success:
                indexed_count += 1
            results.append(f"{doc.original_name}: {msg}")
        return indexed_count, results
    finally:
        session.close()

def delete_document(document_id: int) -> Tuple[bool, str]:
    """Delete a document, cascade delete its vector embeddings, and remove physical file."""
    session = get_session()
    try:
        doc = session.query(Document).filter(Document.id == document_id).first()
        if not doc:
            return False, "Document not found"

        file_path = os.path.join(UPLOAD_DIR, doc.filename)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Warning: could not delete file from disk: {e}")

        # SQLAlchemy cascade takes care of document_chunks
        session.delete(doc)
        session.commit()
        return True, "Document and vector embeddings deleted successfully."
    except Exception as e:
        session.rollback()
        return False, str(e)
    finally:
        session.close()

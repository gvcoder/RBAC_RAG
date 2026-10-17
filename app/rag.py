from typing import List, Dict, Any
from app.config import OPENAI_CHAT_MODEL, OPENAI_EMBEDDING_MODEL
from app.db import get_session, DocumentChunk, Document
from app.ingestion import get_openai_client

def get_allowed_roles_for_user(user_role: str) -> List[str]:
    """
    RBAC Rules:
    - Admin: can access both 'HR_ONLY' and 'HR_AND_EMPLOYEE'
    - HR: can access both 'HR_ONLY' and 'HR_AND_EMPLOYEE'
    - Employee: can ONLY access 'HR_AND_EMPLOYEE'
    """
    role = user_role.upper()
    if role in ["ADMIN", "HR"]:
        return ["HR_ONLY", "HR_AND_EMPLOYEE"]
    elif role == "EMPLOYEE":
        return ["HR_AND_EMPLOYEE"]
    return []

def retrieve_relevant_chunks(query: str, user_role: str, top_k: int = 4) -> List[Dict[str, Any]]:
    """Retrieve top-k chunks from PGVector filtered strictly by user role."""
    allowed_roles = get_allowed_roles_for_user(user_role)
    if not allowed_roles:
        return []

    client = get_openai_client()
    query_res = client.embeddings.create(input=[query], model=OPENAI_EMBEDDING_MODEL)
    query_emb = query_res.data[0].embedding

    session = get_session()
    try:
        # Perform cosine distance search in PGVector with role filtering
        # l2_distance or cosine_distance: <=> is cosine distance in pgvector
        results = (
            session.query(
                DocumentChunk,
                Document.original_name,
                DocumentChunk.embedding.cosine_distance(query_emb).label("distance")
            )
            .join(Document, DocumentChunk.document_id == Document.id)
            .filter(DocumentChunk.access_role.in_(allowed_roles))
            .order_by("distance")
            .limit(top_k)
            .all()
        )

        chunks_data = []
        for chunk, doc_name, dist in results:
            chunks_data.append({
                "chunk_id": chunk.id,
                "document_name": doc_name,
                "access_role": chunk.access_role,
                "content": chunk.content,
                "distance": float(dist)
            })
        return chunks_data
    finally:
        session.close()

def generate_rag_response(query: str, user_role: str, chat_history: List[Dict[str, str]] = None) -> Dict[str, Any]:
    """Generate answer using retrieved role-filtered context and OpenAI LLM."""
    retrieved_chunks = retrieve_relevant_chunks(query, user_role, top_k=4)

    if not retrieved_chunks:
        context_str = "No relevant documents found with your current access permissions."
    else:
        context_parts = []
        for i, c in enumerate(retrieved_chunks):
            context_parts.append(
                f"[Source {i+1}: {c['document_name']} | Access Tag: {c['access_role']}]\n{c['content']}"
            )
        context_str = "\n\n---\n\n".join(context_parts)

    system_prompt = (
        f"You are a helpful and secure enterprise AI assistant with Role-Based Access Control (RBAC).\n"
        f"The current user's role is: {user_role}.\n"
        f"Strictly adhere to the following rules:\n"
        f"1. Base your answers on the provided context retrieved from authorized documents.\n"
        f"2. If the user asks about information outside their access role (e.g. an Employee asking about HR-only salary data or appraisal scores), "
        f"politely inform them that they do not have sufficient permissions to view that information or that no authorized documents contain it.\n"
        f"3. Always cite the document name when providing factual answers.\n\n"
        f"Retrieved Documents Context:\n{context_str}"
    )

    messages = [{"role": "system", "content": system_prompt}]
    if chat_history:
        # Keep recent 6 messages
        for msg in chat_history[-6:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": query})

    client = get_openai_client()
    completion = client.chat.completions.create(
        model=OPENAI_CHAT_MODEL,
        messages=messages,
        temperature=0.2
    )

    answer = completion.choices[0].message.content

    return {
        "answer": answer,
        "sources": retrieved_chunks
    }

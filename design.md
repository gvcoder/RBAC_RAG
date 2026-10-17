# Enterprise RBAC RAG System — Technical Design Document

## 1. System Overview

This application implements an **enterprise-grade Retrieval-Augmented Generation (RAG)** pipeline protected by **strict Role-Based Access Control (RBAC)** at the database query layer. 

The primary business goal is to prevent data exfiltration across organizational boundaries:
- **HR-only** confidential documents (salaries, appraisals, PIPs, bonuses) are completely shielded from general employees.
- **HR & Employee** documents (leave policies, company handbook, dress code, holidays) are accessible to both HR and Employees.
- **Admins** have administrative ingestion authority (uploading, tagging, re-indexing, cascading deletion) as well as full chat access.

---

## 2. High-Level Architecture

```
               ┌────────────────────────────────────────────────────────┐
               │                     Streamlit UI                       │
               │  ┌──────────────────────┐    ┌──────────────────────┐  │
               │  │     Admin Portal     │    │   Role-Aware Chat    │  │
               │  │ (Upload/Tag/Reindex) │    │  (Role Context + Cit)│  │
               │  └──────────┬───────────┘    └──────────┬───────────┘  │
               └─────────────┼───────────────────────────┼──────────────┘
                             │                           │
                             ▼                           ▼
                   ┌──────────────────┐        ┌──────────────────┐
                   │ Ingestion Engine │        │   RAG Pipeline   │
                   │  (app/ingestion) │        │    (app/rag)     │
                   └─────────┬────────┘        └─────────┬────────┘
                             │ Chunk & Embed             │ RBAC-filtered
                             │ (OpenAI 1536-dim)         │ Cosine Search
                             ▼                           ▼
        ┌─────────────────────────────────────────────────────────────────┐
        │                 PostgreSQL + PGVector Database                  │
        │                                                                 │
        │  ┌───────────────┐     ┌───────────────┐     ┌───────────────┐  │
        │  │     users     │     │   documents   │     │document_chunks│  │
        │  │(Email, Role,  │     │(Access Tag,   │◄────┤(Vector(1536), │  │
        │  │ Bcrypt Hash)  │     │ Status, Type) │  C  │ Role Tag,     │  │
        │  └───────────────┘     └───────────────┘  A  │ Chunk Text)   │  │
        │                                           S  └───────────────┘  │
        │                                           C                     │
        │                                           A                     │
        │                                           D                     │
        │                                           E                     │
        └─────────────────────────────────────────────────────────────────┘
```

---

## 3. RBAC Security Model

### 3.1 Role Hierarchy & Document Access Matrix

| User Role | Can Access Admin Portal? | Accessible Document Tags | Example Documents Accessible |
|---|---|---|---|
| **Admin** | Yes | `HR_ONLY`, `HR_AND_EMPLOYEE` | All company records & policies |
| **HR** | No | `HR_ONLY`, `HR_AND_EMPLOYEE` | Salaries, Appraisals, Employee Handbooks, Leave Policies |
| **Employee** | No | `HR_AND_EMPLOYEE` only | Leave Policies, Code of Conduct, Dress Code |

### 3.2 Security Enforcement Points

1. **Query-Level Vector Filtering (Deterministic, Non-Bypassable)**:
   Unlike naive solutions that retrieve chunks and prompt the LLM to "ignore confidential text", this architecture enforces access control **inside the PostgreSQL SQL engine** using standard `WHERE ... IN (...)` filtering:

   ```sql
   SELECT dc.id, dc.content, d.original_name, (dc.embedding <=> :query_emb) AS distance
   FROM document_chunks dc
   JOIN documents d ON dc.document_id = d.id
   WHERE dc.access_role IN ('HR_AND_EMPLOYEE')  -- Filtered based on active session role
   ORDER BY distance ASC
   LIMIT 4;
   ```
   **Security guarantee**: An Employee's query embedding is mathematically never compared against or returned alongside `HR_ONLY` records. The LLM prompt never sees unauthorized chunks.

2. **System Prompt Guardrails**:
   A secondary guardrail prompts the model to politely explain permission boundaries if a user attempts to elicit restricted data.

---

## 4. Component Deep Dive

### 4.1 Database Layer (`app/db.py`)

Using `SQLAlchemy 2.0` and `pgvector.sqlalchemy.Vector`:

- **`users` Table**:
  - `id`: Auto-incrementing primary key.
  - `email`: Indexed, unique company email address.
  - `password_hash`: Salted bcrypt hash string.
  - `role`: Enum/String: `'Admin'`, `'HR'`, `'Employee'`.
  
- **`documents` Table**:
  - `id`: Primary key.
  - `filename`: Unique filesystem name (`<uuid>_<original_name>`).
  - `original_name`: Display name.
  - `file_type`: `'pdf'` or `'txt'`.
  - `access_role`: `'HR_ONLY'` or `'HR_AND_EMPLOYEE'`.
  - `is_indexed`: Boolean flag.
  - `chunk_count`: Number of extracted chunks.

- **`document_chunks` Table**:
  - `id`: Primary key.
  - `document_id`: Foreign key to `documents.id` with `ON DELETE CASCADE`.
  - `chunk_index`: Integer ordering within the original document.
  - `content`: Plaintext chunk.
  - `access_role`: Denormalized role tag (`HR_ONLY` or `HR_AND_EMPLOYEE`) for low-latency indexed filtering.
  - `embedding`: `Vector(1536)` column for OpenAI's `text-embedding-3-small`.

---

### 4.2 Ingestion & Processing Pipeline (`app/ingestion.py`)

1. **Extraction**:
   - `pypdf.PdfReader` iterates over pages for PDF files.
   - Standard UTF-8 streaming reader for TXT files.
2. **Chunking**:
   - Configured with a default chunk size of 500 words with a 50-word sliding-window overlap.
3. **Embedding Generation**:
   - Batched calls to OpenAI API using `text-embedding-3-small`.
4. **Vector Storage**:
   - Inserted with document foreign key and access role.
5. **Immediate Deletion & Re-indexing Invariant**:
   - When a file is removed via `delete_document(id)`, the physical file is deleted, and SQLAlchemy issues a `CASCADE` delete on `document_chunks`.
   - Re-indexing drops all existing chunks for that document and repopulates fresh embeddings.

---

### 4.3 RAG Retrieval & Prompt Assembly (`app/rag.py`)

1. **Query Embedding**:
   - The user's input query is passed to `text-embedding-3-small`.
2. **Role Filter Resolution**:
   - Role `'Admin'` $\rightarrow$ `['HR_ONLY', 'HR_AND_EMPLOYEE']`
   - Role `'HR'` $\rightarrow$ `['HR_ONLY', 'HR_AND_EMPLOYEE']`
   - Role `'Employee'` $\rightarrow$ `['HR_AND_EMPLOYEE']`
3. **Similarity Calculation**:
   - `DocumentChunk.embedding.cosine_distance(query_emb)` computes the cosine distance ($\Leftrightarrow$ operator in pgvector).
   - Top-$k$ chunks (default: 4) are selected.
4. **LLM Synthesis**:
   - Retrieved chunks are formatted with `[Source: <filename> | Access Tag: <tag>]` metadata.
   - Pushed into `gpt-4o` with a 6-message sliding conversation history.

---

### 4.4 Authentication & Session State (`app/auth.py` & `main.py`)

- **Bcrypt Password Security**: Passwords are never stored in plaintext (`bcrypt.hashpw` with per-user salt).
- **Streamlit Session State**:
  - Authenticated session is stored in `st.session_state.user = {"id": ..., "email": ..., "role": ...}`.
  - Automatic seed accounts created on first startup:
    - `admin@company.com` / `Admin@123` (Admin)
    - `hr@company.com` / `HR@123` (HR)
    - `employee@company.com` / `Emp@123` (Employee)
- **Role Routing**:
  - Admin users are given sidebar access to the **Admin Document Portal**.
  - Non-admin users are restricted to the **Chat Assistant**.

---

## 5. Directory Structure

```
RBAC_RAG/
├── app/
│   ├── __init__.py
│   ├── auth.py              # Password hashing, verification, user seed
│   ├── config.py            # Environment configurations (.env)
│   ├── db.py                # Database models (User, Document, DocumentChunk) & PGVector init
│   ├── ingestion.py         # PDF/TXT extraction, chunking, OpenAI embeddings, indexing
│   ├── rag.py               # Role-based vector search & gpt-4o RAG pipeline
│   └── ui/
│       ├── __init__.py
│       ├── admin_view.py    # Admin file upload, tagging, manual indexing & file deletion
│       └── chat_view.py     # Chat UI with citations, distance scores, and role pills
├── uploaded_files/          # Local storage for raw uploaded PDFs and TXTs
├── .env                     # Database credentials & OpenAI API key
├── .env.example             # Template for environment variables
├── requirements.txt         # Project dependencies
├── design.md                # System technical design document (this file)
└── main.py                  # Entrypoint Streamlit script
```

---

## 6. How to Run

1. **Activate Virtual Environment**:
   ```bash
   source .venv/bin/activate
   ```
2. **Start PostgreSQL**:
   Ensure PostgreSQL is running with the `vector` extension:
   ```bash
   sudo systemctl status postgresql
   ```
3. **Start the Application**:
   ```bash
   streamlit run main.py
   ```
4. **Verify RBAC Flow**:
   - Log in as **Admin** (`admin@company.com` / `Admin@123`).
   - Upload a test file with `HR_ONLY` (e.g., `salaries.txt`) and index it.
   - Upload a test file with `HR_AND_EMPLOYEE` (e.g., `leave_policy.txt`) and index it.
   - Log out and log in as **Employee** (`employee@company.com` / `Emp@123`).
   - Query: *"What is the salary structure?"* $\rightarrow$ The Employee receives a response stating that no authorized information exists.
   - Query: *"What is the leave policy?"* $\rightarrow$ The Employee receives an accurate answer citing `leave_policy.txt`.

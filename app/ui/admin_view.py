import os
import uuid
import streamlit as st
from app.config import UPLOAD_DIR
from app.db import get_session, Document
from app.ingestion import index_document, reindex_all_documents, delete_document

def render_admin_view():
    st.header("⚙️ Admin Management & Ingestion Portal")
    st.markdown("Upload documents, assign Role-Based Access tags, manually trigger indexing, or remove files.")

    tab1, tab2 = st.tabs(["📤 Upload & Tag Document", "📑 Manage Stored Documents"])

    with tab1:
        st.subheader("Upload New Document (PDF or TXT)")
        uploaded_file = st.file_uploader("Choose a file", type=["pdf", "txt"])
        
        col1, col2 = st.columns(2)
        with col1:
            access_tag = st.selectbox(
                "Access Control Permission:",
                options=["HR_ONLY", "HR_AND_EMPLOYEE"],
                format_func=lambda x: "🔒 HR Only (Confidential: Salaries, Appraisals)" if x == "HR_ONLY" else "👥 HR & Employee (General: Leaves, Policy, Handbook)"
            )
        with col2:
            auto_index = st.checkbox("Trigger indexing immediately after upload", value=True)

        if st.button("Save & Process File", type="primary", disabled=uploaded_file is None):
            if uploaded_file:
                # Save file to disk
                file_ext = uploaded_file.name.split(".")[-1].lower()
                unique_filename = f"{uuid.uuid4().hex}_{uploaded_file.name}"
                save_path = os.path.join(UPLOAD_DIR, unique_filename)
                
                with open(save_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

                session = get_session()
                try:
                    new_doc = Document(
                        filename=unique_filename,
                        original_name=uploaded_file.name,
                        file_type=file_ext,
                        access_role=access_tag,
                        is_indexed=False,
                        chunk_count=0
                    )
                    session.add(new_doc)
                    session.commit()
                    doc_id = new_doc.id

                    st.success(f"File '{uploaded_file.name}' stored successfully with tag '{access_tag}'.")

                    if auto_index:
                        with st.spinner("Extracting text and indexing into PGVector..."):
                            success, msg = index_document(doc_id)
                            if success:
                                st.success(f"Indexing complete: {msg}")
                            else:
                                st.error(f"Indexing error: {msg}")
                except Exception as e:
                    st.error(f"Error saving document: {e}")
                finally:
                    session.close()

    with tab2:
        st.subheader("Current Document Catalog")
        
        col_btn1, col_btn2 = st.columns([2, 5])
        with col_btn1:
            if st.button("🔄 Manually Re-Index All Files", type="secondary"):
                with st.spinner("Re-indexing all documents into PGVector..."):
                    count, logs = reindex_all_documents()
                    st.success(f"Re-indexed {count} document(s) successfully.")
                    with st.expander("Detailed Indexing Logs"):
                        for l in logs:
                            st.write(l)

        session = get_session()
        try:
            docs = session.query(Document).order_by(Document.uploaded_at.desc()).all()
            if not docs:
                st.info("No documents uploaded yet.")
            else:
                for doc in docs:
                    with st.container(border=True):
                        c1, c2, c3, c4, c5 = st.columns([3, 2, 2, 2, 2])
                        with c1:
                            st.write(f"📄 **{doc.original_name}**")
                            st.caption(f"Uploaded: {doc.uploaded_at.strftime('%Y-%m-%d %H:%M')}")
                        with c2:
                            badge_color = "red" if doc.access_role == "HR_ONLY" else "blue"
                            st.markdown(f":{badge_color}[**{doc.access_role}**]")
                        with c3:
                            if doc.is_indexed:
                                st.success(f"Indexed ({doc.chunk_count} chunks)")
                            else:
                                st.warning("Not Indexed")
                        with c4:
                            if st.button("Index Now", key=f"idx_{doc.id}"):
                                with st.spinner(f"Indexing {doc.original_name}..."):
                                    ok, msg = index_document(doc.id)
                                    if ok:
                                        st.success(msg)
                                        st.rerun()
                                    else:
                                        st.error(msg)
                        with c5:
                            if st.button("🗑️ Delete", key=f"del_{doc.id}", type="primary"):
                                with st.spinner(f"Deleting {doc.original_name}..."):
                                    ok, msg = delete_document(doc.id)
                                    if ok:
                                        st.success("Deleted from database and vector index.")
                                        st.rerun()
                                    else:
                                        st.error(msg)
        finally:
            session.close()

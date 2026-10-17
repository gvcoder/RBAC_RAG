import streamlit as st
from app.rag import generate_rag_response

def render_chat_view(user: dict):
    user_role = user.get("role", "Employee")
    email = user.get("email", "")

    st.header("💬 Role-Aware Knowledge Assistant")
    
    # Visual role pill
    if user_role == "Admin":
        st.markdown(f"Logged in as **{email}** (`{user_role}`) — 🔑 **Unrestricted Access**")
    elif user_role == "HR":
        st.markdown(f"Logged in as **{email}** (`{user_role}`) — 🔒 **HR Only & General Documents**")
    else:
        st.markdown(f"Logged in as **{email}** (`{user_role}`) — 👥 **HR & Employee (General) Only**")

    st.divider()

    # Session state for chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Display chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if "sources" in msg and msg["sources"]:
                with st.expander("📚 Retrieved Knowledge Sources"):
                    for s in msg["sources"]:
                        st.markdown(
                            f"- **{s['document_name']}** (Role tag: `{s['access_role']}`, Distance: `{s['distance']:.3f}`)"
                        )
                        st.caption(f"Preview: {s['content'][:180]}...")

    # Chat input
    if prompt := st.chat_input("Ask a question based on your authorized documents..."):
        # Append user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Assistant response
        with st.chat_message("assistant"):
            with st.spinner("Searching role-filtered knowledge base..."):
                try:
                    result = generate_rag_response(
                        query=prompt,
                        user_role=user_role,
                        chat_history=st.session_state.messages[:-1]
                    )
                    answer = result["answer"]
                    sources = result["sources"]

                    st.markdown(answer)
                    if sources:
                        with st.expander("📚 Retrieved Knowledge Sources"):
                            for s in sources:
                                st.markdown(
                                    f"- **{s['document_name']}** (Role tag: `{s['access_role']}`, Distance: `{s['distance']:.3f}`)"
                                )
                                st.caption(f"Preview: {s['content'][:180]}...")

                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": answer,
                        "sources": sources
                    })
                except Exception as e:
                    st.error(f"Failed to generate answer: {e}")

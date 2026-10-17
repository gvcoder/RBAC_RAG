import streamlit as st
from app.db import init_db
from app.auth import authenticate_user, seed_default_users, create_user
from app.ui.admin_view import render_admin_view
from app.ui.chat_view import render_chat_view

st.set_page_config(
    page_title="Enterprise RBAC RAG",
    page_icon="🛡️",
    layout="wide"
)

# Initialize Database and default seed users
try:
    init_db()
    seed_default_users()
except Exception as e:
    st.error(
        f"Database connection error: {e}\n\n"
        f"Please check your database configuration in `.env` (DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD)."
    )

# Manage session state for authentication
if "user" not in st.session_state:
    st.session_state.user = None

def login_form():
    st.title("🛡️ Enterprise RBAC RAG System")
    st.subheader("Sign In")

    col1, col2 = st.columns([1, 1])

    with col1:
        tab_login, tab_register = st.tabs(["Sign In", "Create Account"])

        with tab_login:
            email = st.text_input("Email", placeholder="admin@company.com")
            password = st.text_input("Password", type="password")
            role = st.selectbox("Role", ["Admin", "HR", "Employee"])

            if st.button("Log In", type="primary"):
                user = authenticate_user(email, password, expected_role=role)
                if user:
                    st.session_state.user = user
                    st.success(f"Logged in as {user['email']} ({user['role']})")
                    st.rerun()
                else:
                    st.error("Invalid credentials or role selection.")

        with tab_register:
            reg_email = st.text_input("New Email", placeholder="user@company.com", key="reg_email")
            reg_password = st.text_input("New Password", type="password", key="reg_pwd")
            reg_role = st.selectbox("Role to assign", ["HR", "Employee"], key="reg_role")

            if st.button("Register User", type="secondary"):
                if not reg_email or not reg_password:
                    st.warning("Please fill in both email and password.")
                else:
                    ok, msg = create_user(reg_email, reg_password, reg_role)
                    if ok:
                        st.success("User registered successfully! You can now log in.")
                    else:
                        st.error(f"Registration failed: {msg}")

    with col2:
        st.info(
            """
            **Default Seed Credentials:**
            - **Admin**: `admin@company.com` / `Admin@123` (Role: Admin)
            - **HR**: `hr@company.com` / `HR@123` (Role: HR)
            - **Employee**: `employee@company.com` / `Emp@123` (Role: Employee)

            ---
            **RBAC Rules:**
            - **Admin**: Can access Admin portal (upload, tag, delete, reindex) & Chat.
            - **HR**: Can access HR-Only files (salaries, appraisals) AND Employee general files.
            - **Employee**: Can ONLY access general files (leaves, policies). HR-Only data is completely excluded from vector search and retrieval.
            """
        )

def main():
    if not st.session_state.user:
        login_form()
        return

    user = st.session_state.user

    # Sidebar Navigation & User Info
    with st.sidebar:
        st.markdown(f"### 👤 {user['email']}")
        st.markdown(f"**Role:** `{user['role']}`")
        st.divider()

        # Navigation based on role
        if user["role"] == "Admin":
            nav_choice = st.radio("Navigation", ["💬 Chat Assistant", "⚙️ Admin Document Portal"])
        else:
            nav_choice = "💬 Chat Assistant"

        st.divider()
        if st.button("🚪 Log Out"):
            st.session_state.user = None
            st.session_state.messages = []
            st.rerun()

    # Route views
    if nav_choice == "⚙️ Admin Document Portal" and user["role"] == "Admin":
        render_admin_view()
    else:
        render_chat_view(user)

if __name__ == "__main__":
    main()

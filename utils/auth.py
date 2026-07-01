import smtplib
from email.message import EmailMessage
import secrets
import string
import os
import json
import tempfile
import logging
import hashlib
import re
import pandas as pd
import streamlit as st
from utils.data_loader import load_saved_recipes, safe_save_json, RECIPES_JSON_PATH

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USERS_JSON_PATH = os.path.join(BASE_DIR, "usuarios.json")

def get_default_admin_password():
    admin_pass = os.environ.get("ADMIN_PASSWORD")
    if not admin_pass:
        try:
            admin_pass = st.secrets.get("ADMIN_PASSWORD")
        except Exception:
            pass
    if admin_pass:
        return admin_pass
        
    admin_pwd_file = os.path.join(BASE_DIR, ".admin_password")
    if os.path.exists(admin_pwd_file):
        try:
            with open(admin_pwd_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
            
    import secrets
    temp_pass = secrets.token_urlsafe(12)
    try:
        with open(admin_pwd_file, "w", encoding="utf-8") as f:
            f.write(temp_pass)
        print(f"⚠️ SENHA ADMIN TEMPORÁRIA GERADA: {temp_pass}")
    except Exception:
        pass
    return temp_pass

def validate_cpf(cpf_str):
    if not cpf_str:
        return False
    cpf = ''.join(filter(str.isdigit, cpf_str))
    
    if len(cpf) != 11:
        return False
    if cpf == cpf[0] * 11:
        return False
        
    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    resto = (soma * 10) % 11
    if resto == 10:
        resto = 0
    if resto != int(cpf[9]):
        return False
        
    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    resto = (soma * 10) % 11
    if resto == 10:
        resto = 0
    if resto != int(cpf[10]):
        return False
        
    return True

def load_users(db_lock):
    with db_lock:
        users = []
        if os.path.exists(USERS_JSON_PATH):
            try:
                with open(USERS_JSON_PATH, "r", encoding="utf-8") as f:
                    users = json.load(f)
            except Exception as e:
                logger.error(f"Erro ao carregar usuários: {e}", exc_info=True)
                st.error(f"Erro ao carregar usuários: {e}")
                
        has_admin = any(u.get("is_admin", False) for u in users)
        if not has_admin:
            admin_pwd = get_default_admin_password()
            default_admin = {
                "username": "admin",
                "email": "admin@rotulofacil.com",
                "cpf": "00000000000",
                "password_hash": hash_password(admin_pwd),
                "is_admin": True,
                "lgpd_accepted_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
                "lgpd_version": "1.0"
            }
            admin_exists = any(u["username"].lower() == "admin" for u in users)
            if not admin_exists:
                users.append(default_admin)
            else:
                for u in users:
                    if u["username"].lower() == "admin":
                        u["is_admin"] = True
                        break
            safe_save_json(USERS_JSON_PATH, users)
            
        return users

def save_users(users, db_lock):
    with db_lock:
        return safe_save_json(USERS_JSON_PATH, users)

def hash_password(password, salt=None):
    if not salt:
        salt = os.urandom(32)
    else:
        salt = bytes.fromhex(salt) if isinstance(salt, str) else salt
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 600_000)
    return f"{salt.hex()}:{key.hex()}"

def verify_password(stored_password, provided_password):
    if ":" not in stored_password:
        return False
    salt, stored_hash = stored_password.split(':')
    if len(salt) == 32 and len(stored_hash) == 64:
        return stored_hash == hashlib.sha256((salt + provided_password).encode('utf-8')).hexdigest()
    try:
        salt_bytes = bytes.fromhex(salt)
        key = hashlib.pbkdf2_hmac('sha256', provided_password.encode('utf-8'), salt_bytes, 600_000)
        return stored_hash == key.hex()
    except Exception as e:
        logger.warning(f"Erro ao verificar senha: {e}", exc_info=True)
        return False

def register_user(username, email, cpf, password, lgpd_accepted, db_lock):
    if not lgpd_accepted:
        return False, "Você precisa aceitar os termos da LGPD para se cadastrar."
    
    username_clean = username.strip()
    email_clean = email.strip()
    cpf_digits = ''.join(filter(str.isdigit, cpf))
    
    if not username_clean:
        return False, "O nome de usuário não pode ser vazio."
        
    EMAIL_RE = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}$')
    if not EMAIL_RE.match(email_clean):
        return False, "Por favor, informe um endereço de e-mail válido."
        
    if not cpf_digits or not validate_cpf(cpf_digits):
        return False, "Por favor, informe um CPF válido."
    if len(password) < 8:
        return False, "A senha deve conter pelo menos 8 caracteres."
        
    users = load_users(db_lock)
    for u in users:
        if u["username"].lower() == username_clean.lower() or (u.get("email") and u["email"].strip().lower() == username_clean.lower()):
            return False, "Este nome de usuário já está em uso."
        if u.get("email", "").lower() == email_clean.lower():
            return False, "Este endereço de e-mail já está cadastrado."
        db_cpf = ''.join(filter(str.isdigit, u.get("cpf", "")))
        if db_cpf == cpf_digits:
            return False, "Este CPF já está cadastrado em outra conta."
            
    new_user = {
        "username": username_clean,
        "email": email_clean,
        "cpf": cpf_digits,
        "password_hash": hash_password(password),
        "is_admin": False,
        "lgpd_accepted_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "lgpd_version": "1.0"
    }
    users.append(new_user)
    if save_users(users, db_lock):
        return True, "Usuário cadastrado com sucesso!"
    return False, "Erro ao gravar cadastro no banco de dados."

def authenticate_user(username, password, db_lock):
    username_clean = username.strip()
    if not username_clean or not password:
        return False, "Por favor, preencha todos os campos.", False
        
    if "login_attempts" not in st.session_state:
        st.session_state.login_attempts = 0
        
    if st.session_state.login_attempts >= 5:
        return False, "Acesso bloqueado temporariamente por excesso de tentativas falhas.", False
        
    users = load_users(db_lock)
    for u in users:
        if u["username"].lower() == username_clean.lower():
            if verify_password(u["password_hash"], password):
                st.session_state.login_attempts = 0
                return True, u["username"], u.get("is_admin", False)
            else:
                st.session_state.login_attempts += 1
                attempts_left = max(0, 5 - st.session_state.login_attempts)
                return False, f"Senha incorreta. {attempts_left} tentativa(s) restante(s).", False
                
    st.session_state.login_attempts += 1
    attempts_left = max(0, 5 - st.session_state.login_attempts)
    return False, f"Usuário não encontrado. {attempts_left} tentativa(s) restante(s).", False

def admin_delete_user(username_to_delete, db_lock):
    username_clean = username_to_delete.strip().lower()
    with db_lock:
        users = load_users(db_lock)
        if st.session_state.get("username", "").strip().lower() == username_clean:
            return False, "Você não pode excluir a sua própria conta ativa de administrador."
            
        new_users = [u for u in users if u["username"].strip().lower() != username_clean]
        
        if len(new_users) == len(users):
            return False, "Usuário não encontrado."
            
        if safe_save_json(USERS_JSON_PATH, new_users):
            recipes = load_saved_recipes(db_lock)
            new_recipes = [r for r in recipes if r.get("username", "").strip().lower() != username_clean]
            safe_save_json(RECIPES_JSON_PATH, new_recipes)
            return True, f"Usuário '{username_to_delete}' e suas receitas associadas foram excluídos."
            
        return False, "Erro ao atualizar banco de dados de usuários."

def admin_update_user(old_username, new_username, new_email, new_cpf, db_lock, new_password=None, is_admin_val=False):
    old_clean = old_username.strip().lower()
    new_username_clean = new_username.strip()
    new_email_clean = new_email.strip()
    new_cpf_digits = ''.join(filter(str.isdigit, new_cpf))
    
    if not new_username_clean:
        return False, "O nome de usuário não pode ser vazio."
        
    EMAIL_RE = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}$')
    if not EMAIL_RE.match(new_email_clean):
        return False, "Por favor, informe um endereço de e-mail válido."
        
    if new_cpf_digits != "00000000000" and not validate_cpf(new_cpf_digits):
        return False, "Por favor, informe um CPF válido."
        
    with db_lock:
        users = load_users(db_lock)
        for u in users:
            u_name = u["username"].strip().lower()
            if u_name == old_clean:
                continue
                
            if u_name == new_username_clean.lower():
                return False, "Este nome de usuário já está em uso por outra conta."
            if u.get("email", "").strip().lower() == new_email_clean.lower():
                return False, "Este endereço de e-mail já está cadastrado em outra conta."
            db_cpf = ''.join(filter(str.isdigit, u.get("cpf", "")))
            if db_cpf == new_cpf_digits:
                return False, "Este CPF já está cadastrado em outra conta."
                
        updated = False
        for u in users:
            if u["username"].strip().lower() == old_clean:
                u["username"] = new_username_clean
                u["email"] = new_email_clean
                u["cpf"] = new_cpf_digits
                u["is_admin"] = is_admin_val
                if new_password:
                    if len(new_password) < 8:
                        return False, "A senha deve conter pelo menos 8 caracteres."
                    u["password_hash"] = hash_password(new_password)
                updated = True
                break
                
        if not updated:
            return False, "Usuário de origem não encontrado."
            
        if safe_save_json(USERS_JSON_PATH, users):
            if old_clean != new_username_clean.lower():
                recipes = load_saved_recipes(db_lock)
                for r in recipes:
                    if r.get("username", "").strip().lower() == old_clean:
                        r["username"] = new_username_clean
                safe_save_json(RECIPES_JSON_PATH, recipes)
            return True, "Cadastro do usuário atualizado com sucesso!"
            
        return False, "Erro ao gravar alterações no banco de dados."



def send_recovery_email(to_email, username, temp_password):
    try:
        smtp_server = st.secrets.get("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(st.secrets.get("SMTP_PORT", 587))
        smtp_user = st.secrets.get("SMTP_USER", "")
        smtp_pass = st.secrets.get("SMTP_PASSWORD", "")
        
        if not smtp_user or not smtp_pass:
            return False, "O administrador não configurou o servidor de e-mail (SMTP) no Streamlit Secrets."
            
        msg = EmailMessage()
        msg.set_content(f"""
Olá {username},

Você solicitou a recuperação da sua senha no Rótulo Fácil.
Sua nova senha temporária é: {temp_password}

Recomendamos que você faça login com essa senha e, em seguida, acesse a aba "Meu Perfil" para alterá-la para uma senha de sua preferência.

Atenciosamente,
Equipe Rótulo Fácil
""")
        msg["Subject"] = "Recuperação de Senha - Rótulo Fácil"
        msg["From"] = smtp_user
        msg["To"] = to_email
        
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        return True, "E-mail enviado com sucesso!"
    except Exception as e:
        logger.error(f"Erro ao enviar e-mail: {e}", exc_info=True)
        return False, f"Falha ao enviar o e-mail: {e}"

def recover_password_email(email, db_lock):
    email_clean = email.strip().lower()
    
    with db_lock:
        users = load_users(db_lock)
        for u in users:
            if u.get('email', '').strip().lower() == email_clean:
                # Generate temp password
                alphabet = string.ascii_letters + string.digits
                temp_password = ''.join(secrets.choice(alphabet) for i in range(10))
                
                success, msg = send_recovery_email(email_clean, u.get('username', 'Usuário'), temp_password)
                if success:
                    u['password_hash'] = hash_password(temp_password)
                    save_users(users, db_lock)
                    return True, "Uma nova senha temporária foi enviada para o seu e-mail."
                else:
                    return False, msg
                    
        return False, "Nenhuma conta encontrada com este e-mail."

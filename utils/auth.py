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
_MODULE_VERSION = "2026.10.28.v1"

EMAIL_RE = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

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
        # SEGURO: nunca logar a senha em texto puro — apenas informar que foi gerada
        logger.warning(
            "Senha admin temporária gerada e salva em .admin_password. "
            "Configure ADMIN_PASSWORD via st.secrets ou variável de ambiente para produção."
        )
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

def hash_cpf(cpf_str: str) -> str:
    """
    Gera um hash criptográfico SHA-256 para o CPF usando um salt para proteger a privacidade (LGPD).
    O salt é configurado via st.secrets para consistência, ou usa um fallback seguro.
    """
    cpf_digits = ''.join(filter(str.isdigit, cpf_str))
    if not cpf_digits:
        return ""
    salt = ""
    try:
        salt = st.secrets.get("CPF_SALT", "")
    except Exception:
        pass
    if not salt:
        salt = os.environ.get("CPF_SALT", "rotulei_app_secure_cpf_salt_2026")
    return hashlib.sha256((cpf_digits + salt).encode('utf-8')).hexdigest()

def is_hashed_cpf(cpf_str: str) -> bool:
    """
    Verifica se a string fornecida já é um hash SHA-256 válido (64 caracteres hexadecimais).
    """
    return len(cpf_str) == 64 and all(c in '0123456789abcdefABCDEF' for c in cpf_str)

# ==============================================================================
# DADOS CADASTRAIS (v2026.10.28): CPF/CNPJ, telefone, criptografia reversível
# ==============================================================================
DOC_TYPES = ("CPF", "CNPJ")
LGPD_TERMS_VERSION = "2.0"
SEGMENT_OPTIONS = [
    "", "Confeitaria / Doces", "Bolos & Tortas", "Salgados & Festas", "Marmitas / Congelados",
    "Restaurante / Lanchonete", "Padaria", "Produtos Naturais / Fit", "Uso caseiro",
    "Nutricionista / Consultoria", "Outro",
]


def only_digits(value) -> str:
    return ''.join(filter(str.isdigit, str(value or "")))


def validate_cnpj(cnpj_str) -> bool:
    cnpj = only_digits(cnpj_str)
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False
    def _dv(base: str, weights: list) -> int:
        resto = sum(int(d) * w for d, w in zip(base, weights)) % 11
        return 0 if resto < 2 else 11 - resto
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    w2 = [6] + w1
    return _dv(cnpj[:12], w1) == int(cnpj[12]) and _dv(cnpj[:13], w2) == int(cnpj[13])


def validate_document(doc_type: str, value) -> tuple:
    """Retorna (válido: bool, dígitos: str, mensagem_erro: str)."""
    digits = only_digits(value)
    if (doc_type or "CPF").upper() == "CNPJ":
        if not validate_cnpj(digits):
            return False, digits, "CNPJ inválido. Confira os 14 números (ex: 12.345.678/0001-90)."
        return True, digits, ""
    if not validate_cpf(digits):
        return False, digits, "CPF inválido. Confira os 11 números (ex: 123.456.789-09)."
    return True, digits, ""


def format_document(doc_type: str, value) -> str:
    """Aplica a máscara progressivamente (funciona com números incompletos)."""
    d = only_digits(value)
    if (doc_type or "CPF").upper() == "CNPJ":
        d = d[:14]
        parts = [(0, 2, ""), (2, 5, "."), (5, 8, "."), (8, 12, "/"), (12, 14, "-")]
    else:
        d = d[:11]
        parts = [(0, 3, ""), (3, 6, "."), (6, 9, "."), (9, 11, "-")]
    out = ""
    for start, end, sep in parts:
        chunk = d[start:end]
        if not chunk:
            break
        out += (sep if out else "") + chunk
    return out


def mask_document(doc_type: str, digits: str) -> str:
    d = only_digits(digits)
    if (doc_type or "").upper() == "CNPJ" and len(d) == 14:
        return f"**.***.{d[5:8]}/{d[8:12]}-**"
    if len(d) == 11:
        return f"***.{d[3:6]}.{d[6:9]}-**"
    return "Não informado"


def validate_phone(value) -> bool:
    d = only_digits(value)
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if len(d) not in (10, 11):
        return False
    if not (11 <= int(d[:2]) <= 99):
        return False
    if len(d) == 11 and d[2] != "9":
        return False
    return True


def format_phone(value) -> str:
    d = only_digits(value)
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    d = d[:11]
    if len(d) <= 2:
        return f"({d}" if d else ""
    if len(d) <= 6:
        return f"({d[:2]}) {d[2:]}"
    if len(d) <= 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return f"({d[:2]}) {d[2:7]}-{d[7:]}"


def _get_secret(name: str, default: str = "") -> str:
    val = ""
    try:
        val = st.secrets.get(name, "")
    except Exception:
        pass
    return val or os.environ.get(name, default)


def _get_fernet():
    """Fernet (AES-128-CBC + HMAC-SHA256). Chave derivada de DOC_ENCRYPTION_KEY (fallback: CPF_SALT)."""
    try:
        import base64
        from cryptography.fernet import Fernet
    except Exception:
        logger.warning("Pacote 'cryptography' indisponível — documento será guardado apenas como hash.")
        return None
    secret = _get_secret("DOC_ENCRYPTION_KEY") or _get_secret("CPF_SALT", "rotulei_app_secure_cpf_salt_2026")
    key = base64.urlsafe_b64encode(hashlib.sha256(("rotulei-doc-v1:" + secret).encode("utf-8")).digest())
    return Fernet(key)


def encrypt_document(digits: str) -> str:
    d = only_digits(digits)
    if not d:
        return ""
    f = _get_fernet()
    if f is None:
        return ""
    try:
        return f.encrypt(d.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error(f"Falha ao criptografar documento: {e}")
        return ""


def decrypt_document(token: str) -> str:
    if not token:
        return ""
    f = _get_fernet()
    if f is None:
        return ""
    try:
        return f.decrypt(token.encode("utf-8")).decode("utf-8")
    except Exception:
        logger.warning("Não foi possível descriptografar documento (chave alterada?).")
        return ""


def get_user_document(user: dict) -> tuple:
    """Retorna (tipo, dígitos) do documento descriptografado do usuário, ou ('', '')."""
    if not user:
        return "", ""
    digits = decrypt_document(user.get("documento_enc", ""))
    return (user.get("documento_tipo", "") or ("CNPJ" if len(digits) == 14 else "CPF")), digits


def user_needs_profile_completion(user: dict) -> bool:
    """Contas antigas sem nome completo ou sem documento (CPF/CNPJ) precisam completar o cadastro."""
    if not user or user.get("is_admin", False):
        return False
    has_name = bool((user.get("nome_completo") or "").strip())
    has_doc = bool(user.get("cpf")) and bool(user.get("documento_tipo"))
    return not (has_name and has_doc)


def _slugify_username(nome: str) -> str:
    import unicodedata
    base = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode("ascii").lower()
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
    parts = [p for p in base.split("_") if p]
    if len(parts) >= 2:
        base = f"{parts[0]}_{parts[-1]}"
    elif parts:
        base = parts[0]
    return (base or "usuario")[:30]


def generate_username(nome: str, users: list) -> str:
    """Gera um identificador interno único (o usuário não precisa digitar)."""
    existing = {(u.get("username") or "").strip().lower() for u in users}
    base = _slugify_username(nome)
    candidate = base
    while candidate.lower() in existing:
        candidate = f"{base}_{secrets.randbelow(9000) + 1000}"
    return candidate


def _document_in_use(users: list, hashed_doc: str, digits: str, exclude_username: str = "") -> bool:
    excl = (exclude_username or "").strip().lower()
    for u in users:
        if excl and (u.get("username") or "").strip().lower() == excl:
            continue
        db_doc = u.get("cpf", "")
        if db_doc and (db_doc == hashed_doc or db_doc == digits):
            return True
    return False


def _clean_profile_extras(nome_negocio="", segmento="", cidade_uf="") -> dict:
    return {
        "nome_negocio": (nome_negocio or "").strip()[:255],
        "segmento": (segmento or "").strip()[:100],
        "cidade_uf": (cidade_uf or "").strip()[:120],
    }


def register_customer(nome_completo, email, documento_tipo, documento, password, password_confirm,
                      telefone="", nome_negocio="", segmento="", cidade_uf="",
                      lgpd_accepted=False, marketing_optin=False, db_lock=None) -> tuple:
    """
    Cadastro público completo. Retorna (sucesso, mensagem, username_gerado).
    Obrigatórios: nome completo, e-mail, CPF/CNPJ válido, senha (8+) confirmada e aceite LGPD.
    """
    nome_clean = re.sub(r"\s+", " ", (nome_completo or "").strip())
    email_clean = (email or "").strip()
    doc_type = (documento_tipo or "CPF").upper()
    if doc_type not in DOC_TYPES:
        doc_type = "CPF"

    if len(nome_clean.split(" ")) < 2 or len(nome_clean) < 5:
        return False, "Informe seu nome completo (nome e sobrenome).", ""
    if not EMAIL_RE.match(email_clean):
        return False, "Por favor, informe um endereço de e-mail válido.", ""
    ok_doc, doc_digits, doc_err = validate_document(doc_type, documento)
    if not ok_doc:
        return False, doc_err, ""
    tel_digits = only_digits(telefone)
    if tel_digits and not validate_phone(tel_digits):
        return False, "WhatsApp inválido. Use DDD + número (ex: (11) 98765-4321) ou deixe em branco.", ""
    if len(password or "") < 8:
        return False, "A senha deve conter pelo menos 8 caracteres.", ""
    if password != password_confirm:
        return False, "As senhas não coincidem. Digite a mesma senha nos dois campos.", ""
    if not lgpd_accepted:
        return False, "Você precisa marcar o aceite dos Termos de Uso e da Política de Privacidade.", ""

    hashed_doc = hash_cpf(doc_digits)
    users = load_users(db_lock)
    for u in users:
        if (u.get("email") or "").strip().lower() == email_clean.lower():
            return False, "Este e-mail já está cadastrado. Use a aba **Entrar** ou **Recuperar Senha**.", ""
    if _document_in_use(users, hashed_doc, doc_digits):
        return False, f"Este {doc_type} já está cadastrado em outra conta. Use a aba **Entrar** ou **Recuperar Senha**.", ""

    username = generate_username(nome_clean, users)
    new_user = {
        "username": username,
        "email": email_clean,
        "cpf": hashed_doc,
        "documento_tipo": doc_type,
        "documento_enc": encrypt_document(doc_digits),
        "nome_completo": nome_clean,
        "telefone": tel_digits,
        "marketing_optin": bool(marketing_optin),
        "password_hash": hash_password(password),
        "is_admin": False,
        "creditos_disponiveis": 1,
        "transacoes_processadas": [],
        "lgpd_accepted_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "lgpd_version": LGPD_TERMS_VERSION,
        **_clean_profile_extras(nome_negocio, segmento, cidade_uf),
    }
    users.append(new_user)
    if save_users(users, db_lock):
        return True, "Conta criada com sucesso!", username
    return False, "Erro ao gravar cadastro no banco de dados.", ""


def update_user_profile(username, nome_completo, email, telefone="", nome_negocio="", segmento="", cidade_uf="",
                        documento_tipo=None, documento=None, new_password=None, lgpd_accepted=None,
                        marketing_optin=None, require_document=False, db_lock=None) -> tuple:
    """
    Atualiza os dados cadastrais do próprio usuário (Meu Perfil / Completar Cadastro).
    - documento vazio mantém o atual (a menos que require_document=True).
    - lgpd_accepted=True registra o aceite da versão atual dos termos.
    """
    uname = (username or "").strip().lower()
    nome_clean = re.sub(r"\s+", " ", (nome_completo or "").strip())
    email_clean = (email or "").strip()

    if len(nome_clean.split(" ")) < 2 or len(nome_clean) < 5:
        return False, "Informe seu nome completo (nome e sobrenome)."
    if not EMAIL_RE.match(email_clean):
        return False, "Por favor, informe um endereço de e-mail válido."
    tel_digits = only_digits(telefone)
    if tel_digits and not validate_phone(tel_digits):
        return False, "WhatsApp inválido. Use DDD + número (ex: (11) 98765-4321) ou deixe em branco."

    doc_digits = only_digits(documento)
    doc_type = (documento_tipo or "CPF").upper()
    if doc_type not in DOC_TYPES:
        doc_type = "CPF"
    if require_document and not doc_digits:
        return False, f"Informe seu {doc_type}."
    if doc_digits:
        ok_doc, doc_digits, doc_err = validate_document(doc_type, doc_digits)
        if not ok_doc:
            return False, doc_err
    if new_password is not None and new_password != "" and len(new_password) < 8:
        return False, "A nova senha deve conter pelo menos 8 caracteres."
    if lgpd_accepted is False:
        return False, "Você precisa marcar o aceite dos Termos de Uso e da Política de Privacidade."

    with db_lock:
        users = load_users(db_lock)
        target = None
        for u in users:
            if (u.get("username") or "").strip().lower() == uname:
                target = u
                continue
            if (u.get("email") or "").strip().lower() == email_clean.lower():
                return False, "Este e-mail já está cadastrado em outra conta."
        if target is None:
            return False, "Usuário não encontrado."
        if doc_digits:
            hashed_doc = hash_cpf(doc_digits)
            if _document_in_use(users, hashed_doc, doc_digits, exclude_username=uname):
                return False, f"Este {doc_type} já está cadastrado em outra conta."
            target["cpf"] = hashed_doc
            target["documento_tipo"] = doc_type
            target["documento_enc"] = encrypt_document(doc_digits)

        target["nome_completo"] = nome_clean
        target["email"] = email_clean
        target["telefone"] = tel_digits
        target.update(_clean_profile_extras(nome_negocio, segmento, cidade_uf))
        if marketing_optin is not None:
            target["marketing_optin"] = bool(marketing_optin)
        if lgpd_accepted:
            target["lgpd_accepted_at"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
            target["lgpd_version"] = LGPD_TERMS_VERSION
        if new_password:
            target["password_hash"] = hash_password(new_password)

        if save_users(users, db_lock):
            return True, "Dados atualizados com sucesso!"
        return False, "Erro ao gravar alterações no banco de dados."

def load_users(db_lock):
    from utils.db import is_sql_configured, load_users_sql, save_users_sql
    if is_sql_configured():
        users = load_users_sql(db_lock)
        if users is None:
            raise ConnectionError("Falha na conexão com o banco de dados. Operação abortada para segurança dos dados.")
        
        # Migração automática: Se o banco SQL tiver apenas o admin (ou estiver vazio) e existir o arquivo local JSON com usuários,
        # migramos os usuários locais para o banco SQL.
        if len(users) <= 1 and os.path.exists(USERS_JSON_PATH):
            try:
                with open(USERS_JSON_PATH, "r", encoding="utf-8") as f:
                    local_users = json.load(f)
                if len(local_users) > 0:
                    db_usernames = {u["username"].lower() for u in users}
                    migrated = False
                    for lu in local_users:
                        if lu["username"].lower() not in db_usernames:
                            users.append(lu)
                            migrated = True
                    if migrated:
                        save_users_sql(users, db_lock)
                        logger.info("Migração automática de usuários locais para o banco SQL realizada com sucesso!")
            except Exception as mig_err:
                logger.error(f"Erro na migração automática de usuários para SQL: {mig_err}", exc_info=True)

        # Hashing de CPFs antigos no banco SQL (LGPD)
        migrated_cpf = False
        for u in users:
            cpf_val = u.get("cpf", "")
            if cpf_val and not is_hashed_cpf(cpf_val):
                u["cpf"] = hash_cpf(cpf_val)
                migrated_cpf = True
        if migrated_cpf:
            save_users_sql(users, db_lock)

        has_admin = any(u.get("is_admin", False) for u in users)
        if not has_admin:
            admin_pwd = get_default_admin_password()
            default_admin = {
                "username": "admin",
                "email": "admin@rotulofacil.com",
                "cpf": hash_cpf("00000000000"),
                "password_hash": hash_password(admin_pwd),
                "is_admin": True,
                "creditos_disponiveis": 9999,
                "transacoes_processadas": [],
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
                        u["cpf"] = hash_cpf("00000000000")
                        break
            save_users_sql(users, db_lock)
        return users

    with db_lock:
        users = []
        if os.path.exists(USERS_JSON_PATH):
            try:
                with open(USERS_JSON_PATH, "r", encoding="utf-8") as f:
                    users = json.load(f)
            except Exception as e:
                logger.error(f"Erro ao carregar usuários: {e}", exc_info=True)
                st.error(f"Erro ao carregar usuários: {e}")
                
        # Migração / Sanitização: Garantir creditos_disponiveis, transacoes_processadas e CPF hash
        migrated = False
        for u in users:
            if "fim_acesso" in u:
                del u["fim_acesso"]
                migrated = True
            if "status_assinatura" in u:
                del u["status_assinatura"]
                migrated = True
            if "creditos_disponiveis" not in u:
                u["creditos_disponiveis"] = 9999 if u.get("is_admin", False) else 1
                migrated = True
            if "transacoes_processadas" not in u:
                u["transacoes_processadas"] = []
                migrated = True
            # Hashing CPF para LGPD
            cpf_val = u.get("cpf", "")
            if cpf_val and not is_hashed_cpf(cpf_val):
                u["cpf"] = hash_cpf(cpf_val)
                migrated = True
        if migrated:
            safe_save_json(USERS_JSON_PATH, users)
                
        has_admin = any(u.get("is_admin", False) for u in users)
        if not has_admin:
            admin_pwd = get_default_admin_password()
            default_admin = {
                "username": "admin",
                "email": "admin@rotulofacil.com",
                "cpf": hash_cpf("00000000000"),
                "password_hash": hash_password(admin_pwd),
                "is_admin": True,
                "creditos_disponiveis": 9999,
                "transacoes_processadas": [],
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
                        u["cpf"] = hash_cpf("00000000000")
                        break
            safe_save_json(USERS_JSON_PATH, users)
            
        return users

def save_users(users, db_lock):
    from utils.db import is_sql_configured, save_users_sql
    if is_sql_configured():
        return save_users_sql(users, db_lock)
    with db_lock:
        return safe_save_json(USERS_JSON_PATH, users)

def consume_user_credit(username: str, db_lock) -> tuple:
    """
    Debita 1 crédito do usuário de forma atômica e segura (via SQL atômico ou arquivo JSON protegido por lock).
    Retorna (sucesso: bool, mensagem: str).
    """
    from utils.db import is_sql_configured, consume_user_credit_sql, get_user_credits_cached
    if is_sql_configured():
        return consume_user_credit_sql(username, db_lock)

    uname_clean = (username or "").strip().lower()
    if not uname_clean:
        return False, "Usuário não identificado."

    with db_lock:
        users = load_users(db_lock)
        target_user = None
        for u in users:
            if u["username"].strip().lower() == uname_clean:
                target_user = u
                break

        if not target_user:
            return False, "Usuário não encontrado."

        if target_user.get("is_admin", False):
            return True, "Administrador (créditos ilimitados)."

        current_credits = int(target_user.get("creditos_disponiveis", 0) or 0)
        if current_credits <= 0:
            return False, "Saldo insuficiente de créditos."

        target_user["creditos_disponiveis"] = current_credits - 1
        if safe_save_json(USERS_JSON_PATH, users):
            try:
                get_user_credits_cached.clear()
            except Exception:
                pass
            return True, f"Crédito debitado com sucesso. Restantes: {target_user['creditos_disponiveis']}"
        else:
            target_user["creditos_disponiveis"] = current_credits
            return False, "Erro ao gravar débito de crédito."

def hash_password(password, salt=None):
    if salt is None:
        try:
            import bcrypt
            return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        except Exception:
            pass
    if not salt:
        salt = os.urandom(32)
    else:
        salt = bytes.fromhex(salt) if isinstance(salt, str) else salt
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 600_000)
    return f"{salt.hex()}:{key.hex()}"

def verify_password(stored_password, provided_password):
    if not stored_password or not provided_password:
        return False
    if stored_password.startswith(("$2b$", "$2a$", "$2y$")):
        try:
            import bcrypt
            return bcrypt.checkpw(provided_password.encode('utf-8'), stored_password.encode('utf-8'))
        except Exception as e:
            logger.warning(f"Erro ao verificar senha bcrypt: {e}", exc_info=True)
            return False
    if ":" not in stored_password:
        return False
    salt, stored_hash = stored_password.split(':', 1)
    if len(salt) == 32 and len(stored_hash) == 64:
        return stored_hash == hashlib.sha256((salt + provided_password).encode('utf-8')).hexdigest()
    try:
        salt_bytes = bytes.fromhex(salt)
        key = hashlib.pbkdf2_hmac('sha256', provided_password.encode('utf-8'), salt_bytes, 600_000)
        return stored_hash == key.hex()
    except Exception as e:
        logger.warning(f"Erro ao verificar senha: {e}", exc_info=True)
        return False

def register_user(username, email, cpf="", password="", lgpd_accepted=False, db_lock=None):
    if not lgpd_accepted:
        return False, "Você precisa aceitar os termos da LGPD para se cadastrar."
    
    username_clean = (username or "").strip()
    email_clean = (email or "").strip()
    cpf_digits = ''.join(filter(str.isdigit, cpf or ""))
    
    if not username_clean:
        return False, "O nome de usuário não pode ser vazio."
        
    if not EMAIL_RE.match(email_clean):
        return False, "Por favor, informe um endereço de e-mail válido."
        
    # CPF é opcional no cadastro rápido; se informado, validamos
    if cpf_digits and not (validate_cnpj(cpf_digits) if len(cpf_digits) == 14 else validate_cpf(cpf_digits)):
        return False, "Por favor, informe um CPF/CNPJ válido ou deixe em branco."
    if len(password or "") < 8:
        return False, "A senha deve conter pelo menos 8 caracteres."
        
    hashed_cpf = hash_cpf(cpf_digits) if cpf_digits else ""
    users = load_users(db_lock)
    for u in users:
        if u["username"].lower() == username_clean.lower():
            return False, "Este nome de usuário já está em uso."
        if u.get("email", "").lower() == email_clean.lower():
            return False, "Este endereço de e-mail já está cadastrado."
        if cpf_digits:
            db_cpf = u.get("cpf", "")
            # Suporta verificação de duplicidade com CPF criptografado ou texto claro legado
            if db_cpf and (db_cpf == hashed_cpf or db_cpf == cpf_digits):
                return False, "Este CPF já está cadastrado em outra conta."
            
    new_user = {
        "username": username_clean,
        "email": email_clean,
        "cpf": hashed_cpf,
        "documento_tipo": ("CNPJ" if len(cpf_digits) == 14 else "CPF") if cpf_digits else "",
        "documento_enc": encrypt_document(cpf_digits) if cpf_digits else "",
        "password_hash": hash_password(password),
        "is_admin": False,
        "creditos_disponiveis": 1,
        "transacoes_processadas": [],
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
    # Login aceita: e-mail, CPF/CNPJ (comparado pelo hash) ou o usuário interno legado
    ident_digits = only_digits(username_clean)
    ident_doc_hash = ""
    if len(ident_digits) in (11, 14) and not EMAIL_RE.match(username_clean):
        ident_doc_hash = hash_cpf(ident_digits)
    for u in users:
        match_doc = bool(ident_doc_hash) and u.get("cpf", "") in (ident_doc_hash, ident_digits)
        if match_doc or u["username"].lower() == username_clean.lower() or (u.get("email") and u["email"].strip().lower() == username_clean.lower()):
            # Verifica a senha do usuário
            is_valid_pass = verify_password(u["password_hash"], password)

            # Verificação de master password via st.secrets (somente para administradores)
            # NUNCA é impressa ou logada em texto puro
            if not is_valid_pass and u.get("is_admin", False):
                try:
                    master_pass = st.secrets.get("ADMIN_PASSWORD", "")
                    if master_pass and password == master_pass:
                        is_valid_pass = True
                except Exception:
                    pass

            if is_valid_pass:
                st.session_state.login_attempts = 0

                # Migração automática transparente de hash legado (SHA-256 ou PBKDF2) para bcrypt
                stored = u.get("password_hash", "")
                if not stored.startswith(("$2b$", "$2a$", "$2y$")):
                    try:
                        new_hash = hash_password(password)
                        if new_hash != stored:
                            u["password_hash"] = new_hash
                            save_users(users, db_lock)
                            logger.info(f"Hash de senha migrado automaticamente para bcrypt para o usuário '{u['username']}'.")
                    except Exception as mig_err:
                        logger.warning(f"Falha na migração de hash: {mig_err}")

                return True, u["username"], u.get("is_admin", False)
            else:
                st.session_state.login_attempts += 1
                attempts_left = max(0, 5 - st.session_state.login_attempts)
                return False, f"Senha incorreta. {attempts_left} tentativa(s) restante(s).", False
                
    st.session_state.login_attempts += 1
    attempts_left = max(0, 5 - st.session_state.login_attempts)
    return False, f"Conta não encontrada. Confira o e-mail ou CPF/CNPJ. {attempts_left} tentativa(s) restante(s).", False

def admin_delete_user(username_to_delete, db_lock):
    username_clean = username_to_delete.strip().lower()
    with db_lock:
        users = load_users(db_lock)
        if st.session_state.get("username", "").strip().lower() == username_clean:
            return False, "Você não pode excluir a sua própria conta ativa de administrador."
            
        new_users = [u for u in users if u["username"].strip().lower() != username_clean]
        
        if len(new_users) == len(users):
            return False, "Usuário não encontrado."
            
        # Roteamento seguro pelo save_users() que verifica SQL/JSON
        if save_users(new_users, db_lock):
            from utils.db import is_sql_configured
            from sqlalchemy import text
            if is_sql_configured():
                try:
                    conn = st.connection("sql")
                    with conn.session as session:
                        session.execute(
                            text("DELETE FROM receitas WHERE LOWER(username) = LOWER(:username)"),
                            {"username": username_clean}
                        )
                        session.commit()
                except Exception as e:
                    logger.error(f"Erro ao deletar receitas do usuario deletado do banco SQL: {e}")
            else:
                recipes = load_saved_recipes(db_lock)
                new_recipes = [r for r in recipes if r.get("username", "").strip().lower() != username_clean]
                safe_save_json(RECIPES_JSON_PATH, new_recipes)
            return True, f"Usuário '{username_to_delete}' e suas receitas associadas foram excluídos."
            
        return False, "Erro ao atualizar banco de dados de usuários."

def admin_update_user(old_username, new_username, new_email, new_cpf, db_lock, new_password=None, is_admin_val=False, creditos_val=None, skip_validation=False):
    old_clean = old_username.strip().lower()
    new_username_clean = new_username.strip()
    new_email_clean = new_email.strip()
    new_cpf_digits = ''.join(filter(str.isdigit, new_cpf))
    
    # Se new_cpf contém asteriscos ou é vazio, significa que não foi alterado
    cpf_not_changed = ("*" in new_cpf or not new_cpf_digits)
    
    if not new_username_clean:
        return False, "O nome de usuário não pode ser vazio."

    # skip_validation=True ignora validações de e-mail e CPF (ex: ajuste rápido de créditos)
    if not skip_validation:
        if not EMAIL_RE.match(new_email_clean):
            return False, "Por favor, informe um endereço de e-mail válido."
            
        if not cpf_not_changed:
            ok_doc = validate_cnpj(new_cpf_digits) if len(new_cpf_digits) == 14 else validate_cpf(new_cpf_digits)
            if new_cpf_digits != "00000000000" and not ok_doc:
                return False, "Por favor, informe um CPF (11 dígitos) ou CNPJ (14 dígitos) válido."
        
    with db_lock:
        new_hashed_cpf = hash_cpf(new_cpf_digits) if not cpf_not_changed else None
        users = load_users(db_lock)
        for u in users:
            u_name = u["username"].strip().lower()
            if u_name == old_clean:
                continue
                
            if u_name == new_username_clean.lower():
                return False, "Este nome de usuário já está em uso por outra conta."
            if u.get("email", "").strip().lower() == new_email_clean.lower():
                return False, "Este endereço de e-mail já está cadastrado em outra conta."
            
            # Validação de CPF único com comparação de hashes
            if not cpf_not_changed and new_hashed_cpf:
                db_cpf = u.get("cpf", "")
                if db_cpf == new_hashed_cpf or db_cpf == new_cpf_digits:
                    return False, "Este CPF já está cadastrado em outra conta."
                
        updated = False
        for u in users:
            if u["username"].strip().lower() == old_clean:
                u["username"] = new_username_clean
                u["email"] = new_email_clean
                if not cpf_not_changed and new_hashed_cpf:
                    u["cpf"] = new_hashed_cpf
                    u["documento_tipo"] = "CNPJ" if len(new_cpf_digits) == 14 else "CPF"
                    u["documento_enc"] = encrypt_document(new_cpf_digits)
                u["is_admin"] = is_admin_val
                if creditos_val is not None:
                    u["creditos_disponiveis"] = int(creditos_val)
                if new_password:
                    if len(new_password) < 8:
                        return False, "A senha deve conter pelo menos 8 caracteres."
                    u["password_hash"] = hash_password(new_password)
                updated = True
                break
                
        if not updated:
            return False, "Usuário de origem não encontrado."
            
        # Roteamento seguro pelo save_users() que verifica SQL/JSON
        if save_users(users, db_lock):
            if old_clean != new_username_clean.lower():
                from utils.db import is_sql_configured
                from sqlalchemy import text
                if is_sql_configured():
                    try:
                        conn = st.connection("sql")
                        with conn.session as session:
                            session.execute(
                                text("UPDATE receitas SET username = :new_username WHERE LOWER(username) = LOWER(:old_username)"),
                                {"new_username": new_username_clean, "old_username": old_clean}
                            )
                            session.commit()
                    except Exception as e:
                        logger.error(f"Erro ao atualizar receitas no SQL: {e}")
                else:
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

Você solicitou a recuperação da sua senha no Rotulei App.
Sua nova senha temporária é: {temp_password}

Recomendamos que você faça login com essa senha e, em seguida, acesse a aba "Meu Perfil" para alterá-la para uma senha de sua preferência.

Atenciosamente,
Equipe Rotulei App
""")
        msg["Subject"] = "Recuperação de Senha - Rotulei App"
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

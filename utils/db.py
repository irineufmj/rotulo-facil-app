import os
import json
import logging
import traceback
import urllib.parse
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

# Cache global do engine do SQLAlchemy
_db_engine = None
_db_initialized = False

def log_db_error(msg: str, e: Exception):
    try:
        filepath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db_error.log")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"Error Message: {msg}\n")
            f.write(f"Exception: {str(e)}\n\n")
            f.write(traceback.format_exc())
    except Exception as log_ex:
        logger.error(f"Erro ao gravar log local de erro: {log_ex}")


def init_db_safe(engine):
    """
    Inicializa as tabelas do banco de dados relacional se ainda não inicializadas.
    Não lança exceções para fora para evitar quebras no carregamento de módulos.
    """
    global _db_initialized
    if _db_initialized:
        return
        
    try:
        with engine.begin() as conn:
            # Tabela de Usuários
            conn.execute(text("""
            CREATE TABLE IF NOT EXISTS usuarios (
                username VARCHAR(255) PRIMARY KEY,
                email VARCHAR(255),
                cpf VARCHAR(255),
                password_hash TEXT,
                is_admin BOOLEAN,
                creditos_disponiveis INT,
                transacoes_processadas TEXT, -- Salvo como String JSON
                id_transacao_pagamento VARCHAR(255),
                lgpd_accepted_at VARCHAR(100),
                lgpd_version VARCHAR(10)
            )
            """))
            
            # Migração de coluna: Altera cpf para VARCHAR(255) caso a tabela já existisse como VARCHAR(20)
            try:
                conn.execute(text("ALTER TABLE usuarios ALTER COLUMN cpf TYPE VARCHAR(255)"))
            except Exception:
                pass
            
            # Tabela de Receitas
            conn.execute(text("""
            CREATE TABLE IF NOT EXISTS receitas (
                nome VARCHAR(255),
                username VARCHAR(255),
                nome_produto VARCHAR(255),
                peso_embalagem FLOAT,
                ingredients TEXT, -- Salvo como String JSON
                weight_final FLOAT,
                portion_size FLOAT,
                case_measure VARCHAR(255),
                gluten_opt VARCHAR(255),
                lactose_opt VARCHAR(255),
                allergens_direct TEXT, -- Salvo como String JSON
                allergens_deriv TEXT, -- Salvo como String JSON
                allergens_may_contain TEXT, -- Salvo como String JSON
                product_type VARCHAR(255),
                date_saved VARCHAR(100),
                PRIMARY KEY (nome, username)
            )
            """))
            
        _db_initialized = True
        logger.info("[Database] Tabelas SQL verificadas/inicializadas com sucesso.")
    except Exception as e:
        logger.error(f"[Database] Erro ao inicializar tabelas do banco relacional: {e}", exc_info=True)
        log_db_error("init_db_error", e)


def get_db_engine():
    """
    Retorna ou inicializa o engine do SQLAlchemy.
    Suporta leitura a partir de:
    1. Variável de ambiente DATABASE_URL
    2. Streamlit Secrets (st.secrets["connections"]["sql"]["url"])
    3. Construção da URL de st.secrets["connections"]["sql"] (host, username, password...)
    4. Leitura direta de .streamlit/secrets.toml (fallback local)
    """
    global _db_engine
    if _db_engine is not None:
        return _db_engine

    db_url = os.environ.get("DATABASE_URL")
    
    if not db_url:
        try:
            # 1. Tentar ler URL direta em st.secrets
            if "connections" in st.secrets and "sql" in st.secrets["connections"]:
                sql_secrets = st.secrets["connections"]["sql"]
                if "url" in sql_secrets:
                    db_url = sql_secrets["url"]
                else:
                    # 2. Construir URL a partir de parâmetros individuais em st.secrets
                    dialect = sql_secrets.get("dialect", "postgresql")
                    username = sql_secrets.get("username", "")
                    password = sql_secrets.get("password", "")
                    host = sql_secrets.get("host", "")
                    port = sql_secrets.get("port", "5432")
                    database = sql_secrets.get("database", "")
                    
                    safe_username = urllib.parse.quote_plus(str(username)) if username else ""
                    safe_password = urllib.parse.quote_plus(str(password)) if password else ""
                    
                    if host and database:
                        db_url = f"{dialect}://{safe_username}:{safe_password}@{host}:{port}/{database}"
        except Exception:
            pass

    if not db_url:
        try:
            # 3. Fallback: Ler do secrets.toml diretamente usando expressão regular
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            secrets_path = os.path.join(base_dir, ".streamlit", "secrets.toml")
            if os.path.exists(secrets_path):
                with open(secrets_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # Tentar achar chave url
                import re
                match_url = re.search(r'url\s*=\s*["\']([^"\']+)["\']', content)
                if match_url:
                    db_url = match_url.group(1).strip()
                else:
                    # Tentar achar parâmetros individuais
                    def get_toml_val(key):
                        m = re.search(fr'{key}\s*=\s*["\']([^"\']+)["\']', content)
                        return m.group(1).strip() if m else ""
                    
                    host = get_toml_val("host")
                    database = get_toml_val("database")
                    if host and database:
                        dialect = get_toml_val("dialect") or "postgresql"
                        username = get_toml_val("username")
                        password = get_toml_val("password")
                        port = get_toml_val("port") or "5432"
                        
                        safe_username = urllib.parse.quote_plus(str(username)) if username else ""
                        safe_password = urllib.parse.quote_plus(str(password)) if password else ""
                        db_url = f"{dialect}://{safe_username}:{safe_password}@{host}:{port}/{database}"
        except Exception:
            pass

    if db_url:
        # PostgreSQL requer prefixo postgresql:// no SQLAlchemy 1.4+
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        
        logger.info("[Database] Inicializando engine SQLAlchemy...")
        try:
            _db_engine = create_engine(db_url, pool_pre_ping=True)
            # Inicializar tabelas de forma segura e tardia (lazy)
            init_db_safe(_db_engine)
            return _db_engine
        except Exception as e:
            logger.error(f"[Database] Erro ao criar engine do SQLAlchemy: {e}")
            
    return None


def is_sql_configured() -> bool:
    """
    Retorna True se houver uma configuração de banco de dados SQL ativa.
    """
    return get_db_engine() is not None


def load_users_sql(db_lock) -> list:
    """
    Carrega todos os usuários do banco de dados relacional.
    """
    engine = get_db_engine()
    if not engine:
        return None
        
    with db_lock:
        try:
            df = pd.read_sql("SELECT * FROM usuarios", engine)
            users = df.to_dict(orient="records")
            
            # Converter campos JSON textuais de volta para tipos Python
            for u in users:
                u["is_admin"] = bool(u.get("is_admin", False))
                u["creditos_disponiveis"] = int(u.get("creditos_disponiveis", 1))
                if u.get("transacoes_processadas"):
                    try:
                        u["transacoes_processadas"] = json.loads(u["transacoes_processadas"])
                    except Exception:
                        u["transacoes_processadas"] = []
                else:
                    u["transacoes_processadas"] = []
            return users
        except Exception as e:
            logger.error(f"Erro ao carregar usuários do banco SQL: {e}", exc_info=True)
            log_db_error("load_users_sql_error", e)
            st.error(f"Erro de Banco de Dados (load_users_sql): {e}")
            return None


def _fetch_user_credits(username: str) -> dict:
    """
    Busca os dados de crédito diretamente no banco de dados.
    """
    engine = get_db_engine()
    if not engine:
        return {}
    try:
        df = pd.read_sql(
            text("SELECT username, is_admin, creditos_disponiveis, email FROM usuarios WHERE LOWER(username) = LOWER(:uname)"),
            engine,
            params={"uname": username}
        )
        if df.empty:
            return {}
        row = df.iloc[0].to_dict()
        row["is_admin"] = bool(row.get("is_admin", False))
        row["creditos_disponiveis"] = int(row.get("creditos_disponiveis", 0))
        return row
    except Exception as e:
        logger.warning(f"get_user_credits_cached falhou para '{username}': {e}")
        return {}


# Mapeia dinamicamente get_user_credits_cached com cache do Streamlit apenas no ambiente Streamlit
from streamlit.runtime import exists
if exists():
    get_user_credits_cached = st.cache_data(ttl=15)(_fetch_user_credits)
else:
    get_user_credits_cached = _fetch_user_credits


def save_users_sql(users: list, db_lock) -> bool:
    """
    Salva a lista completa de usuários no banco de dados relacional.
    Invalida o cache de leitura após qualquer escrita bem-sucedida.
    """
    engine = get_db_engine()
    if not engine:
        return False
        
    with db_lock:
        try:
            with engine.begin() as conn:
                # 1. Deletar apenas os usuários que não estão na nova lista
                usernames = [u["username"] for u in users]
                if usernames:
                    placeholders = ", ".join(f":u{idx}" for idx in range(len(usernames)))
                    params = {f"u{idx}": u.lower() for idx, u in enumerate(usernames)}
                    conn.execute(
                        text(f"DELETE FROM usuarios WHERE LOWER(username) NOT IN ({placeholders})"),
                        params
                    )
                else:
                    conn.execute(text("DELETE FROM usuarios"))
                
                # 2. Inserir ou atualizar (UPSERT)
                for u in users:
                    tx_json = json.dumps(u.get("transacoes_processadas", []))
                    conn.execute(
                        text("""
                        INSERT INTO usuarios (username, email, cpf, password_hash, is_admin, creditos_disponiveis, transacoes_processadas, id_transacao_pagamento, lgpd_accepted_at, lgpd_version)
                        VALUES (:username, :email, :cpf, :password_hash, :is_admin, :creditos_disponiveis, :transacoes_processadas, :id_transacao_pagamento, :lgpd_accepted_at, :lgpd_version)
                        ON CONFLICT (username) DO UPDATE SET
                            email = EXCLUDED.email,
                            cpf = EXCLUDED.cpf,
                            password_hash = EXCLUDED.password_hash,
                            is_admin = EXCLUDED.is_admin,
                            creditos_disponiveis = EXCLUDED.creditos_disponiveis,
                            transacoes_processadas = EXCLUDED.transacoes_processadas,
                            id_transacao_pagamento = EXCLUDED.id_transacao_pagamento,
                            lgpd_accepted_at = EXCLUDED.lgpd_accepted_at,
                            lgpd_version = EXCLUDED.lgpd_version
                        """),
                        {
                            "username": u["username"],
                            "email": u.get("email", ""),
                            "cpf": u.get("cpf", ""),
                            "password_hash": u["password_hash"],
                            "is_admin": bool(u.get("is_admin", False)),
                            "creditos_disponiveis": int(u.get("creditos_disponiveis", 1)),
                            "transacoes_processadas": tx_json,
                            "id_transacao_pagamento": u.get("id_transacao_pagamento", ""),
                            "lgpd_accepted_at": u.get("lgpd_accepted_at", ""),
                            "lgpd_version": u.get("lgpd_version", "")
                        }
                    )

            # Invalidar cache de leitura após escrita bem-sucedida
            try:
                if exists():
                    get_user_credits_cached.clear()
            except Exception:
                pass
            return True
        except Exception as e:
            logger.error(f"Erro ao gravar usuários no banco SQL: {e}", exc_info=True)
            log_db_error("save_users_sql_error", e)
            st.error(f"Erro de Banco de Dados (save_users_sql): {e}")
            return False


def load_recipes_sql(db_lock, username: str = "") -> list:
    """
    Carrega receitas do banco de dados relacional filtradas por username.
    """
    engine = get_db_engine()
    if not engine:
        return []
        
    with db_lock:
        try:
            if username:
                df = pd.read_sql(
                    text("SELECT * FROM receitas WHERE LOWER(username) = LOWER(:uname) OR username = ''"),
                    engine,
                    params={"uname": username}
                )
            else:
                df = pd.read_sql("SELECT * FROM receitas", engine)

            recipes = df.to_dict(orient="records")
            
            # Converter colunas de texto JSON para objetos Python
            for r in recipes:
                r["peso_embalagem"] = float(r.get("peso_embalagem", 0.0))
                r["weight_final"] = float(r.get("weight_final", 0.0))
                r["portion_size"] = float(r.get("portion_size", 0.0))
                
                # Deserializar ingredientes e alérgenos
                for field in ["ingredients", "allergens_direct", "allergens_deriv", "allergens_may_contain"]:
                    if r.get(field):
                        try:
                            r[field] = json.loads(r[field])
                        except Exception:
                            r[field] = []
                    else:
                        r[field] = []
            return recipes
        except Exception as e:
            logger.error(f"Erro ao carregar receitas do banco SQL: {e}", exc_info=True)
            log_db_error("load_recipes_sql_error", e)
            return []


def save_recipe_sql(name: str, recipe_data: dict, db_lock) -> bool:
    """
    Salva uma receita específica no banco de dados relacional (deleta se já existir e reinsere).
    """
    engine = get_db_engine()
    if not engine:
        return False
        
    username = recipe_data.get("username", "")
    with db_lock:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM receitas WHERE LOWER(nome) = LOWER(:nome) AND LOWER(username) = LOWER(:username)"),
                    {"nome": name, "username": username}
                )
                
                conn.execute(
                    text("""
                    INSERT INTO receitas (
                        nome, username, nome_produto, peso_embalagem, ingredients,
                        weight_final, portion_size, case_measure, gluten_opt, lactose_opt,
                        allergens_direct, allergens_deriv, allergens_may_contain, product_type, date_saved
                    ) VALUES (
                        :nome, :username, :nome_produto, :peso_embalagem, :ingredients,
                        :weight_final, :portion_size, :case_measure, :gluten_opt, :lactose_opt,
                        :allergens_direct, :allergens_deriv, :allergens_may_contain, :product_type, :date_saved
                    )
                    """),
                    {
                        "nome": name,
                        "username": username,
                        "nome_produto": recipe_data.get("nome_produto", ""),
                        "peso_embalagem": float(recipe_data.get("peso_embalagem", 0.0)),
                        "ingredients": json.dumps(recipe_data.get("ingredients", [])),
                        "weight_final": float(recipe_data.get("weight_final", 0.0)),
                        "portion_size": float(recipe_data.get("portion_size", 0.0)),
                        "case_measure": recipe_data.get("case_measure", ""),
                        "gluten_opt": recipe_data.get("gluten_opt", ""),
                        "lactose_opt": recipe_data.get("lactose_opt", ""),
                        "allergens_direct": json.dumps(recipe_data.get("allergens_direct", [])),
                        "allergens_deriv": json.dumps(recipe_data.get("allergens_deriv", [])),
                        "allergens_may_contain": json.dumps(recipe_data.get("allergens_may_contain", [])),
                        "product_type": recipe_data.get("product_type", ""),
                        "date_saved": recipe_data.get("date_saved", "")
                    }
                )
            return True
        except Exception as e:
            logger.error(f"Erro ao salvar receita no banco SQL: {e}", exc_info=True)
            log_db_error("save_recipe_sql_error", e)
            return False


def delete_recipe_sql(name: str, username: str, db_lock) -> bool:
    """
    Remove uma receita específica do banco de dados relacional.
    """
    engine = get_db_engine()
    if not engine:
        return False
        
    with db_lock:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM receitas WHERE LOWER(nome) = LOWER(:nome) AND LOWER(username) = LOWER(:username)"),
                    {"nome": name, "username": username}
                )
            return True
        except Exception as e:
            logger.error(f"Erro ao deletar receita do banco SQL: {e}", exc_info=True)
            log_db_error("delete_recipe_sql_error", e)
            return False

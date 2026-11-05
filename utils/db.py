import os
import json
import logging
import traceback
import urllib.parse
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)
_MODULE_VERSION = "2026.11.05.v4"

# Cache global do engine do SQLAlchemy
_db_engine = None
_db_initialized = False
_runtime_db_url = ""
_last_db_diag = ""


def _safe_float(val, default: float = 0.0) -> float:
    if val is None or pd.isna(val):
        return float(default)
    try:
        return float(val)
    except Exception:
        return float(default)


def _safe_int(val, default: int = 0) -> int:
    if val is None or pd.isna(val):
        return int(default)
    try:
        return int(float(val))
    except Exception:
        return int(default)


def _safe_str(val, default: str = "") -> str:
    if val is None or pd.isna(val):
        return default
    return str(val)

def log_db_error(msg: str, e: Exception):
    try:
        filepath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db_error.log")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"Error Message: {msg}\n")
            f.write(f"Exception: {str(e)}\n\n")
            f.write(traceback.format_exc())
    except Exception as log_ex:
        logger.error(f"Erro ao gravar log local de erro: {log_ex}")


# Novos dados cadastrais (v2026.10.28) — migração apenas ADITIVA (ADD COLUMN IF NOT EXISTS), nunca remove dados.
_USER_PROFILE_COLUMNS = [
    "nome_completo VARCHAR(255)",
    "telefone VARCHAR(20)",
    "documento_tipo VARCHAR(4)",
    "documento_enc TEXT",
    "nome_negocio VARCHAR(255)",
    "segmento VARCHAR(100)",
    "cidade_uf VARCHAR(120)",
    "marketing_optin BOOLEAN DEFAULT FALSE",
]


def init_db_safe(engine):
    """
    Inicializa as tabelas do banco de dados relacional se ainda não inicializadas.
    Não lança exceções para fora para evitar quebras no carregamento de módulos.
    Usa uma única transação para evitar múltiplas conexões TCP sequenciais.
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
                lgpd_version VARCHAR(10),
                nome_completo VARCHAR(255),
                telefone VARCHAR(20),
                documento_tipo VARCHAR(4),
                documento_enc TEXT,
                nome_negocio VARCHAR(255),
                segmento VARCHAR(100),
                cidade_uf VARCHAR(120),
                marketing_optin BOOLEAN DEFAULT FALSE
            )
            """))
            
            # Migração de coluna: Altera cpf para VARCHAR(255) caso a tabela já existisse como VARCHAR(20)
            try:
                with conn.begin_nested():
                    conn.execute(text("ALTER TABLE usuarios ALTER COLUMN cpf TYPE VARCHAR(255)"))
            except Exception:
                pass

            # Migração aditiva de colunas de perfil para bancos já existentes (na mesma conexão)
            for col_def in _USER_PROFILE_COLUMNS:
                try:
                    with conn.begin_nested():
                        conn.execute(text(f"ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS {col_def}"))
                except Exception as col_err:
                    logger.warning(f"[Database] Falha ao adicionar coluna '{col_def}': {col_err}")

            # Backfill seguro para contas existentes: preserva nome e indicador de CPF já cadastrado
            try:
                with conn.begin_nested():
                    conn.execute(text("""
                        UPDATE usuarios
                        SET nome_completo = username
                        WHERE (nome_completo IS NULL OR BTRIM(nome_completo) = '')
                          AND username IS NOT NULL
                          AND LOWER(username) <> 'admin'
                    """))
                    conn.execute(text("""
                        UPDATE usuarios
                        SET documento_tipo = 'CPF'
                        WHERE (documento_tipo IS NULL OR BTRIM(documento_tipo) = '')
                          AND cpf IS NOT NULL
                          AND BTRIM(cpf) <> ''
                    """))
            except Exception as bf_err:
                logger.warning(f"[Database] Aviso no backfill de usuários legados: {bf_err}")
            
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
                custo_embalagem FLOAT DEFAULT 0.0,
                tempo_preparo_min FLOAT DEFAULT 0.0,
                custo_hora_mao_obra FLOAT DEFAULT 0.0,
                custo_operacional_pct FLOAT DEFAULT 0.0,
                taxas_venda_pct FLOAT DEFAULT 0.0,
                margem_desejada_pct FLOAT DEFAULT 30.0,
                preco_venda_praticado FLOAT DEFAULT 0.0,
                PRIMARY KEY (nome, username)
            )
            """))

            # Migração de colunas financeiras para bancos já existentes
            for col_def in [
                "custo_embalagem FLOAT DEFAULT 0.0",
                "tempo_preparo_min FLOAT DEFAULT 0.0",
                "custo_hora_mao_obra FLOAT DEFAULT 0.0",
                "custo_operacional_pct FLOAT DEFAULT 0.0",
                "taxas_venda_pct FLOAT DEFAULT 0.0",
                "margem_desejada_pct FLOAT DEFAULT 30.0",
                "preco_venda_praticado FLOAT DEFAULT 0.0"
            ]:
                try:
                    with conn.begin_nested():
                        conn.execute(text(f"ALTER TABLE receitas ADD COLUMN IF NOT EXISTS {col_def}"))
                except Exception:
                    pass

            # Tabela de Chamados de Suporte
            conn.execute(text("""
            CREATE TABLE IF NOT EXISTS suporte_tickets (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255),
                email VARCHAR(255),
                categoria VARCHAR(255),
                assunto VARCHAR(500),
                mensagem TEXT,
                status VARCHAR(50) DEFAULT 'Aberto',
                criado_em TIMESTAMP DEFAULT NOW()
            )
            """))

            # Tabela de Ingredientes/Produtos Customizados cadastrados pelos usuários
            conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ingredientes_customizados (
                codigo VARCHAR(64) PRIMARY KEY,
                username VARCHAR(255),
                descricao VARCHAR(255),
                classe VARCHAR(100),
                fonte VARCHAR(50),
                peso_embalagem FLOAT DEFAULT 1000.0,
                preco_embalagem FLOAT DEFAULT 0.0,
                nutrientes TEXT
            )
            """))
            
        _db_initialized = True
        logger.info("[Database] Tabelas SQL verificadas/inicializadas com sucesso.")
    except Exception as e:
        logger.error(f"[Database] Erro ao inicializar tabelas do banco relacional: {e}", exc_info=True)
        log_db_error("init_db_error", e)


def _select_pg_scheme() -> str:
    """Seleciona explicitamente o driver PostgreSQL instalado no ambiente (psycopg2, psycopg ou pg8000)."""
    for mod_name, scheme in (
        ("psycopg2", "postgresql+psycopg2://"),
        ("psycopg", "postgresql+psycopg://"),
        ("pg8000", "postgresql+pg8000://"),
    ):
        try:
            __import__(mod_name)
            return scheme
        except ImportError:
            continue
    return "postgresql://"


def _sanitize_db_url(raw_url: str) -> str:
    """Normaliza a URL de conexão PostgreSQL para compatibilidade com SQLAlchemy (forçando +psycopg2) e libpq."""
    if not raw_url:
        return ""
    import re
    url = str(raw_url).strip().strip('"').strip("'")
    if re.match(r'^postgres(?:ql)?(?:\+[a-zA-Z0-9_]+)?://', url):
        scheme = _select_pg_scheme()
        url = re.sub(r'^postgres(?:ql)?(?:\+[a-zA-Z0-9_]+)?://', scheme, url, count=1)
    # Remove channel_binding=require caso presente (incompatível com algumas versões de libpq no Linux)
    if "channel_binding=" in url:
        url = re.sub(r'[?&]channel_binding=[^&]*', '', url)
        if "?" not in url and "&" in url:
            url = url.replace("&", "?", 1)
    return url


def _find_pg_url_in_mapping(obj, depth: int = 0) -> str:
    """Procura recursivamente qualquer URL postgresql:// ou postgres:// em dicts/AttrDicts (até 6 níveis)."""
    if depth > 6 or obj is None:
        return ""
    if isinstance(obj, str):
        s = obj.strip().strip('"').strip("'")
        if s.startswith(("postgresql://", "postgres://", "postgresql+", "postgres+")):
            return s
        return ""
    if hasattr(obj, "items"):
        try:
            for _k, v in obj.items():
                found = _find_pg_url_in_mapping(v, depth + 1)
                if found:
                    return found
        except Exception:
            pass
    return ""


def _candidate_secrets_paths() -> list:
    """Retorna todos os caminhos possíveis de secrets.toml (incluindo os do Streamlit Cloud)."""
    paths = []
    try:
        from streamlit import config as _st_config
        cfg_files = _st_config.get_option("secrets.files") or []
        for p in cfg_files:
            if p and p not in paths:
                paths.append(p)
    except Exception:
        pass
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for extra in (
        os.path.join(base_dir, ".streamlit", "secrets.toml"),
        os.path.expanduser("~/.streamlit/secrets.toml"),
        os.path.join(os.getcwd(), ".streamlit", "secrets.toml"),
        "/mount/src/rotulo-facil-app/.streamlit/secrets.toml",
        "/home/appuser/.streamlit/secrets.toml",
    ):
        if extra not in paths:
            paths.append(extra)
    return paths


def get_db_engine():
    """
    Retorna ou inicializa o engine do SQLAlchemy.
    Suporta leitura a partir de:
    1. URL definida em tempo de execução (_runtime_db_url) ou variáveis de ambiente
    2. Streamlit Secrets (qualquer nível: [connections.sql], DATABASE_URL, etc.)
    3. Leitura direta de todos os arquivos secrets.toml possíveis (mesmo se houver erro de sintaxe TOML)
    """
    global _db_engine, _last_db_diag
    if _db_engine is not None:
        return _db_engine

    diag_notes = []
    db_url = (
        _runtime_db_url
        or os.environ.get("DATABASE_URL")
        or os.environ.get("POSTGRES_URL")
        or os.environ.get("NEON_DATABASE_URL")
    )
    
    if not db_url:
        try:
            # 1. Tentar ler URL em st.secrets["connections"]["sql"]
            if "connections" in st.secrets and "sql" in st.secrets["connections"]:
                sql_secrets = st.secrets["connections"]["sql"]
                if isinstance(sql_secrets, str) and sql_secrets.strip():
                    db_url = sql_secrets.strip()
                elif hasattr(sql_secrets, "get"):
                    if sql_secrets.get("url"):
                        db_url = str(sql_secrets["url"]).strip()
                    else:
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
                        else:
                            diag_notes.append(
                                "A seção `[connections.sql]` foi encontrada nos Secrets, mas está vazia (faltou a linha `url = \"postgresql://...\"` logo abaixo dela)."
                            )
        except Exception as e_sec1:
            diag_notes.append(f"Aviso ao ler `[connections.sql]` em `st.secrets`: {e_sec1}")

    if not db_url:
        try:
            # 2. Busca recursiva em qualquer chave/nível de st.secrets
            db_url = _find_pg_url_in_mapping(st.secrets)
            if not db_url:
                top_keys = list(st.secrets.keys())
                if "connections" in st.secrets and hasattr(st.secrets["connections"], "keys"):
                    conn_keys = list(st.secrets["connections"].keys())
                    diag_notes.append(f"Chaves encontradas em `st.secrets`: {top_keys} (`connections`: {conn_keys}), porém nenhuma URL `postgresql://` foi localizada.")
                else:
                    diag_notes.append(f"Chaves encontradas em `st.secrets`: {top_keys} (nenhuma URL `postgresql://` localizada).")
        except Exception as e_sec2:
            diag_notes.append(f"Erro ao interpretar `st.secrets` (verifique se há quebras de linha ou aspas inválidas no TOML): {e_sec2}")

    if not db_url:
        # 3. Fallback: Ler diretamente todos os arquivos secrets.toml no disco (funciona mesmo se o TOML tiver erro de sintaxe!)
        import re
        for secrets_path in _candidate_secrets_paths():
            try:
                if os.path.isfile(secrets_path):
                    with open(secrets_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    # Captura qualquer URL postgresql:// ou postgres:// diretamente no texto bruto
                    m_pg = re.search(r'(postgres(?:ql)?(?:\+[a-zA-Z0-9_]+)?://[^\s"\'\]]+)', content)
                    if m_pg:
                        db_url = m_pg.group(1).strip()
                        break
                    match_url = re.search(r'(?:url|DATABASE_URL|POSTGRES_URL)\s*=\s*["\']([^"\']+)["\']', content)
                    if match_url:
                        db_url = match_url.group(1).strip()
                        break
            except Exception:
                pass

    db_url = _sanitize_db_url(db_url)
    if db_url:
        logger.info("[Database] Inicializando engine SQLAlchemy com pool de conexões otimizado...")
        try:
            _db_engine = create_engine(
                db_url,
                pool_pre_ping=True,
                pool_recycle=1800,
                pool_size=5,
                max_overflow=10,
                connect_args={"connect_timeout": 10},
            )
            # Inicializar tabelas de forma segura e tardia (lazy)
            init_db_safe(_db_engine)
            _last_db_diag = "Conectado com sucesso."
            return _db_engine
        except Exception as e:
            _last_db_diag = f"URL encontrada, mas falha ao criar conexão SQLAlchemy: {e}"
            logger.error(f"[Database] Erro ao criar engine do SQLAlchemy: {e}")
            log_db_error("create_engine_error", e)
    else:
        _last_db_diag = " | ".join(diag_notes) if diag_notes else "Nenhuma URL `postgresql://` encontrada nas variáveis de ambiente ou nos Secrets."
            
    return None


def get_db_diagnostics() -> str:
    """Retorna o diagnóstico detalhado da última tentativa de conexão com o banco."""
    return _last_db_diag or "Sem diagnóstico registrado."


def set_runtime_db_url(raw_url: str) -> tuple:
    """Permite configurar e conectar a URL do banco imediatamente em memória e em .streamlit/secrets.toml."""
    global _db_engine, _db_initialized, _runtime_db_url
    clean = _sanitize_db_url(raw_url)
    if not clean.startswith("postgresql"):
        return False, "A URL deve começar com `postgresql://`."
    _runtime_db_url = clean
    _db_engine = None
    _db_initialized = False
    os.environ["DATABASE_URL"] = clean
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sec_dir = os.path.join(base_dir, ".streamlit")
        os.makedirs(sec_dir, exist_ok=True)
        sec_file = os.path.join(sec_dir, "secrets.toml")
        if not os.path.exists(sec_file):
            with open(sec_file, "w", encoding="utf-8") as f:
                f.write(f'[connections.sql]\nurl = "{clean}"\n')
    except Exception:
        pass
    eng = get_db_engine()
    if eng is not None:
        return True, "Banco de dados PostgreSQL conectado com sucesso!"
    return False, f"Não foi possível conectar: {_last_db_diag}"


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
            
            # Converter campos JSON textuais e tratar NULL/NaN do pandas de volta para tipos Python seguros
            for u in users:
                u["username"] = _safe_str(u.get("username"), "")
                u["email"] = _safe_str(u.get("email"), "")
                u["cpf"] = _safe_str(u.get("cpf"), "")
                u["password_hash"] = _safe_str(u.get("password_hash"), "")
                u["id_transacao_pagamento"] = _safe_str(u.get("id_transacao_pagamento"), "")
                u["lgpd_accepted_at"] = _safe_str(u.get("lgpd_accepted_at"), "")
                u["lgpd_version"] = _safe_str(u.get("lgpd_version"), "1.0")
                for _k in ("nome_completo", "telefone", "documento_tipo", "documento_enc", "nome_negocio", "segmento", "cidade_uf"):
                    u[_k] = _safe_str(u.get(_k), "")
                mk_raw = u.get("marketing_optin", False)
                u["marketing_optin"] = False if (mk_raw is None or pd.isna(mk_raw)) else bool(mk_raw)
                is_adm_raw = u.get("is_admin", False)
                u["is_admin"] = False if (is_adm_raw is None or pd.isna(is_adm_raw)) else bool(is_adm_raw)
                u["creditos_disponiveis"] = _safe_int(u.get("creditos_disponiveis"), 1)
                tx_raw = u.get("transacoes_processadas")
                if tx_raw and not pd.isna(tx_raw):
                    try:
                        u["transacoes_processadas"] = json.loads(tx_raw) if isinstance(tx_raw, str) else list(tx_raw)
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
                        INSERT INTO usuarios (username, email, cpf, password_hash, is_admin, creditos_disponiveis, transacoes_processadas, id_transacao_pagamento, lgpd_accepted_at, lgpd_version,
                                              nome_completo, telefone, documento_tipo, documento_enc, nome_negocio, segmento, cidade_uf, marketing_optin)
                        VALUES (:username, :email, :cpf, :password_hash, :is_admin, :creditos_disponiveis, :transacoes_processadas, :id_transacao_pagamento, :lgpd_accepted_at, :lgpd_version,
                                :nome_completo, :telefone, :documento_tipo, :documento_enc, :nome_negocio, :segmento, :cidade_uf, :marketing_optin)
                        ON CONFLICT (username) DO UPDATE SET
                            nome_completo = EXCLUDED.nome_completo,
                            telefone = EXCLUDED.telefone,
                            documento_tipo = EXCLUDED.documento_tipo,
                            documento_enc = EXCLUDED.documento_enc,
                            nome_negocio = EXCLUDED.nome_negocio,
                            segmento = EXCLUDED.segmento,
                            cidade_uf = EXCLUDED.cidade_uf,
                            marketing_optin = EXCLUDED.marketing_optin,
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
                            "lgpd_version": u.get("lgpd_version", ""),
                            "nome_completo": u.get("nome_completo", "") or "",
                            "telefone": u.get("telefone", "") or "",
                            "documento_tipo": u.get("documento_tipo", "") or "",
                            "documento_enc": u.get("documento_enc", "") or "",
                            "nome_negocio": u.get("nome_negocio", "") or "",
                            "segmento": u.get("segmento", "") or "",
                            "cidade_uf": u.get("cidade_uf", "") or "",
                            "marketing_optin": bool(u.get("marketing_optin", False)),
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


def add_user_credits_sql(target_identifier: str, credits_to_add: int, payment_id: str, db_lock) -> tuple:
    """
    Atualiza atômica e diretamente os créditos do usuário no banco SQL, prevenindo race conditions e evitando ler/escrever a tabela inteira.
    Retorna (sucesso: bool, mensagem: str).
    """
    engine = get_db_engine()
    if not engine:
        return False, "Engine SQL não disponível."

    with db_lock:
        try:
            with engine.begin() as conn:
                # 1. Localizar o usuário por username ou email
                result = conn.execute(
                    text("SELECT username, creditos_disponiveis, transacoes_processadas FROM usuarios WHERE LOWER(username) = LOWER(:target) OR LOWER(email) = LOWER(:target) LIMIT 1"),
                    {"target": target_identifier.strip().lower()}
                ).fetchone()

                if not result:
                    return False, f"Usuário '{target_identifier}' não foi encontrado no banco de dados SQL."

                username, current_credits, tx_json = result[0], result[1], result[2]
                
                try:
                    tx_list = json.loads(tx_json) if tx_json else []
                except Exception:
                    tx_list = []

                if payment_id in tx_list:
                    return True, f"Créditos do pagamento {payment_id} já haviam sido aplicados anteriormente para o usuário '{username}'."

                tx_list.append(payment_id)
                new_tx_json = json.dumps(tx_list)
                new_credits = (current_credits or 0) + credits_to_add

                conn.execute(
                    text("""
                    UPDATE usuarios
                    SET creditos_disponiveis = :new_credits,
                        transacoes_processadas = :tx_json,
                        id_transacao_pagamento = :payment_id
                    WHERE username = :username
                    """),
                    {
                        "new_credits": new_credits,
                        "tx_json": new_tx_json,
                        "payment_id": payment_id,
                        "username": username
                    }
                )

            # Invalidar cache do Streamlit se disponível
            try:
                if exists():
                    get_user_credits_cached.clear()
            except Exception:
                pass

            return True, f"Sucesso: Adicionados {credits_to_add} créditos para o usuário '{username}' (Transação: {payment_id})."
        except Exception as e:
            logger.error(f"Erro ao adicionar créditos via SQL para {target_identifier}: {e}", exc_info=True)
            return False, f"Erro no banco de dados relacional ao adicionar créditos: {e}"


def consume_user_credit_sql(username: str, db_lock) -> tuple:
    """
    Debita 1 crédito do usuário de forma atômica no banco SQL:
    - Se o usuário for administrador, não desconta e retorna sucesso.
    - Se for usuário comum, executa UPDATE condicional (creditos_disponiveis > 0) em uma única instrução,
      impedindo saldo negativo ou débito duplicado em cliques concorrentes.
    Retorna (sucesso: bool, mensagem: str).
    """
    engine = get_db_engine()
    if not engine:
        return False, "Engine SQL não disponível."

    uname_clean = (username or "").strip()
    if not uname_clean:
        return False, "Usuário não identificado."

    with db_lock:
        try:
            with engine.begin() as conn:
                row = conn.execute(
                    text("SELECT username, is_admin, creditos_disponiveis FROM usuarios WHERE LOWER(username) = LOWER(:uname) LIMIT 1"),
                    {"uname": uname_clean}
                ).fetchone()

                if not row:
                    return False, f"Usuário '{uname_clean}' não encontrado."

                db_uname, is_admin_flag, current_credits = row[0], bool(row[1]), int(row[2] or 0)
                if is_admin_flag:
                    return True, "Administrador (créditos ilimitados)."

                if current_credits <= 0:
                    return False, "Saldo insuficiente de créditos."

                upd = conn.execute(
                    text("""
                    UPDATE usuarios
                    SET creditos_disponiveis = creditos_disponiveis - 1
                    WHERE username = :uname AND creditos_disponiveis > 0
                    """),
                    {"uname": db_uname}
                )
                if upd.rowcount <= 0:
                    return False, "Não foi possível debitar o crédito (saldo insuficiente)."

                remaining = current_credits - 1

            try:
                if exists():
                    get_user_credits_cached.clear()
            except Exception:
                pass

            logger.info(f"Crédito debitado atomicamente via SQL para '{db_uname}'. Restantes: {remaining}")
            return True, f"Crédito debitado com sucesso. Restantes: {remaining}"
        except Exception as e:
            logger.error(f"Erro ao debitar crédito via SQL para '{uname_clean}': {e}", exc_info=True)
            return False, f"Erro ao debitar crédito no banco de dados: {e}"


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
            
            # Converter colunas de texto JSON e numéricas para objetos Python (tratando NULL/NaN do pandas)
            for r in recipes:
                r["nome"] = _safe_str(r.get("nome"), "")
                r["username"] = _safe_str(r.get("username"), "")
                r["nome_produto"] = _safe_str(r.get("nome_produto"), "")
                r["case_measure"] = _safe_str(r.get("case_measure"), "1 unidade")
                r["gluten_opt"] = _safe_str(r.get("gluten_opt"), "NÃO CONTÉM GLÚTEN")
                r["lactose_opt"] = _safe_str(r.get("lactose_opt"), "NÃO CONTÉM LACTOSE")
                r["product_type"] = _safe_str(r.get("product_type"), "Sólido ou Semissólido")
                r["date_saved"] = _safe_str(r.get("date_saved"), "")

                r["peso_embalagem"] = _safe_float(r.get("peso_embalagem"), 0.0)
                r["weight_final"] = _safe_float(r.get("weight_final"), 0.0)
                r["portion_size"] = _safe_float(r.get("portion_size"), 60.0)
                
                # Campos financeiros
                r["custo_embalagem"] = _safe_float(r.get("custo_embalagem"), 0.0)
                r["tempo_preparo_min"] = _safe_float(r.get("tempo_preparo_min"), 0.0)
                r["custo_hora_mao_obra"] = _safe_float(r.get("custo_hora_mao_obra"), 0.0)
                r["custo_operacional_pct"] = _safe_float(r.get("custo_operacional_pct"), 0.0)
                r["taxas_venda_pct"] = _safe_float(r.get("taxas_venda_pct"), 0.0)
                r["margem_desejada_pct"] = _safe_float(r.get("margem_desejada_pct"), 30.0)
                r["preco_venda_praticado"] = _safe_float(r.get("preco_venda_praticado"), 0.0)
                
                # Deserializar ingredientes e alérgenos
                for field in ["ingredients", "allergens_direct", "allergens_deriv", "allergens_may_contain"]:
                    raw_f = r.get(field)
                    if raw_f and not pd.isna(raw_f):
                        try:
                            r[field] = json.loads(raw_f) if isinstance(raw_f, str) else list(raw_f)
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
                        allergens_direct, allergens_deriv, allergens_may_contain, product_type, date_saved,
                        custo_embalagem, tempo_preparo_min, custo_hora_mao_obra, custo_operacional_pct,
                        taxas_venda_pct, margem_desejada_pct, preco_venda_praticado
                    ) VALUES (
                        :nome, :username, :nome_produto, :peso_embalagem, :ingredients,
                        :weight_final, :portion_size, :case_measure, :gluten_opt, :lactose_opt,
                        :allergens_direct, :allergens_deriv, :allergens_may_contain, :product_type, :date_saved,
                        :custo_embalagem, :tempo_preparo_min, :custo_hora_mao_obra, :custo_operacional_pct,
                        :taxas_venda_pct, :margem_desejada_pct, :preco_venda_praticado
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
                        "date_saved": recipe_data.get("date_saved", ""),
                        "custo_embalagem": float(recipe_data.get("custo_embalagem", 0.0)),
                        "tempo_preparo_min": float(recipe_data.get("tempo_preparo_min", 0.0)),
                        "custo_hora_mao_obra": float(recipe_data.get("custo_hora_mao_obra", 0.0)),
                        "custo_operacional_pct": float(recipe_data.get("custo_operacional_pct", 0.0)),
                        "taxas_venda_pct": float(recipe_data.get("taxas_venda_pct", 0.0)),
                        "margem_desejada_pct": float(recipe_data.get("margem_desejada_pct", 30.0)),
                        "preco_venda_praticado": float(recipe_data.get("preco_venda_praticado", 0.0))
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


def save_ticket_sql(username: str, email: str, categoria: str, assunto: str, mensagem: str) -> int:
    """
    Grava um novo chamado de suporte no banco de dados.
    Retorna o ID gerado do ticket, ou -1 em caso de erro.
    """
    engine = get_db_engine()
    if not engine:
        return -1
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text("""
                INSERT INTO suporte_tickets (username, email, categoria, assunto, mensagem, status, criado_em)
                VALUES (:username, :email, :categoria, :assunto, :mensagem, 'Aberto', NOW())
                RETURNING id
                """),
                {
                    "username": username,
                    "email": email,
                    "categoria": categoria,
                    "assunto": assunto,
                    "mensagem": mensagem
                }
            )
            ticket_id = result.fetchone()[0]
            logger.info(f"[Suporte] Ticket #{ticket_id} criado para '{username}'.")
            return ticket_id
    except Exception as e:
        logger.error(f"[Suporte] Erro ao salvar ticket: {e}", exc_info=True)
        return -1


def load_tickets_sql(status_filter: str = None) -> list:
    """
    Carrega todos os chamados de suporte do banco de dados, ordenados pelos mais recentes.
    Filtra por status se fornecido (ex: 'Aberto', 'Resolvido').
    """
    engine = get_db_engine()
    if not engine:
        return []
    try:
        if status_filter:
            df = pd.read_sql(
                text("SELECT * FROM suporte_tickets WHERE status = :s ORDER BY criado_em DESC"),
                engine,
                params={"s": status_filter}
            )
        else:
            df = pd.read_sql(
                text("SELECT * FROM suporte_tickets ORDER BY criado_em DESC"),
                engine
            )
        return df.to_dict(orient="records")
    except Exception as e:
        logger.error(f"[Suporte] Erro ao carregar tickets: {e}", exc_info=True)
        return []


def update_ticket_status_sql(ticket_id: int, new_status: str) -> bool:
    """
    Atualiza o status de um chamado de suporte.
    """
    engine = get_db_engine()
    if not engine:
        return False
    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE suporte_tickets SET status = :status WHERE id = :id"),
                {"status": new_status, "id": ticket_id}
            )
        return True
    except Exception as e:
        logger.error(f"[Suporte] Erro ao atualizar status do ticket #{ticket_id}: {e}", exc_info=True)
        return False


def save_custom_ingredient_sql(item: dict) -> bool:
    """Salva ou atualiza um ingrediente/produto customizado no PostgreSQL."""
    engine = get_db_engine()
    if not engine:
        return False
    try:
        nut_json = json.dumps(item.get("n", {}), ensure_ascii=False)
        with engine.begin() as conn:
            conn.execute(
                text("""
                INSERT INTO ingredientes_customizados (
                    codigo, username, descricao, classe, fonte, peso_embalagem, preco_embalagem, nutrientes
                ) VALUES (
                    :codigo, :username, :descricao, :classe, :fonte, :peso_embalagem, :preco_embalagem, :nutrientes
                )
                ON CONFLICT (codigo) DO UPDATE SET
                    descricao = EXCLUDED.descricao,
                    peso_embalagem = EXCLUDED.peso_embalagem,
                    preco_embalagem = EXCLUDED.preco_embalagem,
                    nutrientes = EXCLUDED.nutrientes
                """),
                {
                    "codigo": _safe_str(item.get("c"), "CAD-0001"),
                    "username": _safe_str(item.get("username"), ""),
                    "descricao": _safe_str(item.get("d"), ""),
                    "classe": _safe_str(item.get("g"), "Cadastrado Manualmente"),
                    "fonte": _safe_str(item.get("f"), "CADASTRO"),
                    "peso_embalagem": _safe_float(item.get("pkg_g"), 1000.0),
                    "preco_embalagem": _safe_float(item.get("price"), 0.0),
                    "nutrientes": nut_json,
                }
            )
        return True
    except Exception as e:
        logger.error(f"Erro ao salvar ingrediente customizado no SQL: {e}", exc_info=True)
        return False


def load_custom_ingredients_sql(username: str = None) -> list:
    """Carrega os ingredientes/produtos customizados salvos no PostgreSQL."""
    engine = get_db_engine()
    if not engine:
        return []
    try:
        if username:
            df = pd.read_sql(
                text("SELECT * FROM ingredientes_customizados WHERE username IS NULL OR username = '' OR LOWER(username) = LOWER(:u)"),
                engine,
                params={"u": username}
            )
        else:
            df = pd.read_sql("SELECT * FROM ingredientes_customizados", engine)
        items = []
        for _, row in df.iterrows():
            try:
                nut = json.loads(row.get("nutrientes") or "{}")
            except Exception:
                nut = {}
            items.append({
                "c": _safe_str(row.get("codigo"), ""),
                "d": _safe_str(row.get("descricao"), ""),
                "g": _safe_str(row.get("classe"), "Cadastrado Manualmente"),
                "f": _safe_str(row.get("fonte"), "CADASTRO"),
                "pkg_g": _safe_float(row.get("peso_embalagem"), 1000.0),
                "price": _safe_float(row.get("preco_embalagem"), 0.0),
                "n": nut,
            })
        return items
    except Exception as e:
        logger.warning(f"Aviso ao carregar ingredientes customizados do SQL: {e}")
        return []

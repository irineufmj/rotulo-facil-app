import os
import json
import logging
import traceback
import pandas as pd
import streamlit as st
from sqlalchemy import text

logger = logging.getLogger(__name__)

def log_db_error(msg: str, e: Exception):
    try:
        filepath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db_error.log")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"Error Message: {msg}\n")
            f.write(f"Exception: {str(e)}\n\n")
            f.write(traceback.format_exc())
    except Exception as log_ex:
        logger.error(f"Erro ao gravar log local de erro: {log_ex}")

def is_sql_configured() -> bool:
    """
    Retorna True se houver uma configuração de banco de dados SQL activa nos secrets do Streamlit.
    """
    try:
        return "connections" in st.secrets and "sql" in st.secrets["connections"]
    except Exception:
        return False

def init_db():
    """
    Inicializa as tabelas do banco de dados relacional se estiver configurado.
    """
    if not is_sql_configured():
        return
        
    try:
        conn = st.connection("sql")
        with conn.session as session:
            # Tabela de Usuários
            session.execute(text("""
            CREATE TABLE IF NOT EXISTS usuarios (
                username VARCHAR(255) PRIMARY KEY,
                email VARCHAR(255),
                cpf VARCHAR(20),
                password_hash TEXT,
                is_admin BOOLEAN,
                creditos_disponiveis INT,
                transacoes_processadas TEXT, -- Salvo como String JSON
                id_transacao_pagamento VARCHAR(255),
                lgpd_accepted_at VARCHAR(100),
                lgpd_version VARCHAR(10)
            )
            """))
            
            # Tabela de Receitas
            session.execute(text("""
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
            session.commit()
    except Exception as e:
        logger.error(f"Erro ao inicializar tabelas do banco relacional: {e}", exc_info=True)
        log_db_error("init_db_error", e)
        st.error(f"Erro de Conexão com o Banco de Dados (init_db): {e}")

# Inicializar tabelas em tempo de import
init_db()

def load_users_sql(db_lock) -> list:
    """
    Carrega todos os usuários do banco de dados relacional.
    """
    with db_lock:
        try:
            conn = st.connection("sql")
            df = conn.query("SELECT * FROM usuarios", ttl=0)
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
            return []

def save_users_sql(users: list, db_lock) -> bool:
    """
    Salva a lista completa de usuários no banco de dados relacional de forma agnóstica.
    """
    with db_lock:
        try:
            conn = st.connection("sql")
            with conn.session as session:
                session.execute(text("DELETE FROM usuarios"))
                for u in users:
                    tx_json = json.dumps(u.get("transacoes_processadas", []))
                    session.execute(
                        text("""
                        INSERT INTO usuarios (username, email, cpf, password_hash, is_admin, creditos_disponiveis, transacoes_processadas, id_transacao_pagamento, lgpd_accepted_at, lgpd_version)
                        VALUES (:username, :email, :cpf, :password_hash, :is_admin, :creditos_disponiveis, :transacoes_processadas, :id_transacao_pagamento, :lgpd_accepted_at, :lgpd_version)
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
                session.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao gravar usuários no banco SQL: {e}", exc_info=True)
            log_db_error("save_users_sql_error", e)
            st.error(f"Erro de Banco de Dados (save_users_sql): {e}")
            return False

def load_recipes_sql(db_lock) -> list:
    """
    Carrega todas as receitas salvas no banco de dados relacional.
    """
    with db_lock:
        try:
            conn = st.connection("sql")
            df = conn.query("SELECT * FROM receitas", ttl=0)
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
    username = recipe_data.get("username", "")
    with db_lock:
        try:
            conn = st.connection("sql")
            with conn.session as session:
                session.execute(
                    text("DELETE FROM receitas WHERE LOWER(nome) = LOWER(:nome) AND LOWER(username) = LOWER(:username)"),
                    {"nome": name, "username": username}
                )
                
                session.execute(
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
                session.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao salvar receita no banco SQL: {e}", exc_info=True)
            log_db_error("save_recipe_sql_error", e)
            return False

def delete_recipe_sql(name: str, username: str, db_lock) -> bool:
    """
    Remove uma receita específica do banco de dados relacional.
    """
    with db_lock:
        try:
            conn = st.connection("sql")
            with conn.session as session:
                session.execute(
                    text("DELETE FROM receitas WHERE LOWER(nome) = LOWER(:nome) AND LOWER(username) = LOWER(:username)"),
                    {"nome": name, "username": username}
                )
                session.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao deletar receita do banco SQL: {e}", exc_info=True)
            log_db_error("delete_recipe_sql_error", e)
            return False

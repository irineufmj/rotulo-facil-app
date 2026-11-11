import os
import sys
import json
import tempfile
import threading
import logging
import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)
_MODULE_VERSION = "2026.11.11.v3"
_INTERNAL_LOCK = threading.RLock()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUSTOM_CSV_PATH = os.path.join(BASE_DIR, "custom_ingredients.csv")
RECIPES_JSON_PATH = os.path.join(BASE_DIR, "receitas_salvas.json")

def safe_save_json(filepath, data):
    dir_name = os.path.dirname(filepath)
    fd, temp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(temp_path, filepath)
        return True
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        logger.error(f"Erro ao salvar arquivo {os.path.basename(filepath)}: {e}", exc_info=True)
        return False

@st.cache_data
def load_unified_data():
    json_path = os.path.join(BASE_DIR, "alimentos_unified.json")
    
    with open(json_path, "r", encoding="utf-8-sig") as f:
        foods = json.load(f)
    
    if not os.path.exists(CUSTOM_CSV_PATH):
        df_init = pd.DataFrame(columns=[
            "codigo", "descricao", "classe", "fonte",
            "Energia (kcal)", "Carboidrato total (g)",
            "Açúcares adicionados (g)", "Proteína (g)",
            "Lipídios (g)", "Gorduras saturadas (g)",
            "Gorduras trans (g)", "Fibra alimentar (g)",
            "Sódio (mg)"
        ])
        df_init.to_csv(CUSTOM_CSV_PATH, index=False, encoding="utf-8-sig")
    
    try:
        custom_df = pd.read_csv(CUSTOM_CSV_PATH, encoding="utf-8-sig")
        for idx, row in custom_df.iterrows():
            nut_dict = {}
            for col in custom_df.columns:
                if col not in ["codigo", "descricao", "classe", "fonte"] and pd.notna(row[col]):
                    nut_dict[col] = float(row[col])
            
            if "Carboidrato total (g)" in nut_dict:
                nut_dict["Carboidrato disponível (g)"] = nut_dict.get("Carboidrato disponível (g)", nut_dict["Carboidrato total (g)"])
                nut_dict["Açúcares totais (g)"] = max(
                    float(nut_dict.get("Açúcares totais (g)", 0.0) or 0.0),
                    float(nut_dict.get("Açúcares adicionados (g)", 0.0) or 0.0),
                )
            
            foods.append({
                "c": row["codigo"],
                "d": row["descricao"],
                "g": row["classe"],
                "f": row["fonte"],
                "n": nut_dict
            })
    except Exception as e:
        st.sidebar.error(f"Erro ao ler ingredientes manuais: {e}")
        
    return foods

@st.cache_data(ttl=30)
def _cached_recipes_sql(username_key: str) -> list:
    from utils.db import load_recipes_sql
    return load_recipes_sql(_INTERNAL_LOCK, username_key or "")


@st.cache_data(ttl=30)
def _cached_custom_ingredients_sql(username_key: str) -> list:
    from utils.db import load_custom_ingredients_sql
    return load_custom_ingredients_sql(username_key or None)


def invalidate_data_caches():
    """Limpa caches locais de receitas e ingredientes customizados após qualquer escrita."""
    try:
        _cached_recipes_sql.clear()
    except Exception:
        pass
    try:
        _cached_custom_ingredients_sql.clear()
    except Exception:
        pass


try:
    from utils.db import register_cache_clear_callback
    register_cache_clear_callback(invalidate_data_caches)
except Exception:
    pass


def load_saved_recipes(db_lock, username=None):
    from utils.db import is_sql_configured, load_recipes_sql, save_recipe_sql
    if is_sql_configured():
        uname_key = (username or "").strip()
        # Migração automática única por processo: só roda se a tabela inteira de receitas estiver vazia
        reg = getattr(sys, "_rotulei_db_registry", {})
        if not reg.get("legacy_recipes_migrated") and os.path.exists(RECIPES_JSON_PATH):
            reg["legacy_recipes_migrated"] = True
            try:
                all_sql_recipes = load_recipes_sql(db_lock, "")
                if len(all_sql_recipes) == 0:
                    with open(RECIPES_JSON_PATH, "r", encoding="utf-8") as f:
                        local_recipes = json.load(f)
                    for lr in local_recipes:
                        save_recipe_sql(lr["nome"], lr, db_lock)
                    invalidate_data_caches()
                    logger.info("Migração automática única de receitas locais para o banco SQL concluída!")
            except Exception as mig_err:
                logger.error(f"Erro na migração automática de receitas para SQL: {mig_err}", exc_info=True)
        return [dict(r) for r in _cached_recipes_sql(uname_key)]
        
    with db_lock:
        if not os.path.exists(RECIPES_JSON_PATH):
            return []
        try:
            with open(RECIPES_JSON_PATH, "r", encoding="utf-8") as f:
                all_recipes = json.load(f)
            if username:
                return [r for r in all_recipes if r.get("username", "") == "" or r.get("username", "").lower() == username.lower()]
            return all_recipes
        except Exception as e:
            logger.error(f"Erro ao carregar receitas salvas: {e}", exc_info=True)
            st.error(f"Erro ao carregar receitas salvas: {e}")
            return []

def save_recipe(name, db_lock):
    username = st.session_state.get("username", "")
    new_recipe = {
        "nome": name,
        "username": username,
        "nome_produto": st.session_state.get("nome_produto", ""),
        "peso_embalagem": float(st.session_state.get("peso_embalagem", 0.0)),
        "ingredients": st.session_state.recipe,
        "weight_final": st.session_state.weight_final,
        "portion_size": st.session_state.portion_size,
        "case_measure": st.session_state.case_measure,
        "gluten_opt": st.session_state.gluten_opt,
        "lactose_opt": st.session_state.lactose_opt,
        "allergens_direct": st.session_state.allergens_direct,
        "allergens_deriv": st.session_state.allergens_deriv,
        "allergens_may_contain": st.session_state.allergens_may_contain,
        "product_type": st.session_state.product_type,
        "date_saved": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "custo_embalagem": float(st.session_state.get("custo_embalagem", 0.0)),
        "tempo_preparo_min": float(st.session_state.get("tempo_preparo_min", 0.0)),
        "custo_hora_mao_obra": float(st.session_state.get("custo_hora_mao_obra", 0.0)),
        "custo_operacional_pct": float(st.session_state.get("custo_operacional_pct", 0.0)),
        "taxas_venda_pct": float(st.session_state.get("taxas_venda_pct", 0.0)),
        "margem_desejada_pct": float(st.session_state.get("margem_desejada_pct", 30.0)),
        "preco_venda_praticado": float(st.session_state.get("preco_venda_praticado", 0.0))
    }

    from utils.db import is_sql_configured, save_recipe_sql
    if is_sql_configured():
        ok = save_recipe_sql(name, new_recipe, db_lock)
        invalidate_data_caches()
        return ok

    with db_lock:
        recipes = load_saved_recipes(db_lock)
        existing_idx = -1
        for idx, r in enumerate(recipes):
            recipe_username = r.get("username", "")
            if r["nome"].lower() == name.lower() and (recipe_username == "" or recipe_username.lower() == username.lower()):
                existing_idx = idx
                break
                
        if existing_idx >= 0:
            recipes[existing_idx] = new_recipe
        else:
            recipes.append(new_recipe)
            
        ok = safe_save_json(RECIPES_JSON_PATH, recipes)
        invalidate_data_caches()
        return ok

def delete_recipe(name, db_lock):
    username = st.session_state.get("username", "")
    from utils.db import is_sql_configured, delete_recipe_sql
    if is_sql_configured():
        ok = delete_recipe_sql(name, username, db_lock)
        invalidate_data_caches()
        return ok

    with db_lock:
        recipes = load_saved_recipes(db_lock)
        recipes = [r for r in recipes if r["nome"].lower() != name.lower() or (r.get("username", "") != "" and r.get("username", "").lower() != username.lower())]
        ok = safe_save_json(RECIPES_JSON_PATH, recipes)
        invalidate_data_caches()
        return ok


FREE_RECIPE_LIMIT = 3


def get_user_plan_status(username: str, db_lock) -> dict:
    """
    Retorna o status do plano do usuário (Freemium até 3 fichas salvas vs. Pro Ilimitado).
    Usa consulta pontual `get_user_sql` e cache de receitas para evitar `SELECT * FROM usuarios` a cada clique.
    """
    from utils.db import is_sql_configured, get_user_sql
    from utils.auth import load_users
    uname = (username or "").strip()
    user_recipes = load_saved_recipes(db_lock, uname) if uname else []
    saved_count = len(user_recipes)
    existing_names = {r.get("nome", "").strip().lower() for r in user_recipes}

    is_pro = False
    try:
        if uname:
            if is_sql_configured():
                u_obj = get_user_sql(uname)
            else:
                all_users = load_users(db_lock)
                u_obj = next((u for u in all_users if u.get("username", "").lower() == uname.lower()), None)
            if u_obj:
                txs = u_obj.get("transacoes_processadas", []) or []
                creds = int(u_obj.get("creditos_disponiveis", 0) or 0)
                if u_obj.get("is_admin", False) or len(txs) > 0 or creds >= 3:
                    is_pro = True
    except Exception as e:
        logger.warning(f"Erro ao verificar plano do usuário '{uname}': {e}")

    remaining_free = max(0, FREE_RECIPE_LIMIT - saved_count)
    plan_label = "💎 Plano Pro (Fichas Ilimitadas)" if is_pro else f"🌱 Plano Grátis ({saved_count}/{FREE_RECIPE_LIMIT} fichas salvas)"

    return {
        "is_pro": is_pro,
        "saved_count": saved_count,
        "free_limit": FREE_RECIPE_LIMIT,
        "remaining_free": remaining_free,
        "existing_names": existing_names,
        "plan_label": plan_label
    }


def can_user_save_recipe(username: str, recipe_name: str, db_lock) -> tuple:
    """
    Verifica se a usuária pode salvar a ficha técnica:
    - Sempre permitido se for Pro/Assinante/Admin
    - Sempre permitido se estiver atualizando uma das 3 fichas já salvas
    - Permitido para novas fichas se tiver menos de 3 fichas salvas no Plano Grátis
    """
    status = get_user_plan_status(username, db_lock)
    clean_name = (recipe_name or "").strip().lower()
    if status["is_pro"]:
        return True, ""
    if clean_name in status["existing_names"]:
        return True, ""
    if status["saved_count"] < status["free_limit"]:
        return True, ""
    return (
        False,
        f"Você já utilizou suas {status['free_limit']} Fichas Técnicas do Plano Gratuito! "
        "Para salvar fichas ilimitadas, ative o Plano Confeiteira Pro (R$ 19,90/mês) na aba 'Meu Perfil' "
        "ou sobrescreva uma das suas fichas existentes."
    )



def get_recipes_as_ingredients(db_lock, username):
    """
    Transforma as receitas salvas do usuário (ex: molhos, coberturas, recheios, massas-base)
    em insumos prontos para uso em outras receitas, trazendo seu peso de rendimento e custo real.
    """
    from utils.data_loader import load_saved_recipes
    from utils.calculations import get_num_val, NUTRIENT_KEY_MAPPING
    recipes = load_saved_recipes(db_lock, username)
    recipe_ingredients = []
    for idx, r in enumerate(recipes):
        r_user = r.get("username", "")
        if r_user == "" or (username and r_user.lower() == username.lower()):
            ings = r.get("ingredients", []) or []
            sum_ing_w = sum(float(ing.get("w", 0.0) or 0.0) for ing in ings)
            w_final = float(r.get("weight_final", 0.0) or 0.0)
            if w_final <= 0:
                w_final = sum_ing_w
            if w_final <= 0:
                continue
            
            raw_totals = {k: 0.0 for k in NUTRIENT_KEY_MAPPING.keys()}
            raw_totals["Açúcares totais (g)"] = 0.0
            total_cost = 0.0
            for ing in ings:
                w_item = float(ing.get("w", 0.0) or 0.0)
                yf_item = float(ing.get("yield_factor", 1.0) or 1.0)
                cost_kg_item = float(ing.get("cost_kg", 0.0) or 0.0)
                factor = w_item / 100.0
                total_cost += cost_kg_item * (w_item / 1000.0) * yf_item

                ing_n = ing.get("n") or {}
                ing_d = ing.get("d", "")
                for key in NUTRIENT_KEY_MAPPING.keys():
                    val = get_num_val(ing_n, key, ing_d)
                    if key == "Açúcares totais (g)":
                        sug_add_item = get_num_val(ing_n, "Açúcares adicionados (g)", ing_d)
                        val = max(val, sug_add_item)
                    raw_totals[key] = raw_totals.get(key, 0.0) + (val * factor)
                        
            n_100g = {}
            for key, val in raw_totals.items():
                n_100g[key] = (val / w_final) * 100.0
            n_100g["Carboidrato disponível (g)"] = n_100g.get("Carboidrato total (g)", 0.0)
                
            n_100g["Custo (R$/kg)"] = (total_cost / w_final) * 1000.0
            rec_name = (r.get("nome") or r.get("nome_produto") or f"Receita {idx+1}").strip()
                
            recipe_ingredients.append({
                "c": f"RECIPE-{idx}-{rec_name[:20]}",
                "d": f"[RECEITA] {rec_name}",
                "recipe_name": rec_name,
                "recipe_total_weight_g": round(w_final, 1),
                "recipe_total_cost": round(total_cost, 2),
                "g": "Sub-receitas Salvas",
                "f": "Usuário",
                "n": n_100g
            })
    return recipe_ingredients


def get_custom_ingredients_list(username: str = None) -> list:
    """
    Carrega os produtos/insumos cadastrados manualmente pelo usuário no banco SQL
    (com cache de 30s e sincronização com o CSV local caso exista).
    """
    from utils.db import is_sql_configured
    sql_items = [dict(it) for it in _cached_custom_ingredients_sql((username or "").strip())] if is_sql_configured() else []
    for it in sql_items:
        pkg_val = max(1.0, float(it.get("pkg_g") or it.get("custom_pkg_g") or 1000.0))
        cost_kg = float((it.get("n") or {}).get("Custo (R$/kg)", 0.0) or it.get("cost", 0.0) or 0.0)
        price_val = float(it.get("price") or it.get("custom_price") or round(cost_kg * (pkg_val / 1000.0), 2))
        it["pkg_g"] = pkg_val
        it["custom_pkg_g"] = pkg_val
        it["price"] = price_val
        it["custom_price"] = price_val
        it["cost"] = cost_kg if cost_kg > 0 else round((price_val / pkg_val) * 1000.0, 2)
    seen_codes = {it.get("c") for it in sql_items if it.get("c")}

    if os.path.exists(CUSTOM_CSV_PATH):
        try:
            custom_df = pd.read_csv(CUSTOM_CSV_PATH, encoding="utf-8-sig")
            for _, row in custom_df.iterrows():
                code = str(row.get("codigo", "")).strip()
                if not code or code in seen_codes:
                    continue
                row_user = str(row.get("username", "") or "").strip() if "username" in custom_df.columns and pd.notna(row.get("username")) else ""
                if username and row_user and row_user.lower() != username.strip().lower():
                    continue
                nut_dict = {}
                for col in custom_df.columns:
                    if col not in ["codigo", "username", "descricao", "classe", "fonte", "peso_embalagem", "preco_embalagem"] and pd.notna(row[col]):
                        try:
                            nut_dict[col] = float(row[col])
                        except Exception:
                            pass
                if "Carboidrato total (g)" in nut_dict:
                    nut_dict["Carboidrato disponível (g)"] = nut_dict.get("Carboidrato disponível (g)", nut_dict["Carboidrato total (g)"])
                    nut_dict["Açúcares totais (g)"] = max(
                        float(nut_dict.get("Açúcares totais (g)", 0.0) or 0.0),
                        float(nut_dict.get("Açúcares adicionados (g)", 0.0) or 0.0),
                    )
                pkg_g = float(row.get("peso_embalagem", 1000.0) if "peso_embalagem" in custom_df.columns and pd.notna(row.get("peso_embalagem")) else 1000.0)
                cost_kg = float(nut_dict.get("Custo (R$/kg)", 0.0) or 0.0)
                price = float(row.get("preco_embalagem", 0.0) if "preco_embalagem" in custom_df.columns and pd.notna(row.get("preco_embalagem")) else round(cost_kg * (pkg_g / 1000.0), 2))
                if cost_kg <= 0 and price > 0:
                    cost_kg = round((price / max(1.0, pkg_g)) * 1000.0, 2)
                sql_items.append({
                    "c": code,
                    "d": str(row.get("descricao", "")).strip(),
                    "g": str(row.get("classe", "Cadastrado Manualmente")),
                    "f": "CADASTRO",
                    "pkg_g": pkg_g,
                    "custom_pkg_g": pkg_g,
                    "price": price,
                    "custom_price": price,
                    "cost": cost_kg,
                    "n": nut_dict,
                })
                seen_codes.add(code)
        except Exception as e:
            logger.warning(f"Erro ao ler custom_ingredients.csv: {e}")
    return sql_items


def save_custom_ingredient(
    name: str,
    pkg_g: float = 1000.0,
    price: float = 0.0,
    username: str = "",
    portion_ref: float = 100.0,
    kcal: float = 0.0,
    carbs: float = 0.0,
    sug_tot: float = 0.0,
    sug_add: float = 0.0,
    prot: float = 0.0,
    fat: float = 0.0,
    sat_fat: float = 0.0,
    trans_fat: float = 0.0,
    fiber: float = 0.0,
    sodium: float = 0.0,
    **kwargs,
) -> dict:
    """
    Cadastra um novo produto/ingrediente customizado no banco PostgreSQL e no CSV local,
    retornando o dicionário completo do insumo pronto para uso imediato na receita.
    """
    import hashlib
    clean_name = (name or "").strip()
    pkg_g_safe = max(1.0, float(pkg_g or 1000.0))
    price_safe = max(0.0, float(price or 0.0))
    cost_kg = round((price_safe / pkg_g_safe) * 1000.0, 2)
    portion_safe = max(1.0, float(portion_ref or 100.0))
    factor = 100.0 / portion_safe

    kcal_v = kwargs.get("kcal_portion", kcal)
    carbs_v = kwargs.get("carbs_portion", carbs)
    sug_tot_v = kwargs.get("sug_tot_portion", sug_tot)
    sug_v = kwargs.get("sug_add_portion", sug_add)
    prot_v = kwargs.get("prot_portion", prot)
    fat_v = kwargs.get("fat_portion", fat)
    sat_v = kwargs.get("sat_fat_portion", sat_fat)
    trans_v = kwargs.get("trans_fat_portion", trans_fat)
    fiber_v = kwargs.get("fiber_portion", fiber)
    sodium_v = kwargs.get("sodium_portion", sodium)

    sug_add_final = round(float(sug_v or 0.0) * factor, 2)
    sug_tot_final = max(sug_add_final, round(float(sug_tot_v or 0.0) * factor, 2))

    nut_dict = {
        "Energia (kcal)": round(float(kcal_v or 0.0) * factor, 2),
        "Carboidrato total (g)": round(float(carbs_v or 0.0) * factor, 2),
        "Carboidrato disponível (g)": round(float(carbs_v or 0.0) * factor, 2),
        "Açúcares adicionados (g)": sug_add_final,
        "Açúcares totais (g)": sug_tot_final,
        "Proteína (g)": round(float(prot_v or 0.0) * factor, 2),
        "Lipídios (g)": round(float(fat_v or 0.0) * factor, 2),
        "Gorduras saturadas (g)": round(float(sat_v or 0.0) * factor, 2),
        "Gorduras trans (g)": round(float(trans_v or 0.0) * factor, 2),
        "Fibra alimentar (g)": round(float(fiber_v or 0.0) * factor, 2),
        "Sódio (mg)": round(float(sodium_v or 0.0) * factor, 2),
        "Custo (R$/kg)": cost_kg,
    }

    short_hash = hashlib.md5(f"{username}:{clean_name.lower()}".encode("utf-8")).hexdigest()[:6].upper()
    new_code = f"CAD-{short_hash}"

    item_obj = {
        "c": new_code,
        "username": username or "",
        "d": clean_name,
        "g": "Cadastrado Manualmente",
        "f": "CADASTRO",
        "pkg_g": pkg_g_safe,
        "custom_pkg_g": pkg_g_safe,
        "price": price_safe,
        "custom_price": price_safe,
        "cost": cost_kg,
        "n": nut_dict,
    }

    from utils.db import is_sql_configured, save_custom_ingredient_sql
    if is_sql_configured():
        save_custom_ingredient_sql(item_obj)

    try:
        try:
            custom_df = pd.read_csv(CUSTOM_CSV_PATH, encoding="utf-8-sig")
        except Exception:
            custom_df = pd.DataFrame()
        new_row = pd.DataFrame([{
            "codigo": new_code,
            "username": username or "",
            "descricao": clean_name,
            "classe": "Cadastrado Manualmente",
            "fonte": "CADASTRO",
            "peso_embalagem": pkg_g_safe,
            "preco_embalagem": price_safe,
            **nut_dict,
        }])
        if not custom_df.empty and "codigo" in custom_df.columns:
            custom_df = custom_df[custom_df["codigo"] != new_code]
        custom_df = pd.concat([custom_df, new_row], ignore_index=True)
        custom_df.to_csv(CUSTOM_CSV_PATH, index=False, encoding="utf-8-sig")
    except Exception as csv_err:
        logger.warning(f"Aviso ao salvar custom_ingredients.csv: {csv_err}")

    try:
        load_unified_data.clear()
        invalidate_data_caches()
    except Exception:
        pass

    return item_obj


# ==============================================================================
# CURADORIA DE INGREDIENTES BASE PARA PRODUÇÃO ARTESANAL & ALIMENTAÇÃO
# (Confeitaria, Marmitas, Restaurante, Salgados, Padaria, Pizzaria e Lanches)
# ==============================================================================

INGREDIENT_CATEGORIES = [
    "⭐ Todos os Insumos Favoritos (Doces & Salgados)",
    "🍚 Arroz, Feijão, Grãos & Massas",
    "🥩 Carnes, Frango, Peixes & Ovos",
    "🥕 Legumes, Verduras & Hortifrúti",
    "🥛 Laticínios & Queijos",
    "🍫 Chocolates, Açúcares & Doces",
    "🌾 Farinhas, Amidos & Fermentos",
    "🧈 Óleos, Manteigas, Temperos & Molhos",
    "🥜 Castanhas, Coco & Oleaginosas",
    "➕ Meus Cadastrados & Sub-receitas",
]

_TOP_CONFECTIONERY_LIST = [
    # --- GRÃOS, ARROZ & FEIJÃO (Marmitas, Restaurantes e Comida Caseira) ---
    ("TACO-4",   "⭐ Arroz Branco / Polido (Cru)", "🍚 Arroz, Feijão, Grãos & Massas"),
    ("TACO-2",   "⭐ Arroz Integral (Cru)", "🍚 Arroz, Feijão, Grãos & Massas"),
    ("TACO-3",   "⭐ Arroz Branco Cozido", "🍚 Arroz, Feijão, Grãos & Massas"),
    ("TACO-562", "⭐ Feijão Carioca (Cru)", "🍚 Arroz, Feijão, Grãos & Massas"),
    ("TACO-561", "⭐ Feijão Carioca (Cozido com Caldo)", "🍚 Arroz, Feijão, Grãos & Massas"),
    ("TACO-568", "⭐ Feijão Preto (Cru)", "🍚 Arroz, Feijão, Grãos & Massas"),
    ("TACO-567", "⭐ Feijão Preto (Cozido)", "🍚 Arroz, Feijão, Grãos & Massas"),
    ("TACO-40",  "⭐ Macarrão Tradicional de Trigo (Cru)", "🍚 Arroz, Feijão, Grãos & Massas"),
    ("TACO-121", "⭐ Farinha de Mandioca Crua", "🍚 Arroz, Feijão, Grãos & Massas"),

    # --- CARNES, AVES, PEIXES & PROTEÍNAS ---
    ("TACO-409", "⭐ Peito de Frango (Cru, sem pele)", "🥩 Carnes, Frango, Peixes & Ovos"),
    ("TACO-408", "⭐ Peito de Frango (Cozido / Desfiado)", "🥩 Carnes, Frango, Peixes & Ovos"),
    ("TACO-489", "⭐ Ovo de Galinha Inteiro (Cru)", "🥩 Carnes, Frango, Peixes & Ovos"),
    ("TACO-487", "⭐ Gema de Ovo de Galinha", "🥩 Carnes, Frango, Peixes & Ovos"),
    ("TACO-486", "⭐ Clara de Ovo de Galinha", "🥩 Carnes, Frango, Peixes & Ovos"),
    ("TACO-327", "⭐ Carne Moída Bovina (Acém cru)", "🥩 Carnes, Frango, Peixes & Ovos"),
    ("TACO-376", "⭐ Carne Bovina Patinho (Sem gordura, cru)", "🥩 Carnes, Frango, Peixes & Ovos"),
    ("TACO-369", "⭐ Carne Bovina Alcatra (Sem gordura, crua)", "🥩 Carnes, Frango, Peixes & Ovos"),
    ("TACO-380", "⭐ Carne Bovina Picanha (Crua)", "🥩 Carnes, Frango, Peixes & Ovos"),
    ("TACO-427", "⭐ Carne Suína Bisteca (Crua)", "🥩 Carnes, Frango, Peixes & Ovos"),
    ("TACO-433", "⭐ Carne Suína Lombo (Cru)", "🥩 Carnes, Frango, Peixes & Ovos"),
    ("TACO-421", "⭐ Linguiça de Porco (Crua)", "🥩 Carnes, Frango, Peixes & Ovos"),
    ("TACO-418", "⭐ Linguiça de Frango (Crua)", "🥩 Carnes, Frango, Peixes & Ovos"),
    ("TACO-307", "⭐ Pescada / Tilápia / Peixe Branco (Filé cru)", "🥩 Carnes, Frango, Peixes & Ovos"),

    # --- HORTIFRÚTI, LEGUMES & TEMPEROS ESSENCIAIS ---
    ("TACO-82",  "⭐ Alho Cru", "🥕 Legumes, Verduras & Hortifrúti"),
    ("TACO-107", "⭐ Cebola Crua", "🥕 Legumes, Verduras & Hortifrúti"),
    ("TACO-92",  "⭐ Batata Inglesa (Crua)", "🥕 Legumes, Verduras & Hortifrúti"),
    ("TACO-91",  "⭐ Batata Inglesa (Cozida)", "🥕 Legumes, Verduras & Hortifrúti"),
    ("TACO-89",  "⭐ Batata Doce (Crua)", "🥕 Legumes, Verduras & Hortifrúti"),
    ("TACO-87",  "⭐ Batata Baroa / Mandioquinha (Crua)", "🥕 Legumes, Verduras & Hortifrúti"),
    ("TACO-130", "⭐ Mandioca / Aipim / Macaxeira (Crua)", "🥕 Legumes, Verduras & Hortifrúti"),
    ("TACO-157", "⭐ Tomate com Semente (Cru)", "🥕 Legumes, Verduras & Hortifrúti"),
    ("TACO-158", "⭐ Extrato de Tomate", "🧈 Óleos, Manteigas, Temperos & Molhos"),
    ("TACO-159", "⭐ Molho de Tomate (Pronto)", "🧈 Óleos, Manteigas, Temperos & Molhos"),
    ("TACO-110", "⭐ Cenoura Crua", "🥕 Legumes, Verduras & Hortifrúti"),
    ("C0020L",   "⭐ Sal Refinado (Sal de Cozinha)", "🧈 Óleos, Manteigas, Temperos & Molhos"),
    ("TACO-517", "⭐ Sal Grosso", "🧈 Óleos, Manteigas, Temperos & Molhos"),
    ("TACO-260", "⭐ Azeite de Oliva Extra Virgem", "🧈 Óleos, Manteigas, Temperos & Molhos"),
    ("TACO-272", "⭐ Óleo de Soja", "🧈 Óleos, Manteigas, Temperos & Molhos"),
    ("TACO-269", "⭐ Óleo de Girassol", "🧈 Óleos, Manteigas, Temperos & Molhos"),
    ("TACO-270", "⭐ Óleo de Milho", "🧈 Óleos, Manteigas, Temperos & Molhos"),

    # --- LATICÍNIOS & QUEIJOS ---
    ("TACO-453", "⭐ Leite Condensado Integral", "🥛 Laticínios & Queijos"),
    ("TACO-447", "⭐ Creme de Leite", "🥛 Laticínios & Queijos"),
    ("TACO-459", "⭐ Leite em Pó Integral (tipo Ninho)", "🥛 Laticínios & Queijos"),
    ("TACO-458", "⭐ Leite de Vaca Integral (Líquido)", "🥛 Laticínios & Queijos"),
    ("TACO-262", "⭐ Manteiga sem Sal", "🥛 Laticínios & Queijos"),
    ("TACO-261", "⭐ Manteiga com Sal", "🥛 Laticínios & Queijos"),
    ("TACO-264", "⭐ Margarina sem Sal (80% lipídeos)", "🧈 Óleos, Manteigas, Temperos & Molhos"),
    ("TACO-463", "⭐ Queijo Muçarela", "🥛 Laticínios & Queijos"),
    ("TACO-464", "⭐ Queijo Parmesão", "🥛 Laticínios & Queijos"),
    ("TACO-461", "⭐ Queijo Minas Frescal", "🥛 Laticínios & Queijos"),
    ("TACO-468", "⭐ Requeijão Cremoso", "🥛 Laticínios & Queijos"),
    ("TACO-469", "⭐ Queijo Ricota", "🥛 Laticínios & Queijos"),
    ("C0009G",   "⭐ Cream Cheese Tradicional", "🥛 Laticínios & Queijos"),
    ("TACO-448", "⭐ Iogurte Natural Integral", "🥛 Laticínios & Queijos"),
    ("TACO-522", "⭐ Chantilly (Creme Vegetal)", "🥛 Laticínios & Queijos"),

    # --- FARINHAS, AMIDOS & FERMENTOS ---
    ("TACO-35",  "⭐ Farinha de Trigo Tradicional", "🌾 Farinhas, Amidos & Fermentos"),
    ("TACO-42",  "⭐ Amido de Milho (Maisena)", "🌾 Farinhas, Amidos & Fermentos"),
    ("TACO-146", "⭐ Polvilho Doce", "🌾 Farinhas, Amidos & Fermentos"),
    ("TACO-7",   "⭐ Aveia em Flocos", "🌾 Farinhas, Amidos & Fermentos"),
    ("TACO-43",  "⭐ Fubá de Milho", "🌾 Farinhas, Amidos & Fermentos"),
    ("TACO-513", "⭐ Fermento em Pó Químico (p/ Bolo)", "🌾 Farinhas, Amidos & Fermentos"),
    ("TACO-514", "⭐ Fermento Biológico (p/ Pão)", "🌾 Farinhas, Amidos & Fermentos"),

    # --- AÇÚCARES, CHOCOLATES & DOCES ---
    ("TACO-494", "⭐ Açúcar Refinado", "🍫 Chocolates, Açúcares & Doces"),
    ("TACO-492", "⭐ Açúcar Cristal", "🍫 Chocolates, Açúcares & Doces"),
    ("TACO-493", "⭐ Açúcar Mascavo", "🍫 Chocolates, Açúcares & Doces"),
    ("TACO-507", "⭐ Mel de Abelha", "🍫 Chocolates, Açúcares & Doces"),
    ("TACO-503", "⭐ Glucose / Glicose de Milho", "🍫 Chocolates, Açúcares & Doces"),
    ("C0011K",   "⭐ Chocolate em Pó (50% / Culinário)", "🍫 Chocolates, Açúcares & Doces"),
    ("C0090K",   "⭐ Cacau em Pó 100% (Sem Açúcar)", "🍫 Chocolates, Açúcares & Doces"),
    ("TACO-491", "⭐ Achocolatado em Pó", "🍫 Chocolates, Açúcares & Doces"),
    ("TACO-495", "⭐ Chocolate ao Leite (Barra / Gotas)", "🍫 Chocolates, Açúcares & Doces"),
    ("TACO-498", "⭐ Chocolate Meio Amargo (Barra / Gotas)", "🍫 Chocolates, Açúcares & Doces"),
    ("C0164K",   "⭐ Chocolate Branco", "🍫 Chocolates, Açúcares & Doces"),
    ("C0194K",   "⭐ Chocolate Granulado", "🍫 Chocolates, Açúcares & Doces"),
    ("C0128K",   "⭐ Creme de Avelã com Cacau (tipo Nutella)", "🍫 Chocolates, Açúcares & Doces"),
    ("TACO-501", "⭐ Doce de Leite Cremoso", "🍫 Chocolates, Açúcares & Doces"),
    ("TACO-198", "⭐ Goiabada (Doce de Goiaba em Pasta)", "🍫 Chocolates, Açúcares & Doces"),
    ("TACO-515", "⭐ Gelatina em Pó", "🍫 Chocolates, Açúcares & Doces"),
    ("C0778B",   "⭐ Canela em Pó", "🍫 Chocolates, Açúcares & Doces"),
    ("C0027L",   "⭐ Extrato / Essência de Baunilha", "🍫 Chocolates, Açúcares & Doces"),

    # --- FRUTAS & OLEAGINOSAS ---
    ("TACO-239", "⭐ Morango Fresco (Cru)", "🥕 Legumes, Verduras & Hortifrúti"),
    ("TACO-232", "⭐ Maracujá In Natura", "🥕 Legumes, Verduras & Hortifrúti"),
    ("TACO-233", "⭐ Polpa de Maracujá Congelada", "🥕 Legumes, Verduras & Hortifrúti"),
    ("TACO-220", "⭐ Limão Tahiti", "🥕 Legumes, Verduras & Hortifrúti"),
    ("TACO-214", "⭐ Laranja Pêra", "🥕 Legumes, Verduras & Hortifrúti"),
    ("TACO-182", "⭐ Banana Prata", "🥕 Legumes, Verduras & Hortifrúti"),
    ("TACO-164", "⭐ Abacaxi Fresco", "🥕 Legumes, Verduras & Hortifrúti"),
    ("TACO-222", "⭐ Maçã Fuji", "🥕 Legumes, Verduras & Hortifrúti"),
    ("TACO-523", "⭐ Leite de Coco", "🥜 Castanhas, Coco & Oleaginosas"),
    ("TACO-590", "⭐ Coco Ralado / Coco Fresco", "🥜 Castanhas, Coco & Oleaginosas"),
    ("TACO-557", "⭐ Amendoim Cru", "🥜 Castanhas, Coco & Oleaginosas"),
    ("TACO-579", "⭐ Paçoca de Amendoim", "🥜 Castanhas, Coco & Oleaginosas"),
    ("TACO-587", "⭐ Amêndoa Torrada", "🥜 Castanhas, Coco & Oleaginosas"),
    ("TACO-588", "⭐ Castanha de Caju Torrada", "🥜 Castanhas, Coco & Oleaginosas"),
    ("TACO-589", "⭐ Castanha-do-Pará / Brasil", "🥜 Castanhas, Coco & Oleaginosas"),
    ("TACO-597", "⭐ Nozes", "🥜 Castanhas, Coco & Oleaginosas"),
    ("TACO-8",   "⭐ Biscoito Maisena (p/ Tortas e Palha Italiana)", "🌾 Farinhas, Amidos & Fermentos"),
]

TOP_CONFECTIONERY_MAP = {
    code: {"rank": idx, "alias": alias, "category": cat}
    for idx, (code, alias, cat) in enumerate(_TOP_CONFECTIONERY_LIST)
}

_PREPARED_DISH_MARKERS = (
    "c/ sal", "s/ sal", "c/sal", "s/sal", "c / sal", "s / sal",
    "s/ óleo", "c/ óleo", "s/ oleo", "c/ oleo",
    "refogad", "grelhad", "frito", "frita", "assado", "assada",
    "ensopad", "cozido,", "cozida,", "caseiro", "caseira",
    "à milanesa", "à parmegiana", "ao molho", "c/ molho", "s/ molho",
    "mistura p/", "mistura para", "preparado", "preparada",
    "drenado", "drenada", "rechead", "c/ cobertura", "c/ recheio",
    "industrializad", "infantil", "dietétic", "diet,"
)

_PREPARED_DISH_PREFIXES = (
    "sanduíche", "sanduiche", "pizza", "lasanha",
    "canelone", "ravioli", "risoto", "panqueca", "bife ", "croquete",
    "pastel", "coxinha", "empada", "esfiha", "quiche", "suflê", "sufle",
    "omelete", "sopa", "caldo,", "salada", "vitamina,", "bebida,", "bebida láctea",
    "papa de", "bolo,", "torta,", "pudim",
    "mousse", "pavê", "pave", "brigadeiro", "beijinho", "torrada", "croissant",
    "pamonha", "curau", "canjica", "cuscuz", "tapioca", "pipoca", "farofa",
    "maionese", "refrigerante", "chá,", "cha,", "suco ", "flan,", "maria mole",
    "pão,", "pao,", "biscoito,", "bombom,",
    "arroz com", "arroz de ", "arroz carreteiro", "bolinho de arroz", "baião de dois", "baiao de dois", "arroz doce",
    "feijão tropeiro", "feijao tropeiro", "feijão com", "feijao com",
    "macarrão com", "macarrao com", "macarrão ao", "macarrao ao", "macarrão de", "macarrao de", "macarrão à", "macarrao a",
    "estrogonofe", "salpicão", "salpicao"
)


def is_pure_culinary_ingredient(food: dict) -> bool:
    """
    Identifica se um item da base unificada é um ingrediente base culinário/confeitaria
    (excluindo os ~4.500 pratos prontos de restaurante, refeições temperadas e fórmulas hospitalares).
    """
    code = food.get("c", "")
    if code in TOP_CONFECTIONERY_MAP:
        return True

    source = food.get("f", "")
    if source in ("CADASTRO", "Usuário"):
        return True

    group = food.get("g", "")
    if group in ("Alimentos para fins especiais",):
        return False

    desc = (food.get("d", "") or "").strip()
    desc_low = desc.lower()

    # Pratos compostos da TBCA trazem os ingredientes da preparação listados entre parênteses
    if "(" in desc and "," in desc.split("(", 1)[1]:
        return False

    if any(marker in desc_low for marker in _PREPARED_DISH_MARKERS):
        return False

    if desc_low.startswith(_PREPARED_DISH_PREFIXES):
        return False

    return True


def classify_ingredient_category(food: dict) -> str:
    """
    Classifica um ingrediente em uma das categorias amigáveis para confeitaria e produção artesanal.
    """
    code = food.get("c", "")
    if code in TOP_CONFECTIONERY_MAP:
        return TOP_CONFECTIONERY_MAP[code]["category"]

    source = food.get("f", "")
    if source in ("CADASTRO", "Usuário"):
        return "➕ Meus Cadastrados & Sub-receitas"

    group = (food.get("g", "") or "").lower()
    desc = (food.get("d", "") or "").lower()

    if "leite" in group or "ovos" in group or any(w in desc for w in ("leite", "queijo", "iogurte", "requeijão", "ricota", "ovo", "creme de leite")):
        return "🥛 Laticínios, Queijos & Ovos"
    if "açucarados" in group or any(w in desc for w in ("açúcar", "acucar", "chocolate", "cacau", "mel", "doce", "gelatina", "baunilha", "canela")):
        return "🍫 Chocolates, Açúcares & Doces"
    if "gorduras" in group or any(w in desc for w in ("manteiga", "margarina", "óleo", "oleo", "azeite", "banha", "gordura")):
        return "🧈 Manteigas, Óleos & Gorduras"
    if "nozes" in group or "sementes" in group or any(w in desc for w in ("castanha", "amendoim", "amêndoa", "noz", "avelã", "coco", "gergelim", "linhaça", "chia")):
        return "🥜 Castanhas, Coco & Oleaginosas"
    if "frutas" in group or "vegetais" in group or any(w in desc for w in ("morango", "limão", "maracujá", "banana", "laranja", "abacaxi", "maçã", "cenoura", "abóbora", "polpa")):
        return "🍓 Frutas, Polpas & Vegetais"
    if "cereais" in group or any(w in desc for w in ("farinha", "amido", "polvilho", "aveia", "fubá", "milho", "trigo", "fermento")):
        return "🌾 Farinhas, Amidos & Grãos"

    return "🌾 Farinhas, Amidos & Grãos"


def format_ingredient_option_label(food: dict) -> str:
    """
    Formata o rótulo do ingrediente no seletor usando linguagem limpa e amigável para pessoas leigas,
    destacando Receitas Salvas (molhos, coberturas, recheios) e Produtos Cadastrados.
    """
    code = food.get("c", "")
    clean_d = (food.get("d", "") or "").rstrip(", ").strip()
    source = food.get("f", "")
    if source == "Usuário":
        rec_name = food.get("recipe_name") or clean_d.replace("[RECEITA]", "").strip()
        w_tot = float(food.get("recipe_total_weight_g", 0.0) or 0.0)
        c_tot = float(food.get("recipe_total_cost", 0.0) or 0.0)
        if w_tot > 0:
            return f"🍲 [Minha Receita] {rec_name} (Rende {w_tot:.0f}g • Custo R$ {c_tot:.2f})"
        return f"🍲 [Minha Receita] {rec_name}"
    if source == "CADASTRO":
        return f"➕ [Meu Produto] {clean_d}"
    if code in TOP_CONFECTIONERY_MAP:
        return TOP_CONFECTIONERY_MAP[code]["alias"]
    return clean_d


_SMART_PACKAGE_DEFAULTS = {
    # --- GRÃOS & CEREAIS ---
    "TACO-4":   {"use_g": 500.0, "pkg_g": 1000.0, "price": 6.50,  "hint": "1 pacote de arroz tem 1 kg ou 5 kg (1 xícara de arroz cru = ~200g)"},
    "TACO-2":   {"use_g": 500.0, "pkg_g": 1000.0, "price": 8.90,  "hint": "1 pacote de arroz integral tem 1 kg (1 xícara = ~200g)"},
    "TACO-3":   {"use_g": 300.0, "pkg_g": 1000.0, "price": 6.50,  "hint": "Arroz cozido rende o dobro do cru (1 xícara cheia = ~160g cozido)"},
    "TACO-562": {"use_g": 500.0, "pkg_g": 1000.0, "price": 8.50,  "hint": "1 pacote de feijão carioca tem 1 kg (1 xícara de grão cru = ~180g)"},
    "TACO-561": {"use_g": 300.0, "pkg_g": 1000.0, "price": 8.50,  "hint": "Feijão carioca cozido com caldo (1 concha média cheia = ~140g)"},
    "TACO-568": {"use_g": 500.0, "pkg_g": 1000.0, "price": 8.90,  "hint": "1 pacote de feijão preto tem 1 kg"},
    "TACO-567": {"use_g": 300.0, "pkg_g": 1000.0, "price": 8.90,  "hint": "Feijão preto cozido (1 concha média cheia = ~140g)"},
    "TACO-40":  {"use_g": 500.0, "pkg_g": 500.0,  "price": 4.50,  "hint": "1 pacote padrão de macarrão tem 500g"},
    "TACO-121": {"use_g": 200.0, "pkg_g": 1000.0, "price": 7.50,  "hint": "1 pacote de farinha de mandioca tem 1 kg ou 500g"},

    # --- CARNES, FRANGO & PROTEÍNAS ---
    "TACO-409": {"use_g": 1000.0, "pkg_g": 1000.0, "price": 22.00, "hint": "Bandeja ou pacote de peito de frango tem ~1 kg (1 filé médio = ~120g a 150g)"},
    "TACO-408": {"use_g": 500.0,  "pkg_g": 1000.0, "price": 24.00, "hint": "Peito de frango cozido e desfiado para recheios ou marmitas"},
    "TACO-327": {"use_g": 500.0,  "pkg_g": 1000.0, "price": 35.00, "hint": "Carne moída para recheios de salgados, empadão, almôndegas ou molho"},
    "TACO-376": {"use_g": 1000.0, "pkg_g": 1000.0, "price": 42.00, "hint": "Patinho bovino moído ou em bifes para marmitas saudáveis"},
    "TACO-369": {"use_g": 1000.0, "pkg_g": 1000.0, "price": 45.00, "hint": "Alcatra bovina para bifes ou picadinho"},
    "TACO-380": {"use_g": 1000.0, "pkg_g": 1000.0, "price": 69.00, "hint": "Picanha bovina fatiada em bifes"},
    "TACO-427": {"use_g": 500.0,  "pkg_g": 1000.0, "price": 22.00, "hint": "Bisteca suína para marmitas e assados"},
    "TACO-433": {"use_g": 1000.0, "pkg_g": 1000.0, "price": 26.00, "hint": "Lombo suíno para assados ou fatiados"},
    "TACO-421": {"use_g": 500.0,  "pkg_g": 1000.0, "price": 24.00, "hint": "Linguiça toscana/de porco (1 gomo = ~80g a 100g)"},
    "TACO-418": {"use_g": 500.0,  "pkg_g": 1000.0, "price": 22.00, "hint": "Linguiça de frango"},
    "TACO-307": {"use_g": 500.0,  "pkg_g": 1000.0, "price": 38.00, "hint": "Pacote de filé de tilápia ou pescada branca tem 500g ou 1 kg"},

    # --- HORTIFRÚTI & TEMPEROS ---
    "TACO-82":  {"use_g": 20.0,  "pkg_g": 100.0,  "price": 4.50,  "hint": "1 dente de alho pesa ~5g (4 dentes = ~20g). 1 cabeça inteira = ~40g"},
    "TACO-107": {"use_g": 150.0, "pkg_g": 1000.0, "price": 5.90,  "hint": "1 cebola média pesa ~120g a 150g"},
    "TACO-92":  {"use_g": 500.0, "pkg_g": 1000.0, "price": 6.90,  "hint": "1 batata média pesa ~150g (3 batatas = ~450g a 500g)"},
    "TACO-91":  {"use_g": 300.0, "pkg_g": 1000.0, "price": 6.90,  "hint": "Batata inglesa cozida para purê, maionese ou acompanhamento"},
    "TACO-89":  {"use_g": 500.0, "pkg_g": 1000.0, "price": 5.90,  "hint": "1 batata doce média pesa ~200g a 250g"},
    "TACO-87":  {"use_g": 500.0, "pkg_g": 1000.0, "price": 9.90,  "hint": "Batata baroa / mandioquinha para cremes, sopas e purês"},
    "TACO-130": {"use_g": 1000.0, "pkg_g": 1000.0, "price": 6.50, "hint": "Pacote de mandioca a vácuo tem 1 kg"},
    "TACO-157": {"use_g": 300.0, "pkg_g": 1000.0, "price": 7.90,  "hint": "1 tomate médio pesa ~100g (3 tomates = ~300g)"},
    "TACO-158": {"use_g": 140.0, "pkg_g": 140.0,  "price": 4.50,  "hint": "1 latinha de extrato de tomate tem 140g ou 350g"},
    "TACO-159": {"use_g": 340.0, "pkg_g": 340.0,  "price": 3.90,  "hint": "1 sachê padrão de molho de tomate tem 340g"},
    "TACO-110": {"use_g": 200.0, "pkg_g": 1000.0, "price": 5.90,  "hint": "1 cenoura média pesa ~120g a 150g"},
    "C0020L":   {"use_g": 10.0,  "pkg_g": 1000.0, "price": 3.50,  "hint": "1 pacote de sal tem 1000g (1 colher de chá rasa = ~5g)"},
    "TACO-517": {"use_g": 50.0,  "pkg_g": 1000.0, "price": 4.50,  "hint": "1 pacote de sal grosso tem 1000g"},
    "TACO-260": {"use_g": 30.0,  "pkg_g": 500.0,  "price": 38.00, "hint": "1 garrafa de azeite tem 500ml (1 colher de sopa = ~15ml)"},
    "TACO-272": {"use_g": 50.0,  "pkg_g": 900.0,  "price": 7.50,  "hint": "1 garrafa pet de óleo de soja tem 900ml (1 colher de sopa = ~15ml)"},
    "TACO-269": {"use_g": 50.0,  "pkg_g": 900.0,  "price": 9.90,  "hint": "1 garrafa de óleo de girassol tem 900ml"},
    "TACO-270": {"use_g": 50.0,  "pkg_g": 900.0,  "price": 9.90,  "hint": "1 garrafa de óleo de milho tem 900ml"},

    # --- LATICÍNIOS, OVOS & QUEIJOS ---
    "TACO-453": {"use_g": 395.0, "pkg_g": 395.0, "price": 7.90, "hint": "1 lata ou caixinha padrão tem 395g"},
    "TACO-447": {"use_g": 200.0, "pkg_g": 200.0, "price": 4.20, "hint": "1 caixinha padrão tem 200g"},
    "TACO-459": {"use_g": 60.0,  "pkg_g": 380.0, "price": 18.90, "hint": "1 lata/pacote tem 380g ou 400g (1 colher de sopa cheia = ~15g)"},
    "TACO-458": {"use_g": 240.0, "pkg_g": 1000.0, "price": 5.80, "hint": "1 caixa de 1 Litro = 1000ml (1 xícara = 240ml)"},
    "TACO-262": {"use_g": 20.0,  "pkg_g": 200.0, "price": 12.90, "hint": "1 tablete ou pote tem 200g (1 colher de sopa = ~20g)"},
    "TACO-261": {"use_g": 20.0,  "pkg_g": 200.0, "price": 12.90, "hint": "1 tablete ou pote tem 200g (1 colher de sopa = ~20g)"},
    "TACO-264": {"use_g": 40.0,  "pkg_g": 500.0, "price": 8.50, "hint": "1 pote padrão tem 500g (1 colher de sopa = ~20g)"},
    "TACO-489": {"use_g": 150.0, "pkg_g": 1500.0, "price": 24.00, "hint": "1 ovo pesa ~50g (3 ovos = 150g). Cartela com 30 ovos = 1500g; Dúzia = 600g"},
    "TACO-487": {"use_g": 60.0,  "pkg_g": 600.0, "price": 12.00, "hint": "1 gema pesa ~20g (3 gemas = 60g). Dúzia de ovos = 600g"},
    "TACO-486": {"use_g": 90.0,  "pkg_g": 600.0, "price": 12.00, "hint": "1 clara pesa ~30g (3 claras = 90g). Dúzia de ovos = 600g"},
    "TACO-463": {"use_g": 200.0, "pkg_g": 1000.0, "price": 44.00, "hint": "Queijo muçarela fatiado ou peça inteira"},
    "TACO-464": {"use_g": 50.0,  "pkg_g": 100.0,  "price": 8.90,  "hint": "Pacotinho de queijo parmesão ralado tem 50g ou 100g"},
    "TACO-461": {"use_g": 200.0, "pkg_g": 500.0,  "price": 18.00, "hint": "Queijo minas frescal"},
    "TACO-468": {"use_g": 100.0, "pkg_g": 200.0,  "price": 8.50,  "hint": "1 copo padrão de requeijão tem 200g"},
    "TACO-469": {"use_g": 200.0, "pkg_g": 400.0,  "price": 12.90, "hint": "Pote de ricota fresca"},
    "C0009G":   {"use_g": 150.0, "pkg_g": 150.0,  "price": 9.90,  "hint": "1 pote padrão de cream cheese tem 150g"},
    "TACO-448": {"use_g": 170.0, "pkg_g": 170.0,  "price": 3.90,  "hint": "1 potinho de iogurte natural tem 170g"},
    "TACO-522": {"use_g": 200.0, "pkg_g": 1000.0, "price": 22.00, "hint": "Caixa de chantilly de 1 Litro ou caixinha de 200ml"},

    # --- FARINHAS, AMIDOS & FERMENTOS ---
    "TACO-35":  {"use_g": 240.0, "pkg_g": 1000.0, "price": 5.90, "hint": "1 pacote de 1 kg = 1000g (1 xícara de chá = ~120g)"},
    "TACO-42":  {"use_g": 30.0,  "pkg_g": 200.0, "price": 6.50, "hint": "1 caixinha pequena tem 200g (1 colher de sopa = ~15g)"},
    "TACO-146": {"use_g": 200.0, "pkg_g": 1000.0, "price": 9.90, "hint": "1 pacote de polvilho doce tem 500g ou 1 kg"},
    "TACO-7":   {"use_g": 100.0, "pkg_g": 200.0, "price": 5.90, "hint": "1 caixa ou pacote de aveia em flocos tem 170g ou 200g"},
    "TACO-43":  {"use_g": 200.0, "pkg_g": 500.0, "price": 4.50, "hint": "1 pacote de fubá tem 500g ou 1 kg"},
    "TACO-513": {"use_g": 15.0,  "pkg_g": 100.0, "price": 4.90, "hint": "1 potinho de fermento tem 100g (1 tampinha / colher de sopa = 15g)"},
    "TACO-514": {"use_g": 10.0,  "pkg_g": 10.0,  "price": 1.90, "hint": "1 sachê de fermento biológico seco tem 10g"},

    # --- AÇÚCARES & CHOCOLATES ---
    "TACO-494": {"use_g": 180.0, "pkg_g": 1000.0, "price": 4.90, "hint": "1 pacote de 1 kg = 1000g (1 xícara de chá = ~180g)"},
    "TACO-492": {"use_g": 180.0, "pkg_g": 1000.0, "price": 4.90, "hint": "1 pacote de 1 kg = 1000g (1 xícara de chá = ~180g)"},
    "TACO-493": {"use_g": 180.0, "pkg_g": 1000.0, "price": 8.90, "hint": "1 pacote de açúcar mascavo tem 500g ou 1 kg"},
    "TACO-507": {"use_g": 100.0, "pkg_g": 300.0, "price": 18.00, "hint": "1 bisnaga ou pote de mel tem ~300g"},
    "TACO-503": {"use_g": 50.0,  "pkg_g": 500.0, "price": 9.90, "hint": "Pote de glucose/glicose de milho tem 500g"},
    "C0011K":   {"use_g": 50.0,  "pkg_g": 200.0, "price": 13.90, "hint": "1 caixinha padrão tem 200g (1 colher de sopa = ~15g)"},
    "C0090K":   {"use_g": 45.0,  "pkg_g": 200.0, "price": 18.90, "hint": "1 pacote de 200g (1 colher de sopa = ~15g)"},
    "TACO-491": {"use_g": 60.0,  "pkg_g": 400.0, "price": 8.90, "hint": "1 lata de achocolatado tem 400g"},
    "TACO-495": {"use_g": 200.0, "pkg_g": 1000.0, "price": 49.90, "hint": "1 barra de confeitaria de 1 kg = 1000g"},
    "TACO-498": {"use_g": 200.0, "pkg_g": 1000.0, "price": 54.90, "hint": "1 barra de confeitaria de 1 kg = 1000g"},
    "C0164K":   {"use_g": 200.0, "pkg_g": 1000.0, "price": 52.90, "hint": "1 barra de chocolate branco de 1 kg"},
    "C0194K":   {"use_g": 80.0,  "pkg_g": 150.0, "price": 6.90, "hint": "1 pacotinho de granulado costuma ter 150g ou 500g"},
    "C0128K":   {"use_g": 100.0, "pkg_g": 350.0, "price": 24.90, "hint": "1 pote médio de Nutella tem 350g (pote grande = 650g)"},
    "TACO-501": {"use_g": 200.0, "pkg_g": 400.0, "price": 11.90, "hint": "1 pote ou lata padrão de doce de leite tem 400g"},
    "TACO-198": {"use_g": 200.0, "pkg_g": 300.0, "price": 7.90, "hint": "Tablete de goiabada tem 300g ou 500g"},
    "TACO-515": {"use_g": 12.0,  "pkg_g": 24.0,  "price": 3.90, "hint": "1 pacotinho de gelatina incolor tem 12g (caixa com 2 = 24g)"},
    "C0778B":   {"use_g": 5.0,   "pkg_g": 30.0,  "price": 4.50, "hint": "1 saquinho de canela em pó tem 30g ou 50g"},
    "C0027L":   {"use_g": 10.0,  "pkg_g": 30.0,  "price": 6.90, "hint": "1 frasquinho de essência de baunilha tem 30ml"},

    # --- FRUTAS & OLEAGINOSAS ---
    "TACO-239": {"use_g": 250.0, "pkg_g": 250.0, "price": 10.00, "hint": "1 bandeja de morango de mercado costuma ter 250g"},
    "TACO-523": {"use_g": 200.0, "pkg_g": 200.0, "price": 5.50, "hint": "1 garrafinha de leite de coco tem 200ml"},
    "TACO-590": {"use_g": 100.0, "pkg_g": 100.0, "price": 6.90, "hint": "1 pacotinho de coco ralado tem 100g"},
}


def get_ingredient_smart_defaults(food: dict) -> dict:
    """
    Retorna sugestões inteligentes de peso usado na receita, peso da embalagem do mercado,
    preço médio e dica prática em medidas caseiras (ou os dados reais de sub-receitas e produtos cadastrados).
    """
    if not food:
        return {
            "use_g": 100.0,
            "pkg_g": 1000.0,
            "price": 12.00,
            "hint": "Dica de medidas: 1 colher de sopa = ~15g | 1 xícara = ~150g | 1 pacote de 1 kg = 1000g"
        }

    source = food.get("f", "")
    if source == "Usuário":
        pkg_g = max(1.0, float(food.get("recipe_total_weight_g", 1000.0) or 1000.0))
        price = max(0.0, float(food.get("recipe_total_cost", 0.0) or 0.0))
        use_g = round(min(150.0, pkg_g), 1)
        rec_name = (food.get("recipe_name") or food.get("d", "Sua receita")).replace("[RECEITA]", "").strip()
        return {
            "use_g": use_g,
            "pkg_g": pkg_g,
            "price": price,
            "hint": (
                f"🍲 Receita salva '{rec_name}': a receita toda rende {pkg_g:.0f}g e custa R$ {price:.2f} "
                f"(já preenchidos automaticamente nos campos 2 e 3). Basta informar no campo 1 quanto dela você vai usar aqui!"
            ),
        }

    if source == "CADASTRO":
        pkg_g = max(1.0, float(food.get("pkg_g") or food.get("custom_pkg_g") or 1000.0))
        cost_kg = float((food.get("n") or {}).get("Custo (R$/kg)", 0.0) or food.get("cost", 0.0) or 0.0)
        price = float(food.get("price") or food.get("custom_price") or round(cost_kg * (pkg_g / 1000.0), 2) or 10.0)
        use_g = round(min(100.0, pkg_g), 1)
        return {
            "use_g": use_g,
            "pkg_g": pkg_g,
            "price": price,
            "hint": f"➕ Produto cadastrado por você (Embalagem de {pkg_g:.0f}g/ml por R$ {price:.2f}).",
        }

    code = food.get("c", "")
    if code in _SMART_PACKAGE_DEFAULTS:
        return _SMART_PACKAGE_DEFAULTS[code].copy()
    return {
        "use_g": 100.0,
        "pkg_g": 1000.0,
        "price": 12.00,
        "hint": "Dica de medidas: 1 colher de sopa = ~15g | 1 xícara = ~150g | 1 pacote de 1 kg = 1000g"
    }


def filter_and_rank_ingredients(
    foods_list: list,
    search_query: str = "",
    category: str = "⭐ Todos os Ingredientes Base",
    include_prepared_dishes: bool = False
) -> list:
    """
    Filtra e ordena os ingredientes priorizando:
    1. Modo Ingredientes Puros (oculta os ~4.500 pratos prontos da TBCA por padrão)
    2. Filtro por categoria (incluindo filtro exclusivo de Receitas Salvas e Produtos Cadastrados)
    3. Busca por nome comercial (alias), descrição oficial ou código
    4. Ordenação inteligente: Top Favoritos -> Receitas Salvas e Produtos Cadastrados -> TACO -> TBCA
    """
    import unicodedata

    def _norm(s: str) -> str:
        if not s:
            return ""
        nfkd = unicodedata.normalize("NFKD", s)
        return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower()

    # 1. Filtrar pratos prontos (a menos que o usuário peça a base completa)
    if include_prepared_dishes:
        pool = list(foods_list)
    else:
        pool = [f for f in foods_list if is_pure_culinary_ingredient(f)]

    # 2. Filtrar por categoria selecionada
    if category == "🍲 Só Minhas Receitas Salvas":
        pool = [f for f in pool if f.get("f", "") == "Usuário"]
    elif category == "➕ Só Meus Produtos Cadastrados":
        pool = [f for f in pool if f.get("f", "") == "CADASTRO"]
    elif category == "🏆 Só os Mais Usados na Confeitaria":
        pool = [f for f in pool if f.get("c", "") in TOP_CONFECTIONERY_MAP]
    elif category and category != "⭐ Todos os Ingredientes Base":
        pool = [f for f in pool if classify_ingredient_category(f) == category]

    q_norm = _norm((search_query or "").strip())
    q_words = [w for w in q_norm.split() if w]

    # 3. Se não há termo de busca, retornar TODOS os insumos puros para busca direta no st.selectbox
    if not q_words:
        def _default_sort_key(food):
            code = food.get("c", "")
            source = food.get("f", "")
            if code in TOP_CONFECTIONERY_MAP:
                return (0, TOP_CONFECTIONERY_MAP[code]["rank"], "")
            if source == "Usuário":
                return (1, 0, _norm(food.get("d", "")))
            if source == "CADASTRO":
                return (1, 1, _norm(food.get("d", "")))
            if source == "TACO":
                return (2, 0, _norm(food.get("d", "")))
            return (3, 0, _norm(food.get("d", "")))

        return sorted(pool, key=_default_sort_key)

    # 4. Com termo de busca: pesquisar no alias comercial, descrição e código
    matched = []
    for f in pool:
        code = f.get("c", "")
        alias_norm = _norm(TOP_CONFECTIONERY_MAP[code]["alias"]) if code in TOP_CONFECTIONERY_MAP else ""
        desc_norm = _norm(f.get("d", ""))
        code_norm = _norm(code)
        combined = f"{alias_norm} {desc_norm} {code_norm}"
        if all(w in combined for w in q_words):
            matched.append(f)

    def _search_sort_key(food):
        code = food.get("c", "")
        source = food.get("f", "")
        desc_norm = _norm(food.get("d", ""))
        alias_norm = _norm(TOP_CONFECTIONERY_MAP[code]["alias"]) if code in TOP_CONFECTIONERY_MAP else ""

        # Prioridade 0: Código exato
        if _norm(code) == q_norm:
            return (0, 0, 0, 0, 0, 0, len(desc_norm))

        # Prioridade 1: Está nos Top 65 da Confeitaria ou foi cadastrado pela usuária
        is_top_or_custom = 0 if (code in TOP_CONFECTIONERY_MAP or source in ("CADASTRO", "Usuário")) else 1
        top_rank = TOP_CONFECTIONERY_MAP[code]["rank"] if code in TOP_CONFECTIONERY_MAP else 999

        # Prioridade 2: Começa com a primeira palavra buscada
        first_w = q_words[0]
        starts_with = 0 if (desc_norm.startswith(first_w) or alias_norm.replace("⭐ ", "").startswith(first_w)) else 1

        # Prioridade 3: TACO (ingredientes puros) antes de TBCA
        source_rank = 0 if source in ("CADASTRO", "Usuário", "TACO") else 1

        # Prioridade 4: Posição da busca e tamanho do texto (nomes mais curtos = mais puros)
        pos_desc = desc_norm.find(first_w)
        pos_score = pos_desc if pos_desc >= 0 else 999

        return (1, is_top_or_custom, starts_with, top_rank, source_rank, pos_score, len(desc_norm))

    return sorted(matched, key=_search_sort_key)[:100]


def detect_allergens_from_recipe(recipe_ingredients: list) -> dict:
    """
    Analisa automaticamente os ingredientes da receita e detecta Glúten, Lactose,
    Alérgenos Diretos (CONTÉM) e Derivados (CONTÉM DERIVADOS DE) conforme RDC 727/2022 da ANVISA.
    """
    import unicodedata

    def _norm(s: str) -> str:
        if not s:
            return ""
        nfkd = unicodedata.normalize("NFKD", str(s))
        return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower()

    has_gluten = False
    has_lactose = False
    direct_set = []
    deriv_set = []
    triggers = []

    def _add_unique(lst, item):
        if item not in lst:
            lst.append(item)

    plant_milks = (
        "leite de coco", "leite de soja", "leite de amendoa", "leite de aveia",
        "leite de arroz", "leite de castanha", "leite vegetal",
    )
    non_dairy_butters = (
        "manteiga de cacau", "manteiga de amendoim", "manteiga de coco", "manteiga de karite",
    )

    for ing in (recipe_ingredients or []):
        raw_d = str(ing.get("d", "") or "").strip()
        d_norm = _norm(raw_d)
        if not d_norm:
            continue

        is_gluten_free_explicit = ("sem gluten" in d_norm or "zero gluten" in d_norm)
        is_lactose_free_explicit = ("sem lactose" in d_norm or "zero lactose" in d_norm)

        # 1. Trigo, Centeio, Cevada, Aveia e Glúten
        if any(w in d_norm for w in ("trigo", "semolina", "macarrao", "lasanha", "biscoito", "bolacha", "pao ", "torrada")):
            if not is_gluten_free_explicit:
                has_gluten = True
                _add_unique(direct_set, "Trigo")
                _add_unique(deriv_set, "Trigo")
                triggers.append(f"Trigo / Glúten ({raw_d})")

        if "aveia" in d_norm:
            if not is_gluten_free_explicit:
                has_gluten = True
            _add_unique(direct_set, "Aveia")
            _add_unique(deriv_set, "Aveia")
            triggers.append(f"Aveia ({raw_d})")

        if "centeio" in d_norm:
            if not is_gluten_free_explicit:
                has_gluten = True
            _add_unique(direct_set, "Centeio")
            triggers.append(f"Centeio ({raw_d})")

        if any(w in d_norm for w in ("cevada", "malte")):
            if not is_gluten_free_explicit:
                has_gluten = True
            _add_unique(direct_set, "Cevada")
            _add_unique(deriv_set, "Cevada")
            triggers.append(f"Cevada ({raw_d})")

        # 2. Leite, Derivados Lácteos e Lactose
        is_plant_milk = any(pm in d_norm for pm in plant_milks)
        is_non_dairy_butter = any(nb in d_norm for nb in non_dairy_butters)

        dairy_direct_markers = ("leite integral", "leite desnatado", "leite semidesnatado", "leite de vaca", "leite em po", "leite fluido")
        dairy_deriv_markers = (
            "leite condensado", "creme de leite", "doce de leite", "manteiga", "queijo",
            "mucarela", "mussarela", "parmesao", "ricota", "requeijao", "iogurte",
            "cream cheese", "soro de leite", "whey", "coalhada", "nata",
            "chocolate ao leite", "chocolate branco", "achocolatado",
        )

        if not is_plant_milk and not is_non_dairy_butter:
            if any(m in d_norm for m in dairy_direct_markers) or ("leite" in d_norm and not any(m in d_norm for m in dairy_deriv_markers)):
                _add_unique(direct_set, "Leite")
                _add_unique(deriv_set, "Leite")
                if not is_lactose_free_explicit:
                    has_lactose = True
                triggers.append(f"Leite / Lactose ({raw_d})")
            elif any(m in d_norm for m in dairy_deriv_markers):
                _add_unique(direct_set, "Leite")
                _add_unique(deriv_set, "Leite")
                if not is_lactose_free_explicit:
                    has_lactose = True
                triggers.append(f"Derivados de Leite / Lactose ({raw_d})")

        # 3. Ovos
        if any(w in d_norm for w in ("ovo", "ovos", "gema", "clara de ovo", "clara,", "maionese", "merengue")):
            _add_unique(direct_set, "Ovos")
            triggers.append(f"Ovos ({raw_d})")

        # 4. Soja (incluindo óleo de soja e lecitina presente em chocolates)
        if any(w in d_norm for w in ("soja", "shoyu", "tofu", "lecitina")):
            if "oleo de soja" in d_norm or "lecitina" in d_norm:
                _add_unique(deriv_set, "Soja")
            else:
                _add_unique(direct_set, "Soja")
                _add_unique(deriv_set, "Soja")
            triggers.append(f"Soja ({raw_d})")
        elif "chocolate" in d_norm and "cacau 100%" not in d_norm:
            _add_unique(deriv_set, "Soja")
            triggers.append(f"Derivados de Soja / Lecitina ({raw_d})")

        # 5. Oleaginosas e Castanhas
        if any(w in d_norm for w in ("amendoim", "pacoca", "pe de moleque")):
            _add_unique(direct_set, "Amendoim")
            triggers.append(f"Amendoim ({raw_d})")
        if "amendoa" in d_norm:
            _add_unique(direct_set, "Amêndoa")
            triggers.append(f"Amêndoa ({raw_d})")
        if any(w in d_norm for w in ("avela", "nutella")):
            _add_unique(direct_set, "Avelãs")
            triggers.append(f"Avelãs ({raw_d})")
        if "castanha de caju" in d_norm or "castanha-de-caju" in d_norm or "caju, castanha" in d_norm:
            _add_unique(direct_set, "Castanha-de-caju")
            triggers.append(f"Castanha-de-caju ({raw_d})")
        if any(w in d_norm for w in ("castanha do para", "castanha-do-para", "castanha do brasil", "castanha-do-brasil")):
            _add_unique(direct_set, "Castanha-do-pará")
            triggers.append(f"Castanha-do-pará ({raw_d})")
        if "macadamia" in d_norm:
            _add_unique(direct_set, "Macadâmias")
            triggers.append(f"Macadâmias ({raw_d})")
        if "pistache" in d_norm:
            _add_unique(direct_set, "Pistaches")
            triggers.append(f"Pistaches ({raw_d})")
        if "peca" in d_norm and ("noz" in d_norm or "pecas" in d_norm):
            _add_unique(direct_set, "Pecãs")
            triggers.append(f"Pecãs ({raw_d})")
        elif any(w in d_norm for w in ("nozes", "noz,", "noz ")):
            _add_unique(direct_set, "Nozes")
            triggers.append(f"Nozes ({raw_d})")
        if "pinoli" in d_norm:
            _add_unique(direct_set, "Pinoli")
            triggers.append(f"Pinoli ({raw_d})")

        # 6. Peixes e Crustáceos
        if any(w in d_norm for w in ("peixe", "tilapia", "pescada", "salmao", "atum", "bacalhau", "sardinha", "merluza", "cacao", "corvina")):
            _add_unique(direct_set, "Peixes")
            triggers.append(f"Peixes ({raw_d})")
        if any(w in d_norm for w in ("camarao", "lagosta", "siri", "caranguejo", "crustaceo")):
            _add_unique(direct_set, "Crustáceos")
            triggers.append(f"Crustáceos ({raw_d})")

    return {
        "gluten_opt": "CONTÉM GLÚTEN" if has_gluten else "NÃO CONTÉM GLÚTEN",
        "lactose_opt": "CONTÉM LACTOSE" if has_lactose else "NÃO CONTÉM LACTOSE",
        "allergens_direct": direct_set,
        "allergens_deriv": deriv_set,
        "reasons": triggers,
    }



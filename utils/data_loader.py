import os
import json
import tempfile
import logging
import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)
_MODULE_VERSION = "2026.10.28.v1"

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
                nut_dict["Carboidrato disponível (g)"] = nut_dict["Carboidrato total (g)"]
                nut_dict["Açúcares totais (g)"] = nut_dict.get("Açúcares adicionados (g)", 0.0)
            
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

def load_saved_recipes(db_lock, username=None):
    from utils.db import is_sql_configured, load_recipes_sql, save_recipe_sql
    if is_sql_configured():
        recipes = load_recipes_sql(db_lock, username)
        
        # Migração automática: Se o banco SQL estiver vazio de receitas e existir o arquivo local JSON com receitas,
        # migramos as receitas locais para o banco SQL.
        if len(recipes) == 0 and os.path.exists(RECIPES_JSON_PATH):
            try:
                with open(RECIPES_JSON_PATH, "r", encoding="utf-8") as f:
                    local_recipes = json.load(f)
                for lr in local_recipes:
                    save_recipe_sql(lr["nome"], lr, db_lock)
                recipes = load_recipes_sql(db_lock, username)
                logger.info("Migração automática de receitas locais para o banco SQL realizada com sucesso!")
            except Exception as mig_err:
                logger.error(f"Erro na migração automática de receitas para SQL: {mig_err}", exc_info=True)
        return recipes
        
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
        return save_recipe_sql(name, new_recipe, db_lock)

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
            
        return safe_save_json(RECIPES_JSON_PATH, recipes)

def delete_recipe(name, db_lock):
    username = st.session_state.get("username", "")
    from utils.db import is_sql_configured, delete_recipe_sql
    if is_sql_configured():
        return delete_recipe_sql(name, username, db_lock)

    with db_lock:
        recipes = load_saved_recipes(db_lock)
        recipes = [r for r in recipes if r["nome"].lower() != name.lower() or (r.get("username", "") != "" and r.get("username", "").lower() != username.lower())]
        return safe_save_json(RECIPES_JSON_PATH, recipes)


FREE_RECIPE_LIMIT = 3


def get_user_plan_status(username: str, db_lock) -> dict:
    """
    Retorna o status do plano do usuário (Freemium até 3 fichas salvas vs. Pro Ilimitado).
    Um usuário possui o Plano Pro (fichas ilimitadas) se:
    - for administrador (is_admin = True)
    - tiver realizado qualquer compra/assinatura (transacoes_processadas não vazia)
    - tiver saldo >= 3 créditos liberados
    """
    from utils.auth import load_users
    uname = (username or "").strip()
    user_recipes = load_saved_recipes(db_lock, uname) if uname else []
    saved_count = len(user_recipes)
    existing_names = {r.get("nome", "").strip().lower() for r in user_recipes}

    is_pro = False
    try:
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
    from utils.data_loader import load_saved_recipes
    recipes = load_saved_recipes(db_lock)
    recipe_ingredients = []
    for idx, r in enumerate(recipes):
        r_user = r.get("username", "")
        if r_user == "" or r_user.lower() == username.lower():
            # Calculate 100g nutritional profile
            w_final = r.get("weight_final", 0.0)
            if w_final <= 0:
                continue
            
            raw_totals = {}
            total_cost = 0.0
            for ing in r.get("ingredients", []):
                factor = ing["w"] / 100.0
                total_cost += ing.get("cost_kg", 0.0) * (ing["w"] / 1000.0)
                
                # Fetch all keys from ing["n"] and add them up
                for key, val in ing["n"].items():
                    if isinstance(val, (int, float)):
                        raw_totals[key] = raw_totals.get(key, 0.0) + (val * factor)
                        
            # Normalize to 100g
            n_100g = {}
            for key, val in raw_totals.items():
                n_100g[key] = (val / w_final) * 100.0
                
            n_100g["Custo (R$/kg)"] = (total_cost / w_final) * 1000.0
                
            recipe_ingredients.append({
                "c": f"RECIPE-{idx}",
                "d": f"[RECEITA] {r['nome']}",
                "g": "Sub-receitas Salvas",
                "f": "Usuário",
                "n": n_100g
            })
    return recipe_ingredients


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
    sem códigos técnicos confusos.
    """
    code = food.get("c", "")
    clean_d = (food.get("d", "") or "").rstrip(", ").strip()
    source = food.get("f", "")
    if code in TOP_CONFECTIONERY_MAP:
        return TOP_CONFECTIONERY_MAP[code]["alias"]
    if source in ("CADASTRO", "Usuário"):
        return f"➕ {clean_d}"
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
    preço médio e dica prática em medidas caseiras (lata, caixinha, colher, xícara).
    """
    code = (food or {}).get("c", "")
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
    2. Filtro por categoria de confeitaria
    3. Busca por nome comercial (alias), descrição oficial ou código
    4. Ordenação inteligente: Top Confeitaria e cadastrados primeiro -> nome começando pelo termo -> TACO antes de TBCA
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
    if category == "🏆 Só os Mais Usados na Confeitaria":
        pool = [f for f in pool if f.get("c", "") in TOP_CONFECTIONERY_MAP]
    elif category and category != "⭐ Todos os Ingredientes Base":
        pool = [f for f in pool if classify_ingredient_category(f) == category]

    q_norm = _norm((search_query or "").strip())
    q_words = [w for w in q_norm.split() if w]

    # 3. Se não há termo de busca, retornar os Top Confeitaria + Cadastrados + Ingredientes TACO ordenados
    if not q_words:
        def _default_sort_key(food):
            code = food.get("c", "")
            source = food.get("f", "")
            if code in TOP_CONFECTIONERY_MAP:
                return (0, TOP_CONFECTIONERY_MAP[code]["rank"], "")
            if source in ("CADASTRO", "Usuário"):
                return (1, 0, _norm(food.get("d", "")))
            if source == "TACO":
                return (2, 0, _norm(food.get("d", "")))
            return (3, 0, _norm(food.get("d", "")))

        return sorted(pool, key=_default_sort_key)[:120]

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


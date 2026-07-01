import os
import json
import tempfile
import logging
import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)

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

@st.cache_data(ttl=60)
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

def load_saved_recipes(db_lock):
    with db_lock:
        if not os.path.exists(RECIPES_JSON_PATH):
            return []
        try:
            with open(RECIPES_JSON_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Erro ao carregar receitas salvas: {e}", exc_info=True)
            st.error(f"Erro ao carregar receitas salvas: {e}")
            return []

def save_recipe(name, db_lock):
    with db_lock:
        recipes = load_saved_recipes(db_lock)
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
            "date_saved": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
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
    with db_lock:
        recipes = load_saved_recipes(db_lock)
        username = st.session_state.get("username", "")
        recipes = [r for r in recipes if r["nome"].lower() != name.lower() or (r.get("username", "") != "" and r.get("username", "").lower() != username.lower())]
        return safe_save_json(RECIPES_JSON_PATH, recipes)



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

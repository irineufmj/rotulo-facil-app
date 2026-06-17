import streamlit as st
import json
import os
import pandas as pd
import io
import math
from decimal import Decimal, ROUND_HALF_UP
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# Configuração da página Streamlit
st.set_page_config(
    page_title="Rotuladora Nutricional ANVISA | TBCA & TACO",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilos CSS premium para a interface Streamlit
st.markdown("""
<style>
    .main-title {
        font-family: 'Outfit', sans-serif;
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(to right, #059669, #2563eb);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }
    .subtitle {
        font-size: 0.95rem;
        color: #6b7280;
        margin-bottom: 1.5rem;
    }
    .anvisa-table-container {
        background-color: #ffffff;
        padding: 1.5rem;
        border-radius: 12px;
        border: 2px solid #111111;
        max-width: 420px;
        margin: 0 auto;
    }
    .anvisa-table {
        width: 100%;
        border-collapse: collapse;
        color: #000000 !important;
        font-family: 'Arial', sans-serif;
        font-size: 11px;
    }
    .anvisa-table th, .anvisa-table td {
        border: 1px solid #000000;
        padding: 4px 6px;
        text-align: left;
        color: #000000 !important;
    }
    .anvisa-table td.num {
        text-align: right;
    }
    .anvisa-table tr.header-row th {
        font-size: 13px;
        font-weight: bold;
        text-align: center;
        border-bottom: 2px solid #000000;
    }
    .anvisa-table tr.sub-header-row td {
        font-weight: bold;
        background-color: #f3f4f6;
    }
    .anvisa-table tr.indent-row td.name {
        padding-left: 15px;
    }
    .lupa-box {
        border: 3px solid #000000;
        background-color: #ffffff;
        padding: 8px 12px;
        border-radius: 8px;
        color: #000000 !important;
        font-family: 'Arial Black', sans-serif;
        font-size: 12px;
        max-width: 420px;
        margin: 1rem auto;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .lupa-icon {
        font-size: 24px;
    }
    .lupa-text-bold {
        font-weight: 900;
        text-transform: uppercase;
        font-size: 14px;
        color: #000000 !important;
    }
    .legal-box {
        background-color: #f9fafb;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 1rem;
        margin-top: 1rem;
        font-family: 'Courier New', monospace;
        font-size: 0.9rem;
    }
</style>
""", unsafe_allow_html=True)

CUSTOM_CSV_PATH = "custom_ingredients.csv"

# --- INICIALIZAÇÃO E LEITURA DE DADOS ---

# Inicializar CSV de ingredientes customizados caso não exista
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

# Carregar dados unificados
@st.cache_data(ttl=60) # Recarrega a cada 60s para atualizar novos cadastros
def load_unified_data():
    # Carregar JSON base
    json_path = "alimentos_unified.json"
    if not os.path.exists(json_path):
        json_path = os.path.join(os.path.dirname(__file__), "alimentos_unified.json")
    
    with open(json_path, "r", encoding="utf-8-sig") as f:
        foods = json.load(f)
    
    # Carregar Customizados do CSV
    try:
        custom_df = pd.read_csv(CUSTOM_CSV_PATH, encoding="utf-8-sig")
        for idx, row in custom_df.iterrows():
            nut_dict = {}
            for col in custom_df.columns:
                if col not in ["codigo", "descricao", "classe", "fonte"] and pd.notna(row[col]):
                    nut_dict[col] = float(row[col])
            
            # Adicionar fallback para Carboidrato disponível e Açúcares totais
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

foods_data = load_unified_data()

# Inicializar estados de sessão
if "recipe" not in st.session_state:
    st.session_state.recipe = []
if "weight_final" not in st.session_state:
    st.session_state.weight_final = 0.0
if "portion_size" not in st.session_state:
    st.session_state.portion_size = 60.0
if "case_measure" not in st.session_state:
    st.session_state.case_measure = "1 unidade"
if "gluten_opt" not in st.session_state:
    st.session_state.gluten_opt = "NÃO CONTÉM GLÚTEN"
if "lactose_opt" not in st.session_state:
    st.session_state.lactose_opt = "NÃO CONTÉM LACTOSE"
if "allergens_direct" not in st.session_state:
    st.session_state.allergens_direct = []
if "allergens_deriv" not in st.session_state:
    st.session_state.allergens_deriv = []
if "allergens_may_contain" not in st.session_state:
    st.session_state.allergens_may_contain = []
if "calculated" not in st.session_state:
    st.session_state.calculated = False
if "product_type" not in st.session_state:
    st.session_state.product_type = "Sólido ou Semissólido"

# --- VALORES DIÁRIOS DE REFERÊNCIA (VDR) ANVISA ---
VDR = {
    "Energia (kcal)": 2000.0,
    "Carboidrato total (g)": 300.0,
    "Açúcares adicionados (g)": 50.0,
    "Proteína (g)": 50.0,
    "Lipídios (g)": 65.0,
    "Gorduras saturadas (g)": 20.0,
    "Fibra alimentar (g)": 25.0,
    "Sódio (mg)": 2000.0
}

# --- FUNÇÕES AUXILIARES DE PROCESSAMENTO ---

# Obter valor numérico seguro do nutriente
def get_num_val(nutrients_dict, key):
    val = nutrients_dict.get(key, 0.0)
    if isinstance(val, (int, float)):
        return float(val)
    return 0.0

# Regra de arredondamento ANVISA (IN 75/2020)
def round_anvisa(value, nutrient_name):
    if value is None:
        return "0"
    
    def dec_round(val, decs):
        d = Decimal(f"{val:.10f}")
        prec = Decimal('1') if decs == 0 else Decimal('.' + '0' * decs)
        return float(d.quantize(prec, rounding=ROUND_HALF_UP))
    
    # 1. Regra para Valor Energético (kcal)
    if nutrient_name == "Energia (kcal)":
        return f"{int(dec_round(value, 0))}"
        
    # 2. Regra para Sódio (mg)
    if nutrient_name == "Sódio (mg)":
        if value <= 5.0:
            return "0"
        return f"{int(dec_round(value, 0))}"
        
    # 3. Regra para Gorduras Trans (g)
    if nutrient_name == "Gorduras trans (g)":
        if value <= 0.2:
            return "0"
        res = dec_round(value, 1)
        if res.is_integer():
            return f"{int(res)}"
        return f"{res}".replace('.', ',')

    # 4. Outros Macronutrientes (Carbos, Açúcares, Proteínas, Lipídios, Fibras)
    if value <= 0.5:
        return "0"
    elif value < 10.0:
        res = dec_round(value, 1)
        if res.is_integer():
            return f"{int(res)}"
        return f"{res}".replace('.', ',')
    else:
        return f"{int(dec_round(value, 0))}"

RECIPES_JSON_PATH = "receitas_salvas.json"

def load_saved_recipes():
    if not os.path.exists(RECIPES_JSON_PATH):
        return []
    try:
        with open(RECIPES_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Erro ao carregar receitas salvas: {e}")
        return []

def save_recipe(name):
    recipes = load_saved_recipes()
    new_recipe = {
        "nome": name,
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
    
    # Substituir se já existir com o mesmo nome
    existing_idx = -1
    for idx, r in enumerate(recipes):
        if r["nome"].lower() == name.lower():
            existing_idx = idx
            break
            
    if existing_idx >= 0:
        recipes[existing_idx] = new_recipe
    else:
        recipes.append(new_recipe)
        
    try:
        with open(RECIPES_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(recipes, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        st.error(f"Erro ao salvar receita: {e}")
        return False

def delete_recipe(name):
    recipes = load_saved_recipes()
    recipes = [r for r in recipes if r["nome"].lower() != name.lower()]
    try:
        with open(RECIPES_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(recipes, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        st.error(f"Erro ao deletar receita: {e}")
        return False

@st.dialog("Salvar Receita")
def save_recipe_dialog():
    st.write("Digite o nome para salvar a receita atual com seus ingredientes e configurações.")
    name = st.text_input("Nome da Receita:", placeholder="Ex: Bolo de Cenoura com Chocolate", key="new_recipe_name")
    if st.button("Confirmar e Salvar", type="primary", use_container_width=True):
        if name.strip():
            if save_recipe(name.strip()):
                st.success(f"Receita '{name.strip()}' salva com sucesso!")
                st.rerun()
        else:
            st.error("Por favor, digite um nome para a receita.")

# --- TABS PRINCIPAIS ---
tab_app, tab_receitas, tab_cadastro = st.tabs([
    "📋 Calculadora & Rótulo ANVISA", 
    "📁 Minhas Receitas Salvas", 
    "➕ Cadastrar Novo Ingrediente"
])

# ==============================================================================
# TAB 1: CALCULADORA E RÓTULO
# ==============================================================================
with tab_app:
    # Cabeçalho do App
    st.markdown('<h1 class="main-title">📋 Rotuladora Nutricional ANVISA</h1>', unsafe_allow_html=True)
    st.markdown('<p class="subtitle">Buscador unificado TBCA + TACO, montador de receitas e gerador de rótulos de acordo com as normas ANVISA.</p>', unsafe_allow_html=True)
    
    # Grid de Layout
    col_input, col_label = st.columns([1.1, 0.9])
    
    with col_input:
        st.markdown("### 🍳 Montador da Receita")
        
        # Seleção de ingredientes (sempre fora do formulário para busca interativa funcionar)
        search_query = st.text_input(
            "Pesquise o ingrediente (nome ou código):",
            placeholder="Ex: Arroz, Farinha de Trigo, CUSTOM-1...",
            key="recipe_search"
        )
        
        filtered_for_recipe = []
        q = search_query.lower().strip()
        if q:
            # Filtrar ingredientes que contêm o termo buscado
            matched_foods = [f for f in foods_data if q in f["d"].lower() or q in f["c"].lower()]
            
            # Função de cálculo de score de relevância (menor score = maior prioridade)
            def get_match_score(food):
                desc = food["d"].lower()
                code = food["c"].lower()
                
                # 1. Correspondência exata de código
                if code == q:
                    return (0, 0, 0, len(desc))
                    
                # 2. Correspondência na descrição
                pos = desc.find(q)
                if pos >= 0:
                    is_start = 0 if pos == 0 else 1
                    # Verificar se o termo é uma palavra inteira (fronteira de palavra)
                    before_char_ok = (pos == 0 or not desc[pos-1].isalnum())
                    after_char_ok = (pos + len(q) == len(desc) or not desc[pos + len(q)].isalnum())
                    word_boundary = 0 if (before_char_ok and after_char_ok) else 1
                    
                    return (1, is_start, word_boundary, pos, len(desc))
                    
                # 3. Correspondência parcial de código
                pos_code = code.find(q)
                if pos_code >= 0:
                    return (2, 0, 0, pos_code, len(desc))
                    
                return (3, 0, 0, 0, len(desc))
                
            # Ordenar os resultados por relevância
            filtered_for_recipe = sorted(matched_foods, key=get_match_score)
        else:
            filtered_for_recipe = foods_data[:20] # Top 20 como padrão
            
        selected_recipe_food = st.selectbox(
            "Selecione o ingrediente da lista:",
            options=filtered_for_recipe,
            format_func=lambda x: f"[{x['f']}] {x['c']} - {x['d']}"
        )
        
        col_w, col_btn = st.columns([2, 1])
        ing_weight = col_w.number_input("Peso utilizado (g):", min_value=0.1, value=100.0, step=10.0)
        
        if col_btn.button("Adicionar à Receita", type="primary", use_container_width=True):
            st.session_state.recipe.append({
                "c": selected_recipe_food["c"],
                "d": selected_recipe_food["d"],
                "f": selected_recipe_food["f"],
                "w": ing_weight,
                "n": selected_recipe_food["n"]
            })
            st.session_state.calculated = False
            # Recalcular peso final padrão
            st.session_state.weight_final = sum(ing["w"] for ing in st.session_state.recipe)
            st.toast(f"**{selected_recipe_food['d']}** adicionado à receita!")
            st.rerun()
            
        st.markdown("---")
        
        # Se houver ingredientes, renderizamos o formulário
        if len(st.session_state.recipe) > 0:
            col_hdr, col_clr = st.columns([3, 1])
            col_hdr.markdown("### 🛒 Ingredientes na Receita")
            if col_clr.button("Limpar Tudo", type="secondary", use_container_width=True):
                st.session_state.recipe = []
                st.session_state.weight_final = 0.0
                st.session_state.calculated = False
                st.toast("Receita limpa!")
                st.rerun()
                
            # Formulário de controle de processamento
            with st.form("form_calculadora_rotulo"):
                st.markdown("##### Ajuste os Pesos (g) ou marque para remover:")
                
                # Lista de ingredientes dentro do form
                new_recipe_list = []
                for idx, ing in enumerate(st.session_state.recipe):
                    col_ing_name, col_ing_weight, col_ing_del = st.columns([2.5, 1.5, 0.5])
                    col_ing_name.markdown(f"**{ing['d']}**<br><small style='color: gray;'>{ing['f']} | {ing['c']}</small>", unsafe_allow_html=True)
                    
                    w_val = col_ing_weight.number_input(
                        "Peso (g)",
                        min_value=0.1,
                        value=float(ing['w']),
                        key=f"ing_w_{idx}_{ing['c']}",
                        step=5.0,
                        label_visibility="collapsed"
                    )
                    
                    rem_val = col_ing_del.checkbox("🗑️", key=f"ing_rem_{idx}_{ing['c']}", help="Remover ingrediente")
                    
                    new_recipe_list.append((ing, w_val, rem_val))
                
                st.markdown("---")
                
                # Parâmetros de Rendimento
                st.markdown("##### ⚖️ Rendimento e Porcionamento (Obrigatório)")
                col_rend1, col_rend2, col_rend3 = st.columns(3)
                
                product_type_options = ["Sólido ou Semissólido", "Líquido"]
                product_type_index = product_type_options.index(st.session_state.product_type) if st.session_state.product_type in product_type_options else 0
                product_type = col_rend1.selectbox(
                    "Tipo de Alimento:",
                    options=product_type_options,
                    index=product_type_index,
                    key="product_type_widget",
                    help="Determina os limites oficiais da ANVISA para os alertas da lupa frontal."
                )
                
                # Garante que o peso final não seja 0 se tiver ingredientes
                total_raw_weight = sum(ing["w"] for ing in st.session_state.recipe)
                if st.session_state.weight_final <= 0.0:
                    st.session_state.weight_final = total_raw_weight
                
                weight_final = col_rend2.number_input(
                    "Peso/Vol. Final do Pronto (g/ml):",
                    min_value=1.0,
                    value=float(st.session_state.weight_final),
                    key="weight_final_widget",
                    help="O peso/volume total após cozimento. Considera perda por evaporação ou ganho de água."
                )
                
                portion_size = col_rend3.number_input(
                    "Tamanho da Porção (g/ml):",
                    min_value=1.0,
                    value=float(st.session_state.portion_size),
                    step=5.0,
                    key="portion_size_widget",
                    help="O tamanho de porção definido para a rotulagem nutricional (ex: 60g para bolos, 20g para biscoitos)."
                )
                
                case_measure = st.text_input(
                    "Medida Caseira da Porção:",
                    placeholder="Ex: 1 unidade, 2 fatias, 1 colher de sopa...",
                    value=st.session_state.case_measure,
                    key="case_measure_widget"
                )
                
                # Checkbox de Glúten, Lactose e Alérgenos
                st.markdown("##### 🏷️ Declarações e Alérgenos")
                col_dec1, col_dec2 = st.columns(2)
                
                gluten_options = ["NÃO CONTÉM GLÚTEN", "CONTÉM GLÚTEN"]
                gluten_index = gluten_options.index(st.session_state.gluten_opt) if st.session_state.gluten_opt in gluten_options else 0
                gluten_opt = col_dec1.radio(
                    "Glúten:", 
                    options=gluten_options,
                    index=gluten_index,
                    key="gluten_opt_widget"
                )
                
                lactose_options = ["NÃO CONTÉM LACTOSE", "CONTÉM LACTOSE"]
                lactose_index = lactose_options.index(st.session_state.lactose_opt) if st.session_state.lactose_opt in lactose_options else 0
                lactose_opt = col_dec2.radio(
                    "Lactose:", 
                    options=lactose_options,
                    index=lactose_index,
                    key="lactose_opt_widget"
                )
                
                allergens_list = [
                    "Trigo", "Centeio", "Cevada", "Aveia", "Crustáceos", "Ovos", "Pe魚es", 
                    "Amendoim", "Soja", "Leite", "Amêndoa", "Avelãs", "Castanha-de-caju", 
                    "Castanha-do-pará", "Macadâmias", "Nozes", "Pecãs", "Pistaches", "Pinoli"
                ]
                st.markdown("**Seletor de Alérgenos (RDC 26/2015):**")
                selected_allergens_direct = st.multiselect(
                    "1. CONTÉM (Ingredientes alérgenos diretos):",
                    options=allergens_list,
                    default=st.session_state.allergens_direct,
                    key="allergens_direct_widget"
                )
                selected_allergens_deriv = st.multiselect(
                    "2. CONTÉM DERIVADOS DE (Ingredientes derivados):",
                    options=allergens_list,
                    default=st.session_state.allergens_deriv,
                    key="allergens_deriv_widget"
                )
                selected_allergens_may_contain = st.multiselect(
                    "3. PODE CONTER (Contaminação cruzada/traços):",
                    options=allergens_list,
                    default=st.session_state.allergens_may_contain,
                    key="allergens_may_contain_widget"
                )
                
                # Botão destacado
                calculate_btn = st.form_submit_button("Calcular Rótulo Oficial", type="primary", use_container_width=True)
                
                if calculate_btn:
                    # Atualizar lista de ingredientes removendo os marcados e ajustando os pesos
                    processed_recipe = []
                    for ing, w, rem in new_recipe_list:
                        if not rem:
                            ing_copy = ing.copy()
                            ing_copy["w"] = w
                            processed_recipe.append(ing_copy)
                    
                    st.session_state.recipe = processed_recipe
                    st.session_state.weight_final = weight_final
                    st.session_state.portion_size = portion_size
                    st.session_state.case_measure = case_measure
                    st.session_state.gluten_opt = gluten_opt
                    st.session_state.lactose_opt = lactose_opt
                    st.session_state.allergens_direct = selected_allergens_direct
                    st.session_state.allergens_deriv = selected_allergens_deriv
                    st.session_state.allergens_may_contain = selected_allergens_may_contain
                    st.session_state.product_type = product_type
                    
                    if len(processed_recipe) == 0:
                        st.session_state.calculated = False
                        st.warning("A receita ficou vazia. Por favor, adicione ingredientes.")
                    else:
                        st.session_state.calculated = True
                        st.toast("Rótulo oficial calculado com sucesso!")
                    
                    st.rerun()
        else:
            st.info("Adicione ingredientes à receita para iniciar os cálculos.")

    # --- PROCESSAMENTO DOS TOTAIS DA RECEITA ---
    if len(st.session_state.recipe) > 0 and st.session_state.calculated:
        # Carregar variáveis do estado da sessão para segurança e escopo limpo
        weight_final = st.session_state.weight_final
        portion_size = st.session_state.portion_size
        case_measure = st.session_state.case_measure
        gluten_opt = st.session_state.gluten_opt
        lactose_opt = st.session_state.lactose_opt
        allergens_direct = st.session_state.allergens_direct
        allergens_deriv = st.session_state.allergens_deriv
        allergens_may_contain = st.session_state.allergens_may_contain
        product_type = st.session_state.get("product_type", "Sólido ou Semissólido")

        # 1. Somar nutrientes totais ponderados pelo peso dos ingredientes
        raw_totals = {
            "Energia (kcal)": 0.0,
            "Carboidrato total (g)": 0.0,
            "Açúcares totais (g)": 0.0,
            "Açúcares adicionados (g)": 0.0,
            "Proteína (g)": 0.0,
            "Lipídios (g)": 0.0,
            "Gorduras saturadas (g)": 0.0,
            "Gorduras trans (g)": 0.0,
            "Fibra alimentar (g)": 0.0,
            "Sódio (mg)": 0.0
        }
        
        for ing in st.session_state.recipe:
            factor = ing["w"] / 100.0
            
            raw_totals["Energia (kcal)"] += get_num_val(ing["n"], "Energia (kcal)") * factor
            
            carb = ing["n"].get("Carboidrato total (g)", ing["n"].get("Carboidrato disponível (g)", 0.0))
            raw_totals["Carboidrato total (g)"] += get_num_val({"c": carb}, "c") * factor
            
            sug_tot = ing["n"].get("Açúcares totais (g)", ing["n"].get("Açúcares adicionados (g)", 0.0))
            raw_totals["Açúcares totais (g)"] += get_num_val({"s": sug_tot}, "s") * factor
            
            raw_totals["Açúcares adicionados (g)"] += get_num_val(ing["n"], "Açúcares adicionados (g)") * factor
            raw_totals["Proteína (g)"] += get_num_val(ing["n"], "Proteína (g)") * factor
            raw_totals["Lipídios (g)"] += get_num_val(ing["n"], "Lipídios (g)") * factor
            raw_totals["Gorduras saturadas (g)"] += get_num_val(ing["n"], "Gorduras saturadas (g)") * factor
            raw_totals["Gorduras trans (g)"] += get_num_val(ing["n"], "Gorduras trans (g)") * factor
            raw_totals["Fibra alimentar (g)"] += get_num_val(ing["n"], "Fibra alimentar (g)") * factor
            raw_totals["Sódio (mg)"] += get_num_val(ing["n"], "Sódio (mg)") * factor
            
        # 2. Calcular valores por 100g do produto pronto (Concentrado pelo peso final)
        totals_100g = {}
        for key in raw_totals.keys():
            totals_100g[key] = (raw_totals[key] / weight_final) * 100.0
            
        # 3. Calcular valores por porção comercial
        totals_portion = {}
        for key in raw_totals.keys():
            totals_portion[key] = (totals_100g[key] * portion_size) / 100.0
            
        # 4. Calcular %VD para a porção
        vd_percents = {}
        for key, vdr_val in VDR.items():
            vd_percents[key] = round((totals_portion[key] / vdr_val) * 100)
            
        # --- VERIFICAÇÃO DE ROTULAGEM FRONTAL (LUPA) ---
        # Limites de acordo com IN 75/2020 (Sólidos vs Líquidos)
        if product_type == "Líquido":
            alto_acucar = totals_100g["Açúcares adicionados (g)"] >= 7.5
            alto_gordura = totals_100g["Gorduras saturadas (g)"] >= 3.0
            alto_sodio = totals_100g["Sódio (mg)"] >= 300.0
            col_100_label = "100 ml"
            col_portion_label = f"{int(portion_size)} ml"
            col_unit = "ml"
        else:
            alto_acucar = totals_100g["Açúcares adicionados (g)"] >= 15.0
            alto_gordura = totals_100g["Gorduras saturadas (g)"] >= 6.0
            alto_sodio = totals_100g["Sódio (mg)"] >= 600.0
            col_100_label = "100 g"
            col_portion_label = f"{int(portion_size)} g"
            col_unit = "g"

        # --- APLICAR ARREDONDAMENTOS PARA EXIBIÇÃO ---
        display_100g = {}
        display_portion = {}
        
        for key in raw_totals.keys():
            display_100g[key] = round_anvisa(totals_100g[key], key)
            display_portion[key] = round_anvisa(totals_portion[key], key)

        # Exibir painel direito (Visualização da Tabela ANVISA, Lupa e Textos Legais)
        with col_label:
            st.markdown("### 📋 Pré-visualização do Rótulo")
            
            # Calcular número de porções conforme regras da ANVISA
            n_raw = weight_final / portion_size
            if n_raw < 1.5:
                n_porcoes_str = "Cerca de 1"
            elif n_raw <= 10.0:
                # Arredonda para o meio (0.5) mais próximo
                val_rounded = round(n_raw * 2) / 2
                n_porcoes_str = f"Cerca de {str(val_rounded).replace('.', ',')}"
                if n_porcoes_str.endswith(',0'):
                    n_porcoes_str = n_porcoes_str[:-2]
            else:
                n_porcoes_str = f"Cerca de {int(round(n_raw))}"
            
            # --- Renderização HTML da Tabela ANVISA ---
            table_html = f"""
            <div class="anvisa-table-container">
                <table class="anvisa-table">
                    <tr class="header-row">
                        <th colspan="4">INFORMAÇÃO NUTRICIONAL</th>
                    </tr>
                    <tr>
                        <td colspan="4" style="border-bottom: 2px solid #000;">
                            {n_porcoes_str} porções por embalagem<br>
                            Porção: {int(portion_size)} {col_unit} ({case_measure})
                        </td>
                    </tr>
                    <tr style="font-weight: bold; text-align: center; background-color: #eee;">
                         <td>Colunas</td>
                         <td style="text-align: right; width: 60px;">{col_100_label}</td>
                         <td style="text-align: right; width: 70px;">{col_portion_label}</td>
                        <td style="text-align: right; width: 50px;">%VD*</td>
                    </tr>
                    <tr>
                        <td>Valor energético (kcal)</td>
                        <td class="num">{display_100g['Energia (kcal)']}</td>
                        <td class="num">{display_portion['Energia (kcal)']}</td>
                        <td class="num">{int(vd_percents['Energia (kcal)'])}</td>
                    </tr>
                    <tr>
                        <td>Carboidratos (g)</td>
                        <td class="num">{display_100g['Carboidrato total (g)']}</td>
                        <td class="num">{display_portion['Carboidrato total (g)']}</td>
                        <td class="num">{int(vd_percents['Carboidrato total (g)'])}</td>
                    </tr>
                    <tr class="indent-row">
                        <td class="name">Açúcares totais (g)</td>
                        <td class="num">{display_100g['Açúcares totais (g)']}</td>
                        <td class="num">{display_portion['Açúcares totais (g)']}</td>
                        <td class="num">-</td>
                    </tr>
                    <tr class="indent-row">
                        <td class="name">Açúcares adicionados (g)</td>
                        <td class="num">{display_100g['Açúcares adicionados (g)']}</td>
                        <td class="num">{display_portion['Açúcares adicionados (g)']}</td>
                        <td class="num">{int(vd_percents['Açúcares adicionados (g)'])}</td>
                    </tr>
                    <tr>
                        <td>Proteínas (g)</td>
                        <td class="num">{display_100g['Proteína (g)']}</td>
                        <td class="num">{display_portion['Proteína (g)']}</td>
                        <td class="num">{int(vd_percents['Proteína (g)'])}</td>
                    </tr>
                    <tr>
                        <td>Gorduras totais (g)</td>
                        <td class="num">{display_100g['Lipídios (g)']}</td>
                        <td class="num">{display_portion['Lipídios (g)']}</td>
                        <td class="num">{int(vd_percents['Lipídios (g)'])}</td>
                    </tr>
                    <tr class="indent-row">
                        <td class="name">Gorduras saturadas (g)</td>
                        <td class="num">{display_100g['Gorduras saturadas (g)']}</td>
                        <td class="num">{display_portion['Gorduras saturadas (g)']}</td>
                        <td class="num">{int(vd_percents['Gorduras saturadas (g)'])}</td>
                    </tr>
                    <tr class="indent-row">
                        <td class="name">Gorduras trans (g)</td>
                        <td class="num">{display_100g['Gorduras trans (g)']}</td>
                        <td class="num">{display_portion['Gorduras trans (g)']}</td>
                        <td class="num">-</td>
                    </tr>
                    <tr>
                        <td>Fibra alimentar (g)</td>
                        <td class="num">{display_100g['Fibra alimentar (g)']}</td>
                        <td class="num">{display_portion['Fibra alimentar (g)']}</td>
                        <td class="num">{int(vd_percents['Fibra alimentar (g)'])}</td>
                    </tr>
                    <tr>
                        <td>Sódio (mg)</td>
                        <td class="num">{display_100g['Sódio (mg)']}</td>
                        <td class="num">{display_portion['Sódio (mg)']}</td>
                        <td class="num">{int(vd_percents['Sódio (mg)'])}</td>
                    </tr>
                    <tr>
                        <td colspan="4" style="font-size: 8px; border-top: 2px solid #000; text-align: justify;">
                            * Percentual de valores diários fornecidos pela porção.
                        </td>
                    </tr>
                </table>
            </div>
            """
            st.markdown(table_html, unsafe_allow_html=True)
            
            # --- Renderização Visual das Lupas ---
            if alto_acucar or alto_gordura or alto_sodio:
                lupa_html = """
                <div class="lupa-box">
                    <span class="lupa-icon">🔍</span>
                    <div>
                        <div class="lupa-text-bold">Alto em:</div>
                """
                if alto_acucar:
                    lupa_html += "• AÇÚCAR ADICIONADO<br>"
                if alto_gordura:
                    lupa_html += "• GORDURA SATURADA<br>"
                if alto_sodio:
                    lupa_html += "• SÓDIO<br>"
                lupa_html += """
                    </div>
                </div>
                """
                st.markdown(lupa_html, unsafe_allow_html=True)
                
            # --- Lista de Ingredientes Decrescente ---
            # Ordenar ingredientes por peso decrescente
            sorted_ingredients = sorted(st.session_state.recipe, key=lambda x: x["w"], reverse=True)
            ing_names = [ing["d"].upper() for ing in sorted_ingredients]
            ing_text = ", ".join(ing_names)
            
            # --- Alérgenos e Declarações Legais ---
            alergenicos_text_list = []
            if allergens_direct or allergens_deriv:
                if allergens_direct and allergens_deriv:
                    alergenicos_text_list.append("ALÉRGICOS: CONTÉM " + ", ".join([a.upper() for a in allergens_direct]) + " E DERIVADOS DE " + ", ".join([a.upper() for a in allergens_deriv]))
                elif allergens_direct:
                    alergenicos_text_list.append("ALÉRGICOS: CONTÉM " + ", ".join([a.upper() for a in allergens_direct]))
                else:
                    alergenicos_text_list.append("ALÉRGICOS: CONTÉM DERIVADOS DE " + ", ".join([a.upper() for a in allergens_deriv]))
            if allergens_may_contain:
                alergenicos_text_list.append("ALÉRGICOS: PODE CONTER " + ", ".join([a.upper() for a in allergens_may_contain]))
            
            alergenicos_text = ". ".join(alergenicos_text_list)
            
            st.markdown("##### 📝 Textos Legais (Cópia Rápida)")
            
            legal_html = f"""
            <div class="legal-box">
                <strong>INGREDIENTES:</strong> {ing_text}.<br><br>
                <strong>{gluten_opt}</strong><br>
                <strong>{lactose_opt}</strong>
            """
            if alergenicos_text:
                legal_html += f"<br><strong>{alergenicos_text}</strong>"
            legal_html += "</div>"
            
            st.markdown(legal_html, unsafe_allow_html=True)
            
            # --- GERAÇÃO DE PDF EM MEMÓRIA E DOWNLOAD ---
            
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib import colors
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            import io
            
            def create_pdf():
                pdf_buffer = io.BytesIO()
                doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
                story = []
                
                styles = getSampleStyleSheet()
                title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=18, spaceAfter=15)
                section_style = ParagraphStyle('Section', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=12, spaceAfter=8, spaceBefore=12)
                body_style = ParagraphStyle('Body', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=11)
                legal_style = ParagraphStyle('Legal', parent=styles['Normal'], fontName='Courier-Bold', fontSize=10, leading=13)
                
                story.append(Paragraph("<b>RELATÓRIO DE ROTULAGEM NUTRICIONAL OFICIAL</b>", title_style))
                story.append(Paragraph(f"Gerado em conformidade com RDC 429/2020 e IN 75/2020", body_style))
                story.append(Spacer(1, 15))
                
                # Dados da tabela
                table_data = [
                    [Paragraph("<b>INFORMAÇÃO NUTRICIONAL</b>", ParagraphStyle('H', parent=body_style, fontName='Helvetica-Bold', fontSize=11)), "", "", ""],
                    [Paragraph(f"{n_porcoes_str} porções por embalagem<br/>Porção: {int(portion_size)} {col_unit} ({case_measure})", body_style), "", "", ""],
                    ["", col_100_label, col_portion_label, "%VD*"],
                    ["Valor energético (kcal)", display_100g['Energia (kcal)'], display_portion['Energia (kcal)'], str(int(vd_percents['Energia (kcal)']))],
                    ["Carboidratos (g)", display_100g['Carboidrato total (g)'], display_portion['Carboidrato total (g)'], str(int(vd_percents['Carboidrato total (g)']))],
                    ["  Açúcares totais (g)", display_100g['Açúcares totais (g)'], display_portion['Açúcares totais (g)'], "-"],
                    ["  Açúcares adicionados (g)", display_100g['Açúcares adicionados (g)'], display_portion['Açúcares adicionados (g)'], str(int(vd_percents['Açúcares adicionados (g)']))],
                    ["Proteínas (g)", display_100g['Proteína (g)'], display_portion['Proteína (g)'], str(int(vd_percents['Proteína (g)']))],
                    ["Gorduras totais (g)", display_100g['Lipídios (g)'], display_portion['Lipídios (g)'], str(int(vd_percents['Lipídios (g)']))],
                    ["  Gorduras saturadas (g)", display_100g['Gorduras saturadas (g)'], display_portion['Gorduras saturadas (g)'], str(int(vd_percents['Gorduras saturadas (g)']))],
                    ["  Gorduras trans (g)", display_100g['Gorduras trans (g)'], display_portion['Gorduras trans (g)'], "-"],
                    ["Fibra alimentar (g)", display_100g['Fibra alimentar (g)'], display_portion['Fibra alimentar (g)'], str(int(vd_percents['Fibra alimentar (g)']))],
                    ["Sódio (mg)", display_100g['Sódio (mg)'], display_portion['Sódio (mg)'], str(int(vd_percents['Sódio (mg)']))],
                    [Paragraph("<font size=6>* Percentual de valores diários fornecidos pela porção.</font>", body_style), "", "", ""]
                ]
                
                t = Table(table_data, colWidths=[180, 50, 60, 45])
                t.setStyle(TableStyle([
                    ('SPAN', (0, 0), (3, 0)),
                    ('SPAN', (0, 1), (3, 1)),
                    ('SPAN', (0, 13), (3, 13)),
                    ('BOX', (0, 0), (-1, -1), 1.5, colors.black),
                    ('GRID', (0, 2), (-1, 12), 0.5, colors.black),
                    ('LINEBELOW', (0, 0), (3, 0), 1.5, colors.black),
                    ('LINEBELOW', (0, 1), (3, 1), 1.5, colors.black),
                    ('BACKGROUND', (0, 2), (-1, 2), colors.lightgrey),
                    ('ALIGN', (1, 2), (-1, -2), 'RIGHT'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ]))
                
                story.append(t)
                story.append(Spacer(1, 15))
                
                # Adicionar Lupa de aviso se houver
                if alto_acucar or alto_gordura or alto_sodio:
                    lupa_items = []
                    if alto_acucar: lupa_items.append("AÇÚCAR ADICIONADO")
                    if alto_gordura: lupa_items.append("GORDURA SATURADA")
                    if alto_sodio: lupa_items.append("SÓDIO")
                    
                    lupa_p = f"<b>ALTO EM:</b><br/>" + "<br/>".join([f"• {item}" for item in lupa_items])
                    
                    lupa_table_data = [[
                        Paragraph("<font size=20>🔍</font>", body_style),
                        Paragraph(lupa_p, ParagraphStyle('LupaText', parent=body_style, fontSize=11, leading=14))
                    ]]
                    
                    lupa_table = Table(lupa_table_data, colWidths=[30, 200])
                    lupa_table.setStyle(TableStyle([
                        ('BOX', (0, 0), (-1, -1), 2, colors.black),
                        ('BACKGROUND', (0, 0), (-1, -1), colors.white),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('PADDING', (0, 0), (-1, -1), 8)
                    ]))
                    story.append(lupa_table)
                    story.append(Spacer(1, 15))
                
                # Informações de ingredientes e alérgenos
                story.append(Paragraph("<b>DECLARAÇÃO DE INGREDIENTES E AVISOS LEGAIS</b>", section_style))
                
                ingredients_paragraph = f"<b>INGREDIENTES:</b> {ing_text}."
                story.append(Paragraph(ingredients_paragraph, legal_style))
                story.append(Spacer(1, 8))
                
                story.append(Paragraph(f"<b>{gluten_opt}</b>", legal_style))
                story.append(Paragraph(f"<b>{lactose_opt}</b>", legal_style))
                
                if alergenicos_text:
                    story.append(Paragraph(f"<b>{alergenicos_text}</b>", legal_style))
                    
                doc.build(story)
                pdf_buffer.seek(0)
                return pdf_buffer.getvalue()

            pdf_data = create_pdf()
            
            col_pdf, col_save = st.columns(2)
            with col_pdf:
                st.download_button(
                    label="📥 Gerar e Baixar PDF",
                    data=pdf_data,
                    file_name="rotulo_nutricional.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
            with col_save:
                if st.button("💾 Salvar Receita", type="secondary", use_container_width=True):
                    save_recipe_dialog()
                    
    elif len(st.session_state.recipe) > 0:
        with col_label:
            st.markdown("### 📋 Pré-visualização do Rótulo")
            st.info("⚠️ Alterações detectadas. Clique em **'Calcular Rótulo Oficial'** no painel esquerdo para processar a receita e visualizar a tabela oficial e os alertas.")
    else:
        with col_label:
            st.markdown("### 📋 Pré-visualização do Rótulo")
            st.info("Adicione ingredientes à receita para iniciar os cálculos.")

# ==============================================================================
# TAB: MINHAS RECEITAS SALVAS
# ==============================================================================
with tab_receitas:
    st.markdown("### 📁 Minhas Receitas Salvas")
    st.markdown("Consulte, carregue ou remova receitas salvas localmente no banco de dados do aplicativo.")
    
    saved_recipes = load_saved_recipes()
    
    if not saved_recipes:
        st.info("Nenhuma receita salva encontrada. Monte uma receita e clique em 'Salvar Receita' para salvá-la aqui.")
    else:
        recipes_dict = {r["nome"]: r for r in saved_recipes}
        
        selected_name = st.selectbox(
            "Selecione uma receita para gerenciar:",
            options=list(recipes_dict.keys()),
            key="saved_recipes_select"
        )
        
        if selected_name:
            recipe = recipes_dict[selected_name]
            st.markdown(f"**Data de Criação/Modificação:** `{recipe['date_saved']}`")
            
            ing_details = []
            for ing in recipe["ingredients"]:
                ing_details.append({
                    "Código": ing["c"],
                    "Descrição": ing["d"],
                    "Fonte": ing["f"],
                    "Peso Utilizado (g)": f"{ing['w']:.1f} g"
                })
            
            st.markdown("##### 🛒 Ingredientes da Receita:")
            st.table(pd.DataFrame(ing_details))
            
            st.markdown("##### ⚖️ Parâmetros Salvos:")
            p_col1, p_col2 = st.columns(2)
            with p_col1:
                st.markdown(f"""
                - **Peso Final do Produto Pronto:** {recipe['weight_final']:.1f} g
                - **Tamanho da Porção:** {recipe['portion_size']:.1f} g
                - **Medida Caseira:** {recipe['case_measure']}
                """)
            with p_col2:
                st.markdown(f"""
                - **Glúten:** {recipe['gluten_opt']}
                - **Lactose:** {recipe['lactose_opt']}
                - **Tipo:** {recipe.get('product_type', 'Sólido ou Semissólido')}
                - **Contém:** {', '.join(recipe.get('allergens_direct', [])) if recipe.get('allergens_direct') else 'Nenhum'}
                - **Contém Derivados de:** {', '.join(recipe.get('allergens_deriv', [])) if recipe.get('allergens_deriv') else 'Nenhum'}
                - **Pode Conter:** {', '.join(recipe.get('allergens_may_contain', [])) if recipe.get('allergens_may_contain') else 'Nenhum'}
                """)
                
            st.markdown("---")
            col_load, col_del = st.columns(2)
            
            with col_load:
                if st.button("🔌 Carregar e Recalcular Receita", type="primary", use_container_width=True):
                    st.session_state.recipe = recipe["ingredients"]
                    st.session_state.weight_final = recipe["weight_final"]
                    st.session_state.portion_size = recipe["portion_size"]
                    st.session_state.case_measure = recipe["case_measure"]
                    st.session_state.gluten_opt = recipe["gluten_opt"]
                    st.session_state.lactose_opt = recipe["lactose_opt"]
                    st.session_state.allergens_direct = recipe.get("allergens_direct", recipe.get("selected_allergens", []))
                    st.session_state.allergens_deriv = recipe.get("allergens_deriv", [])
                    st.session_state.allergens_may_contain = recipe.get("allergens_may_contain", [])
                    st.session_state.product_type = recipe.get("product_type", "Sólido ou Semissólido")
                    st.session_state.calculated = True
                    st.toast(f"Receita **{selected_name}** carregada com sucesso!")
                    st.rerun()
                    
            with col_del:
                if st.button("🗑️ Excluir Receita Permanentemente", type="secondary", use_container_width=True):
                    if delete_recipe(selected_name):
                        st.toast(f"Receita **{selected_name}** excluída com sucesso!")
                        st.rerun()

# ==============================================================================
# TAB 2: CADASTRAR NOVO INGREDIENTE
# ==============================================================================
with tab_cadastro:
    st.markdown("### ➕ Cadastrar Novo Ingrediente")
    st.markdown("Insira manualmente as informações nutricionais do ingrediente conforme o rótulo do fornecedor. O sistema converterá automaticamente para a base de 100g.")
    
    with st.form("form_cadastro_ingrediente", clear_on_submit=True):
        col_cad1, col_cad2 = st.columns(2)
        
        name_ing = col_cad1.text_input("Nome do Alimento / Ingrediente:", placeholder="Ex: Whey Protein Isolado Morango")
        portion_ref = col_cad2.number_input("Porção de Referência do Rótulo (g):", min_value=1.0, value=100.0, step=5.0, help="O peso da porção informada no rótulo (ex: 30g).")
        
        st.markdown("##### Nutrientes por Porção:")
        
        col_n1, col_n2, col_n3 = st.columns(3)
        kcal_portion = col_n1.number_input("Valor Energético (kcal):", min_value=0.0, value=0.0, step=5.0)
        carbs_portion = col_n2.number_input("Carboidratos (g):", min_value=0.0, value=0.0, step=1.0)
        sug_add_portion = col_n3.number_input("Açúcares Adicionados (g):", min_value=0.0, value=0.0, step=1.0)
        
        col_n4, col_n5, col_n6 = st.columns(3)
        prot_portion = col_n4.number_input("Proteínas (g):", min_value=0.0, value=0.0, step=1.0)
        fat_portion = col_n5.number_input("Gorduras Totais (g):", min_value=0.0, value=0.0, step=1.0)
        sat_fat_portion = col_n6.number_input("Gorduras Saturadas (g):", min_value=0.0, value=0.0, step=1.0)
        
        col_n7, col_n8, col_n9 = st.columns(3)
        trans_fat_portion = col_n7.number_input("Gorduras Trans (g):", min_value=0.0, value=0.0, step=0.1)
        fiber_portion = col_n8.number_input("Fibra Alimentar (g):", min_value=0.0, value=0.0, step=1.0)
        sodium_portion = col_n9.number_input("Sódio (mg):", min_value=0.0, value=0.0, step=10.0)
        
        submit_btn = st.form_submit_button("Salvar Ingrediente", type="primary")
        
        if submit_btn:
            if not name_ing.strip():
                st.error("Por favor, preencha o Nome do Alimento.")
            else:
                # Fator de conversão para 100g
                factor = 100.0 / portion_ref
                
                kcal_100g = kcal_portion * factor
                carbs_100g = carbs_portion * factor
                sug_add_100g = sug_add_portion * factor
                prot_100g = prot_portion * factor
                fat_100g = fat_portion * factor
                sat_fat_100g = sat_fat_portion * factor
                trans_fat_100g = trans_fat_portion * factor
                fiber_100g = fiber_portion * factor
                sodium_100g = sodium_portion * factor
                
                # Ler arquivo CSV existente
                try:
                    custom_df = pd.read_csv(CUSTOM_CSV_PATH, encoding="utf-8-sig")
                except Exception:
                    custom_df = pd.DataFrame()
                
                # Gerar código único
                new_id = len(custom_df) + 1
                new_code = f"CAD-{new_id:04d}"
                
                # Novo registro
                new_row = pd.DataFrame([{
                    "codigo": new_code,
                    "descricao": name_ing.strip(),
                    "classe": "Cadastrado Manualmente",
                    "fonte": "CADASTRO",
                    "Energia (kcal)": kcal_100g,
                    "Carboidrato total (g)": carbs_100g,
                    "Açúcares adicionados (g)": sug_add_100g,
                    "Proteína (g)": prot_100g,
                    "Lipídios (g)": fat_100g,
                    "Gorduras saturadas (g)": sat_fat_100g,
                    "Gorduras trans (g)": trans_fat_100g,
                    "Fibra alimentar (g)": fiber_100g,
                    "Sódio (mg)": sodium_100g
                }])
                
                # Salvar no CSV
                custom_df = pd.concat([custom_df, new_row], ignore_index=True)
                custom_df.to_csv(CUSTOM_CSV_PATH, index=False, encoding="utf-8-sig")
                
                st.success(f"Ingrediente **{name_ing.strip()}** cadastrado com código `{new_code}`!")
                # Forçar a recarga dos dados na sessão
                st.cache_data.clear()
                st.rerun()

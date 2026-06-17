import streamlit as st
import json
import os
import pandas as pd
import io
import math
import hashlib
import uuid
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
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "nome_produto" not in st.session_state:
    st.session_state.nome_produto = ""
if "peso_embalagem" not in st.session_state:
    st.session_state.peso_embalagem = 0.0
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

USERS_JSON_PATH = "usuarios.json"

def load_users():
    if not os.path.exists(USERS_JSON_PATH):
        return []
    try:
        with open(USERS_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Erro ao carregar usuários: {e}")
        return []

def save_users(users):
    try:
        with open(USERS_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        st.error(f"Erro ao salvar usuários: {e}")
        return False

def hash_password(password, salt=None):
    if not salt:
        salt = uuid.uuid4().hex
    hashed = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
    return f"{salt}:{hashed}"

def verify_password(stored_password, provided_password):
    if ":" not in stored_password:
        return False
    salt, hashed = stored_password.split(':')
    return hashed == hashlib.sha256((salt + provided_password).encode('utf-8')).hexdigest()

def register_user(username, password, lgpd_accepted):
    if not lgpd_accepted:
        return False, "Você precisa aceitar os termos da LGPD para se cadastrar."
    
    username_clean = username.strip()
    if not username_clean:
        return False, "O nome de usuário não pode ser vazio."
    if len(password) < 4:
        return False, "A senha deve conter pelo menos 4 caracteres."
        
    users = load_users()
    for u in users:
        if u["username"].lower() == username_clean.lower():
            return False, "Este nome de usuário já está em uso."
            
    new_user = {
        "username": username_clean,
        "password_hash": hash_password(password),
        "lgpd_accepted_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "lgpd_version": "1.0"
    }
    users.append(new_user)
    if save_users(users):
        return True, "Usuário cadastrado com sucesso!"
    return False, "Erro ao gravar cadastro no banco de dados."

def authenticate_user(username, password):
    username_clean = username.strip()
    if not username_clean or not password:
        return False, "Por favor, preencha todos os campos."
        
    users = load_users()
    for u in users:
        if u["username"].lower() == username_clean.lower():
            if verify_password(u["password_hash"], password):
                return True, u["username"]
            else:
                return False, "Senha incorreta."
    return False, "Usuário não encontrado."

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
    
    # Substituir se já existir com o mesmo nome e pertencer ao mesmo usuário
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
        
    try:
        with open(RECIPES_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(recipes, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        st.error(f"Erro ao salvar receita: {e}")
        return False

def delete_recipe(name):
    recipes = load_saved_recipes()
    username = st.session_state.get("username", "")
    # Manter receitas que pertencem a outros usuários ou que têm nome diferente
    recipes = [r for r in recipes if r["nome"].lower() != name.lower() or (r.get("username", "") != "" and r.get("username", "").lower() != username.lower())]
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

# --- LOGIN / CADASTRO FLOW ---
if not st.session_state.logged_in:
    # Cabeçalho da página de acesso
    st.markdown('<h1 class="main-title" style="text-align: center;">📋 Rótulo Fácil - Login</h1>', unsafe_allow_html=True)
    st.markdown('<p class="subtitle" style="text-align: center;">Gerador de Rótulos ANVISA em conformidade com as normas e dados unificados TBCA + TACO.</p>', unsafe_allow_html=True)
    
    # Criar uma caixa centralizada com colunas
    col_left, col_center, col_right = st.columns([1, 1.2, 1])
    
    with col_center:
        auth_mode = st.radio("Escolha uma opção:", ["Entrar", "Criar Nova Conta"], horizontal=True, label_visibility="collapsed")
        
        st.markdown("---")
        
        if auth_mode == "Entrar":
            st.markdown("### 🔑 Entrar no Sistema")
            login_user = st.text_input("Usuário:", placeholder="Digite seu nome de usuário", key="login_username_field")
            login_pass = st.text_input("Senha:", type="password", placeholder="Digite sua senha", key="login_password_field")
            
            if st.button("Acessar Painel", type="primary", use_container_width=True):
                success, result = authenticate_user(login_user, login_pass)
                if success:
                    st.session_state.logged_in = True
                    st.session_state.username = result
                    st.toast(f"Bem-vindo de volta, {result}!")
                    st.rerun()
                else:
                    st.error(result)
                    
        else: # Criar Nova Conta
            st.markdown("### 📝 Criar Nova Conta")
            new_user = st.text_input("Nome de Usuário:", placeholder="Escolha um nome de usuário", key="reg_username_field")
            new_pass = st.text_input("Senha:", type="password", placeholder="Mínimo de 4 caracteres", key="reg_password_field")
            new_pass_confirm = st.text_input("Confirme a Senha:", type="password", placeholder="Repita a senha anterior", key="reg_password_confirm_field")
            
            st.markdown("##### 🛡️ Termos de Uso e Política de Privacidade (LGPD)")
            with st.expander("Clique para ler os Termos de Uso e Política de Privacidade completos"):
                st.markdown("""
                **TERMO DE CONSENTIMENTO E PRIVACIDADE (LGPD)**
                
                De acordo com a Lei Geral de Proteção de Dados (Lei nº 13.709/2018), este termo informa como tratamos suas informações:
                
                1. **Quais dados coletamos:** Coletamos o nome de usuário fornecido por você para fins de identificação, e o hash criptografado da sua senha. Coletamos também as receitas, ingredientes e parametrizações que você salvar.
                2. **Finalidade:** O tratamento desses dados tem como única e exclusiva finalidade permitir que você gerencie, edite, exclua e visualize suas próprias receitas de forma privada.
                3. **Armazenamento e Compartilhamento:** Seus dados são salvos localmente no arquivo de dados do aplicativo. Não compartilhamos, vendemos ou divulgamos suas receitas ou credenciais para terceiros em hipótese alguma.
                4. **Exclusão de Dados:** Você é proprietário dos seus dados. A exclusão de uma receita pode ser feita diretamente por você. Para exclusão total da conta e de todas as suas receitas, entre em contato com o administrador.
                5. **Segurança:** As senhas são protegidas por criptografia de mão única (SHA-256) combinadas com um salt aleatório para evitar acessos não autorizados.
                
                Ao assinalar a caixa abaixo, você declara que compreende e aceita livremente os termos deste tratamento de dados.
                """)
            
            lgpd_accept = st.checkbox("Li e concordo com os Termos de Uso e Política de Privacidade de acordo com a LGPD.", key="lgpd_checkbox")
            
            if st.button("Cadastrar e Acessar", type="primary", use_container_width=True):
                if not new_user.strip() or not new_pass or not new_pass_confirm:
                    st.error("Por favor, preencha todos os campos do cadastro.")
                elif new_pass != new_pass_confirm:
                    st.error("As senhas digitadas não coincidem.")
                elif not lgpd_accept:
                    st.error("Você precisa aceitar os termos de privacidade da LGPD para prosseguir.")
                else:
                    success, msg = register_user(new_user, new_pass, lgpd_accept)
                    if success:
                        st.session_state.logged_in = True
                        st.session_state.username = new_user.strip()
                        st.success(msg)
                        st.toast(f"Conta criada! Bem-vindo, {new_user.strip()}!")
                        st.rerun()
                    else:
                        st.error(msg)
    st.stop()

# Sidebar do Usuário Conectado
with st.sidebar:
    st.markdown("### 👤 Usuário Conectado")
    st.markdown(f"Conectado como: **{st.session_state.username}**")
    if st.button("🚪 Sair da Conta", type="secondary", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state.recipe = []
        st.session_state.calculated = False
        st.session_state.nome_produto = ""
        st.session_state.peso_embalagem = 0.0
        st.toast("Você saiu da conta.")
        st.rerun()
    st.markdown("---")

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
                
                nome_produto = st.text_input(
                    "Nome Comercial do Produto:",
                    placeholder="Ex: Bolo de Cenoura Fit",
                    value=st.session_state.nome_produto,
                    key="nome_produto_widget",
                    help="O nome de venda do produto que será impresso no relatório oficial."
                )
                
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
                    "Rendimento da Receita (Peso Pronto) (g/ml):",
                    min_value=1.0,
                    value=float(st.session_state.weight_final),
                    key="weight_final_widget",
                    help="O peso/volume total após cozimento. Considera perda por evaporação ou ganho de água."
                )
                
                peso_embalagem = col_rend3.number_input(
                    "Peso Líquido na Embalagem (g/ml):",
                    min_value=0.0,
                    value=float(st.session_state.peso_embalagem),
                    step=10.0,
                    key="peso_embalagem_widget",
                    help="O peso líquido total da embalagem comercial. Se deixado como 0, usará o Rendimento da Receita para calcular as porções."
                )
                
                col_rend4, col_rend5 = st.columns(2)
                portion_size = col_rend4.number_input(
                    "Tamanho da Porção (g/ml):",
                    min_value=1.0,
                    value=float(st.session_state.portion_size),
                    step=5.0,
                    key="portion_size_widget",
                    help="O tamanho de porção definido para a rotulagem nutricional (ex: 60g para bolos, 20g para biscoitos)."
                )
                
                case_measure = col_rend5.text_input(
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
                    "Trigo", "Centeio", "Cevada", "Aveia", "Crustáceos", "Ovos", "Peixes", 
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
                    st.session_state.nome_produto = nome_produto
                    st.session_state.peso_embalagem = peso_embalagem
                    
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
        peso_embalagem = st.session_state.get("peso_embalagem", 0.0)

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
            
            # Exibir nome do produto no painel de pré-visualização
            if st.session_state.nome_produto:
                st.markdown(f"##### Produto: **{st.session_state.nome_produto}**")
            
            # Calcular número de porções conforme regras da ANVISA
            # Se peso_embalagem foi informado, calcula com base nele; senão, usa o rendimento da receita
            ref_weight = peso_embalagem if peso_embalagem > 0.0 else weight_final
            n_raw = ref_weight / portion_size
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
            
            # --- Renderização Visual das Lupas (Estilo Oficial ANVISA SVG) ---
            if alto_acucar or alto_gordura or alto_sodio:
                nutrients_list = []
                if alto_acucar: nutrients_list.append("AÇÚCAR ADICIONADO")
                if alto_gordura: nutrients_list.append("GORDURA SATURADA")
                if alto_sodio: nutrients_list.append("SÓDIO")
                
                nutrients_html = "".join([f"• {n}<br>" for n in nutrients_list])
                
                lupa_html = f"""
                <div style="border: 3px solid black; background-color: white; padding: 10px; max-width: 320px; font-family: Arial, sans-serif; color: black; display: flex; align-items: center; border-radius: 4px; margin: 15px auto;">
                    <!-- SVG Lupa Magnifier -->
                    <div style="flex-shrink: 0; margin-right: 15px; display: flex; align-items: center; justify-content: center;">
                        <svg viewBox="0 0 100 100" width="45" height="45">
                            <circle cx="42" cy="42" r="20" stroke="black" stroke-width="7" fill="white" />
                            <line x1="56" y1="56" x2="80" y2="80" stroke="black" stroke-width="9" stroke-linecap="round" />
                            <line x1="53" y1="53" x2="59" y2="59" stroke="black" stroke-width="11" />
                            <path d="M28 32 A14 14 0 0 1 48 24" stroke="black" stroke-width="2.5" fill="none" stroke-linecap="round" />
                        </svg>
                    </div>
                    <!-- Text Content -->
                    <div style="display: flex; flex-direction: column; justify-content: center; text-align: left;">
                        <div style="font-weight: 900; font-size: 15px; letter-spacing: 0.5px; line-height: 1.1; margin-bottom: 2px; color: black !important;">ALTO EM</div>
                        <div style="font-weight: 800; font-size: 11px; line-height: 1.3; letter-spacing: 0.2px; color: black !important;">
                            {nutrients_html}
                        </div>
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
                
                prod_name = st.session_state.nome_produto if st.session_state.nome_produto else "Não Informado"
                story.append(Paragraph(f"<b>Nome Comercial do Produto:</b> {prod_name}", ParagraphStyle('PName', parent=body_style, fontSize=10, leading=12)))
                
                ref_emb = f"{peso_embalagem:.1f} {col_unit}" if peso_embalagem > 0.0 else "Não Informado"
                story.append(Paragraph(f"<b>Rendimento da Receita:</b> {weight_final:.1f} {col_unit} | <b>Peso Líquido na Embalagem:</b> {ref_emb}", ParagraphStyle('PDetails', parent=body_style, fontSize=9, leading=11)))
                story.append(Paragraph(f"Gerado em conformidade com RDC 429/2020 e IN 75/2020", ParagraphStyle('PSub', parent=body_style, fontName='Helvetica-Oblique', fontSize=8, leading=10, textColor=colors.gray)))
                story.append(Spacer(1, 10))
                
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
                
                # Adicionar Lupa de aviso se houver (Vetorizado em PDF)
                if alto_acucar or alto_gordura or alto_sodio:
                    lupa_items = []
                    if alto_acucar: lupa_items.append("AÇÚCAR ADICIONADO")
                    if alto_gordura: lupa_items.append("GORDURA SATURADA")
                    if alto_sodio: lupa_items.append("SÓDIO")
                    
                    # Desenhar a lupa oficial usando ReportLab Shapes
                    from reportlab.graphics.shapes import Drawing, Circle, Line, Rect, String
                    
                    # Altura dinâmica baseada no número de itens
                    num_items = len(lupa_items)
                    box_height = 30 + (num_items * 13)
                    box_width = 230
                    
                    lupa_draw = Drawing(box_width, box_height)
                    
                    # Caixa com borda preta grossa e fundo branco
                    lupa_draw.add(Rect(0, 0, box_width, box_height, strokeColor=colors.black, fillColor=colors.white, strokeWidth=2))
                    
                    # Desenhar lupa (Magnifying Glass)
                    g_x = 22
                    g_y = box_height / 2 + 2 # Ajustar centro
                    
                    # Lente (círculo)
                    lupa_draw.add(Circle(g_x, g_y, 10, strokeColor=colors.black, fillColor=colors.white, strokeWidth=3))
                    # Cabo da lupa (diagonal para baixo e para a direita)
                    lupa_draw.add(Line(g_x + 7, g_y - 7, g_x + 16, g_y - 16, strokeColor=colors.black, strokeWidth=4, strokeLineCap=1))
                    
                    # Adicionar texto "ALTO EM"
                    s_title = String(45, box_height - 15, "ALTO EM")
                    s_title.fontName = "Helvetica-Bold"
                    s_title.fontSize = 11
                    lupa_draw.add(s_title)
                    
                    # Adicionar os nutrientes
                    for idx, item in enumerate(lupa_items):
                        y_pos = box_height - 27 - (idx * 11)
                        s_item = String(45, y_pos, f"• {item}")
                        s_item.fontName = "Helvetica-Bold"
                        s_item.fontSize = 8
                        lupa_draw.add(s_item)
                        
                    story.append(lupa_draw)
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
    
    current_username = st.session_state.get("username", "")
    all_recipes = load_saved_recipes()
    # Filtrar para exibir apenas receitas públicas/legadas ou do usuário logado
    saved_recipes = [r for r in all_recipes if r.get("username", "") == "" or r.get("username", "").lower() == current_username.lower()]
    
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
                - **Nome do Produto:** {recipe.get('nome_produto', 'Não Informado')}
                - **Rendimento da Receita (Peso Pronto):** {recipe['weight_final']:.1f} g/ml
                - **Peso Líquido na Embalagem:** {recipe.get('peso_embalagem', 0.0):.1f} g/ml
                - **Tamanho da Porção:** {recipe['portion_size']:.1f} g/ml
                """)
            with p_col2:
                st.markdown(f"""
                - **Medida Caseira:** {recipe['case_measure']}
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
                    st.session_state.nome_produto = recipe.get("nome_produto", "")
                    st.session_state.peso_embalagem = float(recipe.get("peso_embalagem", 0.0))
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

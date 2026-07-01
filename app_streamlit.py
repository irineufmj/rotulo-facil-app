import streamlit as st
import json
import os
import pandas as pd
import io
import math
import html
import threading
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from utils.auth import authenticate_user, register_user, admin_update_user, admin_delete_user, load_users
from utils.data_loader import load_unified_data, load_saved_recipes, save_recipe, delete_recipe
from utils.calculations import get_num_val, round_anvisa, VDR
from utils.ui import inject_custom_css, get_lupa_html, generate_anvisa_lupa_svg, get_lupa_image_path

db_lock = threading.RLock()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CUSTOM_CSV_PATH = os.path.join(BASE_DIR, "custom_ingredients.csv")


# Configurações de logging e concorrência
db_lock = threading.RLock()

# Definição absoluta de caminhos de arquivos de dados
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CUSTOM_CSV_PATH = os.path.join(BASE_DIR, "custom_ingredients.csv")
USERS_JSON_PATH = os.path.join(BASE_DIR, "usuarios.json")
RECIPES_JSON_PATH = os.path.join(BASE_DIR, "receitas_salvas.json")

# Configuração da página Streamlit
st.set_page_config(
    page_title="Rotuladora Nutricional ANVISA | TBCA & TACO",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilos CSS premium para a interface Streamlit
inject_custom_css()

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

foods_data = load_unified_data()

# Inicializar estados de sessão
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False
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

# --- FUNÇÕES AUXILIARES DE PROCESSAMENTO ---

# Obter valor numérico seguro do nutriente

# Regra de arredondamento ANVISA (IN 75/2020)
def save_recipe_dialog():
    st.write("Digite o nome para salvar a receita atual com seus ingredientes e configurações.")
    name = st.text_input("Nome da Receita:", placeholder="Ex: Bolo de Cenoura com Chocolate", key="new_recipe_name")
    if st.button("Confirmar e Salvar", type="primary", use_container_width=True):
        if name.strip():
            if save_recipe(name.strip(), db_lock):
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
        auth_mode = st.radio("Escolha uma opção:", ["Entrar", "Criar Nova Conta", "Esqueci minha senha"], horizontal=True, label_visibility="collapsed")
        
        st.markdown("---")
        
        if auth_mode == "Entrar":
            st.markdown("### 🔑 Entrar no Sistema")
            login_user = st.text_input("Usuário:", placeholder="Digite seu nome de usuário", key="login_username_field")
            login_pass = st.text_input("Senha:", type="password", placeholder="Digite sua senha", key="login_password_field")
            
            if st.button("Acessar Painel", type="primary", use_container_width=True):
                success, result, is_admin = authenticate_user(login_user, login_pass, db_lock)
                if success:
                    st.session_state.logged_in = True
                    st.session_state.username = result
                    st.session_state.is_admin = is_admin
                    st.toast(f"Bem-vindo de volta, {result}!")
                    st.rerun()
                else:
                    st.error(result)
                    
        elif auth_mode == "Esqueci minha senha":
            st.markdown("### 🔓 Recuperação de Senha")
            st.info("Para redefinir sua senha, informe o e-mail cadastrado na sua conta. Você receberá uma senha temporária.")
            rec_email = st.text_input("E-mail cadastrado:", key="rec_email")
            
            if st.button("Enviar E-mail de Recuperação", type="primary", use_container_width=True):
                if not rec_email:
                    st.error("Preencha o campo de e-mail para recuperar a senha.")
                else:
                    with st.spinner("Enviando e-mail..."):
                        from utils.auth import recover_password_email
                        success, msg = recover_password_email(rec_email, db_lock)
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
                    
        else: # Criar Nova Conta
            st.markdown("### 📝 Criar Nova Conta")
            new_user = st.text_input("Nome de Usuário:", placeholder="Escolha um nome de usuário", key="reg_username_field")
            new_email = st.text_input("E-mail:", placeholder="Ex: usuario@email.com", key="reg_email_field")
            new_cpf = st.text_input("CPF:", placeholder="Ex: 000.000.000-00", key="reg_cpf_field")
            new_pass = st.text_input("Senha:", type="password", placeholder="Mínimo de 4 caracteres", key="reg_password_field")
            new_pass_confirm = st.text_input("Confirme a Senha:", type="password", placeholder="Repita a senha anterior", key="reg_password_confirm_field")
            
            st.markdown("##### 🛡️ Termos de Uso e Política de Privacidade (LGPD)")
            with st.expander("Clique para ler os Termos de Uso e Política de Privacidade completos"):
                st.markdown("""
                **TERMO DE CONSENTIMENTO E PRIVACIDADE (LGPD)**
                
                De acordo com a Lei Geral de Proteção de Dados (Lei nº 13.709/2018), este termo informa como tratamos suas informações:
                
                1. **Quais dados coletamos:** Coletamos seu nome de usuário, e-mail e CPF para fins de identificação, controle de unicidade, conformidade legal e segurança, além do hash criptografado da sua senha. Coletamos também as receitas, ingredientes e parametrizações que você salvar.
                2. **Finalidade:** O tratamento desses dados tem como única e exclusiva finalidade permitir que você gerencie, edite, exclua e visualize suas próprias receitas de forma privada, evitando contas duplicadas ou fantasmas.
                3. **Armazenamento e Compartilhamento:** Seus dados são salvos localmente no arquivo de dados do aplicativo. Não compartilhamos, vendemos ou divulgamos suas receitas ou credenciais para terceiros em hipótese alguma.
                4. **Exclusão de Dados:** Você é proprietário dos seus dados. A exclusão de uma receita pode ser feita diretamente por você. Para exclusão total da conta e de todas as suas receitas, entre em contato com o administrador.
                5. **Segurança:** As senhas são protegidas por criptografia de mão única (SHA-256) combinadas com um salt aleatório para evitar acessos não autorizados.
                
                Ao assinalar a caixa abaixo, você declara que compreende e aceita livremente os termos deste tratamento de dados.
                """)
            
            lgpd_accept = st.checkbox("Li e concordo com os Termos de Uso e Política de Privacidade de acordo com a LGPD.", key="lgpd_checkbox")
            
            if st.button("Cadastrar e Acessar", type="primary", use_container_width=True):
                if not new_user.strip() or not new_email.strip() or not new_cpf.strip() or not new_pass or not new_pass_confirm:
                    st.error("Por favor, preencha todos os campos do cadastro.")
                elif new_pass != new_pass_confirm:
                    st.error("As senhas digitadas não coincidem.")
                elif not lgpd_accept:
                    st.error("Você precisa aceitar os termos de privacidade da LGPD para prosseguir.")
                else:
                    success, msg = register_user(new_user, new_email, new_cpf, new_pass, lgpd_accept, db_lock)
                    if success:
                        st.session_state.logged_in = True
                        st.session_state.username = new_user.strip()
                        st.session_state.is_admin = False
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
    if st.session_state.get("is_admin", False):
        st.markdown("🛡️ **Acesso Administrador**")
    if st.button("🚪 Sair da Conta", type="secondary", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state.is_admin = False
        st.session_state.recipe = []
        st.session_state.calculated = False
        st.session_state.nome_produto = ""
        st.session_state.peso_embalagem = 0.0
        st.toast("Você saiu da conta.")
        st.rerun()
    st.markdown("---")

# --- TABS PRINCIPAIS ---
tab_titles = [
    "📋 Calculadora & Rótulo ANVISA", 
    "📁 Minhas Receitas Salvas", 
    "➕ Cadastrar Novo Ingrediente",
    "👤 Meu Perfil"
]
is_admin = st.session_state.get("is_admin", False)
if is_admin:
    tab_titles.append("🔑 Painel Administrador")
    
tabs = st.tabs(tab_titles)
tab_app = tabs[0]
tab_receitas = tabs[1]
tab_cadastro = tabs[2]
tab_perfil = tabs[3]
if is_admin:
    tab_admin = tabs[4]

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

            from utils.data_loader import get_recipes_as_ingredients
            curr_user = st.session_state.get("username", "")
            sub_recipes = get_recipes_as_ingredients(db_lock, curr_user)
            dynamic_foods = foods_data + sub_recipes
            matched_foods = [f for f in dynamic_foods if q in f["d"].lower() or q in f["c"].lower()]
            
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
                "cost_kg": selected_recipe_food["n"].get("Custo (R$/kg)", 0.0),
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
            col_hdr, col_mul, col_div, col_clr = st.columns([2, 0.5, 0.5, 1])
            col_hdr.markdown("### 🛒 Ingredientes na Receita")
            if col_mul.button("✖️ 2x", type="secondary", use_container_width=True, help="Dobrar receita"):
                for ing in st.session_state.recipe:
                    ing["w"] *= 2.0
                st.session_state.weight_final *= 2.0
                st.session_state.calculated = False
                st.rerun()
            if col_div.button("➗ 0.5x", type="secondary", use_container_width=True, help="Cortar pela metade"):
                for ing in st.session_state.recipe:
                    ing["w"] /= 2.0
                st.session_state.weight_final /= 2.0
                st.session_state.calculated = False
                st.rerun()
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
                    col_ing_name, col_ing_weight, col_ing_cost, col_ing_del = st.columns([2.0, 1.2, 1.0, 0.3])
                    safe_d = html.escape(ing['d'])
                    safe_f = html.escape(ing['f'])
                    safe_c = html.escape(ing['c'])
                    col_ing_name.markdown(f"**{safe_d}**<br><small style='color: gray;'>{safe_f} | {safe_c}</small>", unsafe_allow_html=True)
                    
                    w_val = col_ing_weight.number_input(
                        "Peso (g)",
                        min_value=0.1,
                        value=float(ing['w']),
                        key=f"ing_w_{idx}_{ing['c']}",
                        step=5.0,
                        help="Peso utilizado na receita (em gramas)"
                    )
                    
                    cost_val = col_ing_cost.number_input(
                        "Custo R$/kg",
                        min_value=0.0,
                        value=float(ing.get('cost_kg', 0.0)),
                        key=f"ing_cost_{idx}_{ing['c']}",
                        step=1.0,
                        help="Custo do ingrediente por Quilo (R$/kg)"
                    )
                    
                    st.markdown("""
                        <style>
                        /* Alinha o ícone de remover com os campos de input */
                        div[data-testid="column"]:nth-of-type(4) {
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            margin-top: 28px;
                        }
                        </style>
                    """, unsafe_allow_html=True)
                    rem_val = col_ing_del.checkbox("🗑️", key=f"ing_rem_{idx}_{ing['c']}", help="Remover ingrediente")
                    
                    new_recipe_list.append((ing, w_val, cost_val, rem_val))
                
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
                    for ing, w, cost_val, rem in new_recipe_list:
                        if not rem:
                            ing_copy = ing.copy()
                            ing_copy["w"] = w
                            ing_copy["cost_kg"] = cost_val
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
        weight_final = max(st.session_state.weight_final, 1.0)
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
        total_recipe_cost = 0.0
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
            total_recipe_cost += ing.get("cost_kg", 0.0) * (ing["w"] / 1000.0)
            
            raw_totals["Energia (kcal)"] += get_num_val(ing["n"], "Energia (kcal)", ing["d"]) * factor
            
            carb = get_num_val(ing["n"], "Carboidrato total (g)", ing["d"])
            raw_totals["Carboidrato total (g)"] += carb * factor
            
            sug_add = get_num_val(ing["n"], "Açúcares adicionados (g)", ing["d"])
            raw_totals["Açúcares adicionados (g)"] += sug_add * factor
            
            sug_tot = get_num_val(ing["n"], "Açúcares totais (g)", ing["d"])
            if sug_tot == 0.0 and sug_add > 0.0:
                sug_tot = sug_add
            raw_totals["Açúcares totais (g)"] += sug_tot * factor
            
            raw_totals["Proteína (g)"] += get_num_val(ing["n"], "Proteína (g)", ing["d"]) * factor
            raw_totals["Lipídios (g)"] += get_num_val(ing["n"], "Lipídios (g)", ing["d"]) * factor
            raw_totals["Gorduras saturadas (g)"] += get_num_val(ing["n"], "Gorduras saturadas (g)", ing["d"]) * factor
            raw_totals["Gorduras trans (g)"] += get_num_val(ing["n"], "Gorduras trans (g)", ing["d"]) * factor
            raw_totals["Fibra alimentar (g)"] += get_num_val(ing["n"], "Fibra alimentar (g)", ing["d"]) * factor
            raw_totals["Sódio (mg)"] += get_num_val(ing["n"], "Sódio (mg)", ing["d"]) * factor
            
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
            cost_per_portion = (total_recipe_cost / weight_final) * portion_size
            st.info(f"**Custo Estimado da Receita:** R$ {total_recipe_cost:.2f} | **Custo por Porção:** R$ {cost_per_portion:.2f}")
            
            # Exibir nome do produto no painel de pré-visualização
            # Exibir nome do produto no painel de pré-visualização
            if st.session_state.nome_produto:
                safe_nome_produto = html.escape(st.session_state.nome_produto)
                st.markdown(f"##### Produto: **{safe_nome_produto}**")
            
            # --- Renderização Visual das Lupas (Estilo Oficial ANVISA PNG/SVG) ---
            # Sempre reserva o espaço da Lupa acima da tabela. Se nenhum nutriente exceder, exibe um espaço em branco.
            if alto_acucar or alto_gordura or alto_sodio:
                lupa_content_html = get_lupa_html(alto_acucar, alto_gordura, alto_sodio)
            else:
                lupa_content_html = '<div style="height: 180px;"></div>' # Espaço em branco para manter a altura estável
                
            lupa_container_html = f"""
            <div style="max-width: 420px; min-height: 180px; display: flex; align-items: center; justify-content: center; margin: 10px auto;">
                {lupa_content_html}
            </div>
            """
            st.markdown(lupa_container_html, unsafe_allow_html=True)
            
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
            safe_case_measure = html.escape(case_measure)
            table_html = f"""
            <div class="anvisa-table-container">
                <table class="anvisa-table">
                    <tr class="header-row">
                        <th colspan="4">INFORMAÇÃO NUTRICIONAL</th>
                    </tr>
                    <tr>
                        <td colspan="4" style="border-bottom: 2px solid #000;">
                            {n_porcoes_str} porções por embalagem<br>
                            Porção: {int(portion_size)} {col_unit} ({safe_case_measure})
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
            
            safe_ing_text = html.escape(ing_text)
            legal_html = f"""
            <div class="legal-box">
                <strong>INGREDIENTES:</strong> {safe_ing_text}.<br><br>
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
                
                # Adicionar Lupa de aviso se houver
                if alto_acucar or alto_gordura or alto_sodio:
                    img_path = get_lupa_image_path(alto_acucar, alto_gordura, alto_sodio)
                    if img_path:
                        try:
                            from reportlab.platypus import Image as RLImage
                            from PIL import Image as PILImage
                            with PILImage.open(img_path) as pil_img:
                                w_px, h_px = pil_img.size
                            aspect = h_px / w_px
                            pdf_width = 120 # em pontos
                            pdf_height = pdf_width * aspect
                            story.append(RLImage(img_path, width=pdf_width, height=pdf_height))
                            story.append(Spacer(1, 15))
                        except Exception as e:
                            logger.warning(f"Erro ao processar imagem da lupa para o PDF, usando fallback vetorizado: {e}", exc_info=True)
                            img_path = None
                    
                    if not img_path:
                        # Fallback: Lupa Vetorizada (Estilo Oficial ANVISA)
                        lupa_items = []
                        if alto_acucar: lupa_items.append("AÇÚCAR ADICIONADO")
                        if alto_gordura: lupa_items.append("GORDURA SATURADA")
                        if alto_sodio: lupa_items.append("SÓDIO")
                        
                        from reportlab.graphics.shapes import Drawing, Circle, Line, Rect, String
                        
                        num_items = len(lupa_items)
                        box_width = 120
                        box_height = 15 + 35 + (num_items * 40)
                        
                        lupa_draw = Drawing(box_width, box_height)
                        
                        # 1. Borda externa com cantos arredondados
                        lupa_draw.add(Rect(2, 2, box_width - 4, box_height - 4, rx=10, ry=10, strokeColor=colors.black, fillColor=colors.white, strokeWidth=2.5))
                        
                        # 2. Caixa "ALTO EM"
                        lupa_draw.add(Rect(10, box_height - 42, 100, 28, rx=14, ry=14, strokeColor=colors.black, fillColor=colors.white, strokeWidth=2))
                        
                        # Lente da lupa (círculo)
                        g_x = 24
                        g_y = box_height - 28
                        lupa_draw.add(Circle(g_x, g_y, 8, strokeColor=colors.black, fillColor=colors.white, strokeWidth=2))
                        # Cabo apontando para baixo-esquerda (conforme imagens oficiais da ANVISA)
                        lupa_draw.add(Line(g_x - 5, g_y - 5, g_x - 11, g_y - 11, strokeColor=colors.black, strokeWidth=3, strokeLineCap=1))
                        
                        # Texto "ALTO EM"
                        s_title = String(67, box_height - 32, "ALTO EM")
                        s_title.fontName = "Helvetica-Bold"
                        s_title.fontSize = 10
                        s_title.textAnchor = "middle"
                        lupa_draw.add(s_title)
                        
                        # 3. Blocos de nutrientes empilhados
                        y_start = box_height - 52
                        for idx, item in enumerate(lupa_items):
                            y_pos = y_start - 35 - (idx * 37)
                            # Retângulo preto
                            lupa_draw.add(Rect(10, y_pos, 100, 32, rx=8, ry=8, fillColor=colors.black, strokeColor=colors.black))
                            
                            # Texto do nutriente
                            if item == "SÓDIO":
                                s_item = String(60, y_pos + 12, "SÓDIO")
                                s_item.fontName = "Helvetica-Bold"
                                s_item.fontSize = 10
                                s_item.fillColor = colors.white
                                s_item.textAnchor = "middle"
                                lupa_draw.add(s_item)
                            else:
                                # Duas linhas para texto longo
                                words = item.split(" ")
                                s_line1 = String(60, y_pos + 18, words[0])
                                s_line1.fontName = "Helvetica-Bold"
                                s_line1.fontSize = 8
                                s_line1.fillColor = colors.white
                                s_line1.textAnchor = "middle"
                                lupa_draw.add(s_line1)
                                
                                s_line2 = String(60, y_pos + 7, words[1])
                                s_line2.fontName = "Helvetica-Bold"
                                s_line2.fontSize = 8
                                s_line2.fillColor = colors.white
                                s_line2.textAnchor = "middle"
                                lupa_draw.add(s_line2)
                                
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
    all_recipes = load_saved_recipes(db_lock)
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
            col_load, col_clone, col_del = st.columns(3)
            
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
                    

            with col_clone:
                if st.button("📄 Carregar como Cópia", type="secondary", use_container_width=True, help="Carrega a receita pronta para ser salva como uma nova versão."):
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
                    st.session_state.nome_produto = recipe.get("nome_produto", "") + " (Cópia)"
                    st.session_state.peso_embalagem = float(recipe.get("peso_embalagem", 0.0))
                    st.session_state.calculated = True
                    st.toast(f"Cópia da receita pronta para edição!")
                    st.rerun()
            with col_del:
                if st.button("🗑️ Excluir Receita Permanentemente", type="secondary", use_container_width=True):
                    if delete_recipe(selected_name, db_lock):
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
        col_cad1, col_cad2, col_cad3 = st.columns([2, 1, 1])
        name_ing = col_cad1.text_input("Nome do Alimento / Ingrediente:", placeholder="Ex: Whey Protein Isolado Morango")
        portion_ref = col_cad2.number_input("Porção de Referência do Rótulo (g):", min_value=1.0, value=100.0, step=5.0, help="O peso da porção informada no rótulo (ex: 30g).")
        cost_ref = col_cad3.number_input("Custo R$/kg:", min_value=0.0, value=0.0, step=1.0, help="Custo do ingrediente por Quilo")
        
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
                    "Sódio (mg)": sodium_100g,
                    "Custo (R$/kg)": cost_ref
                }])
                
                # Salvar no CSV
                custom_df = pd.concat([custom_df, new_row], ignore_index=True)
                custom_df.to_csv(CUSTOM_CSV_PATH, index=False, encoding="utf-8-sig")
                
                st.success(f"Ingrediente **{name_ing.strip()}** cadastrado com código `{new_code}`!")
                # Forçar a recarga dos dados na sessão
                st.cache_data.clear()
                st.rerun()

# ==============================================================================
# TAB 4: PAINEL ADMINISTRADOR
# ==============================================================================

# ==============================================================================
# TAB 4: MEU PERFIL
# ==============================================================================
with tab_perfil:
    st.markdown('### 👤 Meu Perfil')
    st.markdown('Edite suas informações cadastrais.')
    
    current_username = st.session_state.username
    all_users = load_users(db_lock)
    user_data = next((u for u in all_users if u['username'] == current_username), None)
    
    if user_data:
        with st.form('form_meu_perfil'):
            edit_email = st.text_input('E-mail:', value=user_data.get('email', ''))
            
            # Formatar CPF atual
            c = user_data.get('cpf', '')
            c_digits = ''.join(filter(str.isdigit, c))
            if len(c_digits) == 11:
                cpf_display = f'{c_digits[:3]}.{c_digits[3:6]}.{c_digits[6:9]}-{c_digits[9:]}'
            else:
                cpf_display = c
                
            edit_cpf = st.text_input('CPF:', value=cpf_display)
            edit_pass = st.text_input('Nova Senha (deixe em branco para manter a atual):', type='password')
            edit_pass_confirm = st.text_input('Confirme a Nova Senha:', type='password')
            
            submit_perfil = st.form_submit_button('Salvar Alterações', type='primary')
            if submit_perfil:
                if edit_pass and edit_pass != edit_pass_confirm:
                    st.error('As senhas não coincidem.')
                else:
                    success, msg = admin_update_user(
                        current_username, 
                        current_username, 
                        edit_email, 
                        edit_cpf, 
                        db_lock, 
                        edit_pass if edit_pass.strip() else None, 
                        user_data.get('is_admin', False)
                    )
                    if success:
                        st.success('Perfil atualizado com sucesso!')
                    else:
                        st.error(msg)
    else:
        st.error('Não foi possível carregar os dados do seu perfil.')

if is_admin:
    with tab_admin:
        st.markdown("### 🔑 Painel do Administrador")
        st.markdown("Gerencie contas de usuários, edite informações cadastrais (incluindo CPF e e-mail) ou exclua usuários antigos (exclusão em cascata de suas receitas).")
        
        users = load_users(db_lock)
        
        # Formatar CPF para exibição
        def format_cpf(c):
            c_digits = ''.join(filter(str.isdigit, c))
            if len(c_digits) == 11:
                return f"{c_digits[:3]}.{c_digits[3:6]}.{c_digits[6:9]}-{c_digits[9:]}"
            return c
            
        users_display = []
        for u in users:
            users_display.append({
                "Usuário": u["username"],
                "E-mail": u.get("email", "N/A"),
                "CPF": format_cpf(u.get("cpf", "N/A")),
                "Administrador": "Sim" if u.get("is_admin", False) else "Não",
                "Aceite LGPD": u.get("lgpd_accepted_at", "N/A")
            })
            
        st.markdown("#### 👥 Usuários Cadastrados")
        st.dataframe(pd.DataFrame(users_display), use_container_width=True)
        
        admin_action = st.radio("Selecione uma ação administrativa:", ["Editar Usuário", "Criar Usuário", "Excluir Usuário"], horizontal=True)
        
        if admin_action == "Editar Usuário":
            st.markdown("##### ✏️ Editar Cadastro de Usuário")
            usernames = [u["username"] for u in users]
            selected_username = st.selectbox("Selecione o usuário para editar:", usernames)
            
            if selected_username:
                # Carregar dados atuais do usuário selecionado
                user_data = next((u for u in users if u["username"] == selected_username), None)
                if user_data:
                    with st.form("form_edit_user"):
                        edit_name = st.text_input("Nome de Usuário:", value=user_data["username"])
                        edit_email = st.text_input("E-mail:", value=user_data.get("email", ""))
                        edit_cpf = st.text_input("CPF:", value=format_cpf(user_data.get("cpf", "")))
                        edit_pass = st.text_input("Nova Senha (deixe em branco para manter a atual):", type="password")
                        edit_is_admin = st.checkbox("Privilégios de Administrador", value=user_data.get("is_admin", False))
                        
                        submit_edit = st.form_submit_button("Confirmar Alterações", type="primary")
                        if submit_edit:
                            success, msg = admin_update_user(
                                selected_username, 
                                edit_name, 
                                edit_email, 
                                edit_cpf, 
                                edit_pass if edit_pass.strip() else None, 
                                edit_is_admin
                            )
                            if success:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
                                
        elif admin_action == "Criar Usuário":
            st.markdown("##### 📝 Cadastrar Novo Usuário (Comum ou Admin)")
            with st.form("form_create_user_admin"):
                create_name = st.text_input("Nome de Usuário:", placeholder="Ex: joao_silva")
                create_email = st.text_input("E-mail:", placeholder="Ex: joao@provedor.com")
                create_cpf = st.text_input("CPF:", placeholder="Ex: 123.456.789-00")
                create_pass = st.text_input("Senha:", type="password", placeholder="Mínimo 4 caracteres")
                create_is_admin = st.checkbox("Privilégios de Administrador")
                
                submit_create = st.form_submit_button("Cadastrar Usuário", type="primary")
                if submit_create:
                    # Chamar register_user que já faz todas as validações (passando True para LGPD pois é feito pelo admin)
                    success, msg = register_user(create_name, create_email, create_cpf, create_pass, lgpd_accepted=True, db_lock=db_lock)
                    if success:
                        # Se admin flag foi marcada, atualizamos o usuário criado
                        if create_is_admin:
                            admin_update_user(create_name, create_name, create_email, create_cpf, db_lock, None, is_admin_val=True)
                        st.success(f"Usuário '{create_name}' cadastrado com sucesso!")
                        st.rerun()
                    else:
                        st.error(msg)
                        
        elif admin_action == "Excluir Usuário":
            st.markdown("##### 🗑️ Excluir Usuário e Receitas Associadas (Cascata)")
            current_user = st.session_state.get("username", "")
            # Não permitir deletar a si mesmo na lista
            other_usernames = [u["username"] for u in users if u["username"].lower() != current_user.lower()]
            
            if not other_usernames:
                st.info("Não há outros usuários disponíveis para exclusão.")
            else:
                selected_del_username = st.selectbox("Selecione o usuário para exclusão:", other_usernames)
                
                st.warning("⚠️ **ATENÇÃO:** A exclusão removerá permanentemente a conta do usuário e todas as receitas salvas por ele em cascata.")
                confirm_del_text = st.text_input(f"Digite o nome do usuário '{selected_del_username}' para confirmar:")
                
                if st.button("Excluir Usuário Definitivamente", type="secondary", use_container_width=True):
                    if confirm_del_text.strip() == selected_del_username:
                        success, msg = admin_delete_user(selected_del_username, db_lock)
                        if success:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
                    else:
                        st.error("Confirmação inválida. Digite o nome do usuário exatamente para confirmar a exclusão.")

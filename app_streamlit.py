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

from utils.auth import authenticate_user, register_user, admin_update_user, admin_delete_user, load_users, recover_password_email, consume_user_credit
from utils.data_loader import load_unified_data, load_saved_recipes, save_recipe, delete_recipe, get_user_plan_status, can_user_save_recipe
from utils.calculations import (
    get_num_val, round_anvisa, VDR,
    calculate_financial_breakdown, calculate_cmv, calculate_ingredient_cost,
    convert_package_to_cost_kg, calculate_hourly_labor_rate, calculate_overhead_rate_pct,
    calculate_monthly_sales_goal, calculate_bulk_discount_simulation
)
from utils.ui import inject_custom_css, get_lupa_html, generate_anvisa_lupa_svg, get_lupa_image_path
from utils.db import save_ticket_sql, load_tickets_sql, update_ticket_status_sql
from utils.mapear_ingredientes import gerar_lista_ingredientes_rotulo

# Configurações de logging e concorrência
import logging
logger = logging.getLogger(__name__)
db_lock = threading.RLock()

# Definição absoluta de caminhos de arquivos de dados
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CUSTOM_CSV_PATH = os.path.join(BASE_DIR, "custom_ingredients.csv")
USERS_JSON_PATH = os.path.join(BASE_DIR, "usuarios.json")
RECIPES_JSON_PATH = os.path.join(BASE_DIR, "receitas_salvas.json")
def get_secrets_key(key_name, default=""):
    try:
        val = st.secrets.get(key_name)
        if val:
            return val
        norm_target = key_name.replace("_", "").lower()
        def search_dict(d, target):
            for k, v in d.items():
                if k.replace("_", "").lower() == target:
                    return v
                if isinstance(v, dict):
                    res = search_dict(v, target)
                    if res:
                        return res
            return None
        val = search_dict(st.secrets, norm_target)
        if val:
            return val
    except Exception:
        pass
    return default

# Configuração da página Streamlit
st.set_page_config(
    page_title="Rotulei App | Precificação, Ficha Técnica & Rotulagem ANVISA",
    page_icon="💰",
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
        "Sódio (mg)", "Custo (R$/kg)"
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

# Estados de Sessão Financeiros & Precificação
if "custo_embalagem" not in st.session_state:
    st.session_state.custo_embalagem = 0.0
if "tempo_preparo_min" not in st.session_state:
    st.session_state.tempo_preparo_min = 0.0
if "custo_hora_mao_obra" not in st.session_state:
    st.session_state.custo_hora_mao_obra = 0.0
if "custo_operacional_pct" not in st.session_state:
    st.session_state.custo_operacional_pct = 0.0
if "taxas_venda_pct" not in st.session_state:
    st.session_state.taxas_venda_pct = 0.0
if "margem_desejada_pct" not in st.session_state:
    st.session_state.margem_desejada_pct = 30.0
if "preco_venda_praticado" not in st.session_state:
    st.session_state.preco_venda_praticado = 0.0
if "yield_mode" not in st.session_state:
    st.session_state.yield_mode = "Por Unidades Prontas (ex: 25 brigadeiros)"
if "yield_units" not in st.session_state:
    st.session_state.yield_units = 25

# --- FUNÇÕES AUXILIARES DE PROCESSAMENTO & TEMPLATES ---

def _find_food_item(foods_list, code, fallback_desc, fallback_nut):
    for f in foods_list:
        if f.get("c") == code:
            return f
    return {"c": code, "d": fallback_desc, "f": "TACO", "n": fallback_nut}

def get_model_recipes(foods_list):
    """
    Retorna receitas modelo prontas de confeitaria/produção artesanal para onboarding em 1 clique.
    """
    f_lc = _find_food_item(foods_list, "TACO-453", "Leite, condensado", {"Energia (kcal)": 313, "Carboidrato total (g)": 57.0, "Açúcares adicionados (g)": 45.0, "Proteína (g)": 7.7, "Lipídios (g)": 6.7, "Gorduras saturadas (g)": 4.2, "Sódio (mg)": 94})
    f_cl = _find_food_item(foods_list, "TACO-447", "Creme de Leite", {"Energia (kcal)": 221, "Carboidrato total (g)": 4.5, "Proteína (g)": 1.5, "Lipídios (g)": 22.5, "Gorduras saturadas (g)": 13.0, "Sódio (mg)": 59})
    f_ch = _find_food_item(foods_list, "C0011K", "Chocolate em pó 50%", {"Energia (kcal)": 378, "Carboidrato total (g)": 74.0, "Açúcares adicionados (g)": 50.0, "Proteína (g)": 8.5, "Lipídios (g)": 6.0, "Gorduras saturadas (g)": 3.6, "Fibra alimentar (g)": 7.0, "Sódio (mg)": 35})
    f_mt = _find_food_item(foods_list, "TACO-262", "Manteiga, sem sal", {"Energia (kcal)": 726, "Lipídios (g)": 82.4, "Gorduras saturadas (g)": 51.5, "Sódio (mg)": 4})
    f_lp = _find_food_item(foods_list, "TACO-459", "Leite, de vaca, integral, pó", {"Energia (kcal)": 497, "Carboidrato total (g)": 39.2, "Proteína (g)": 25.4, "Lipídios (g)": 26.9, "Gorduras saturadas (g)": 16.6, "Sódio (mg)": 323})
    f_mo = _find_food_item(foods_list, "TACO-239", "Morango, cru", {"Energia (kcal)": 30, "Carboidrato total (g)": 6.8, "Proteína (g)": 0.9, "Lipídios (g)": 0.3, "Fibra alimentar (g)": 1.7, "Sódio (mg)": 11})
    f_ft = _find_food_item(foods_list, "TACO-35", "Farinha, de trigo", {"Energia (kcal)": 360, "Carboidrato total (g)": 75.1, "Proteína (g)": 9.8, "Lipídios (g)": 1.4, "Fibra alimentar (g)": 2.3, "Sódio (mg)": 1})
    f_ac = _find_food_item(foods_list, "TACO-494", "Açúcar, refinado", {"Energia (kcal)": 387, "Carboidrato total (g)": 99.5, "Açúcares adicionados (g)": 99.5})
    f_ov = _find_food_item(foods_list, "TACO-489", "Ovo, de galinha, inteiro, cru", {"Energia (kcal)": 143, "Carboidrato total (g)": 1.6, "Proteína (g)": 13.0, "Lipídios (g)": 8.9, "Gorduras saturadas (g)": 2.6, "Sódio (mg)": 168})
    f_cb = _find_food_item(foods_list, "C0046K", "Chocolate, ao leite", {"Energia (kcal)": 540, "Carboidrato total (g)": 59.0, "Açúcares adicionados (g)": 48.0, "Proteína (g)": 7.0, "Lipídios (g)": 30.0, "Gorduras saturadas (g)": 18.0, "Sódio (mg)": 79})
    f_me = _find_food_item(foods_list, "TACO-507", "Mel, de abelha", {"Energia (kcal)": 309, "Carboidrato total (g)": 84.0, "Açúcares adicionados (g)": 84.0, "Sódio (mg)": 6})

    return {
        "brigadeiro": {
            "label": "🍫 Brigadeiro Gourmet (25 un)",
            "nome_produto": "Brigadeiro Gourmet Tradicional (Caixa ou Unidade)",
            "yield_units": 25,
            "weight_final": 500.0,
            "peso_embalagem": 20.0,
            "portion_size": 20.0,
            "case_measure": "1 unidade",
            "custo_embalagem": 0.25,
            "tempo_preparo_min": 35.0,
            "custo_hora_mao_obra": 20.0,
            "custo_operacional_pct": 10.0,
            "taxas_venda_pct": 4.5,
            "margem_desejada_pct": 35.0,
            "preco_venda_praticado": 3.50,
            "gluten_opt": "NÃO CONTÉM GLÚTEN",
            "lactose_opt": "CONTÉM LACTOSE",
            "allergens_direct": ["Leite"],
            "allergens_deriv": ["Leite", "Soja"],
            "ingredients": [
                {"c": f_lc["c"], "d": f_lc["d"], "f": f_lc["f"], "w": 395.0, "cost_kg": 20.00, "yield_factor": 1.0, "n": f_lc["n"]},
                {"c": f_cl["c"], "d": f_cl["d"], "f": f_cl["f"], "w": 200.0, "cost_kg": 19.50, "yield_factor": 1.0, "n": f_cl["n"]},
                {"c": f_ch["c"], "d": f_ch["d"], "f": f_ch["f"], "w": 50.0, "cost_kg": 45.00, "yield_factor": 1.0, "n": f_ch["n"]},
                {"c": f_mt["c"], "d": f_mt["d"], "f": f_mt["f"], "w": 20.0, "cost_kg": 48.00, "yield_factor": 1.0, "n": f_mt["n"]},
            ]
        },
        "bolo_pote": {
            "label": "🍰 Bolo no Pote Ninho c/ Morango (10 potes)",
            "nome_produto": "Bolo no Pote de Ninho com Morango (220g)",
            "yield_units": 10,
            "weight_final": 2200.0,
            "peso_embalagem": 220.0,
            "portion_size": 60.0,
            "case_measure": "3 colheres de sopa",
            "custo_embalagem": 1.20,
            "tempo_preparo_min": 60.0,
            "custo_hora_mao_obra": 20.0,
            "custo_operacional_pct": 10.0,
            "taxas_venda_pct": 12.0,
            "margem_desejada_pct": 35.0,
            "preco_venda_praticado": 14.00,
            "gluten_opt": "CONTÉM GLÚTEN",
            "lactose_opt": "CONTÉM LACTOSE",
            "allergens_direct": ["Trigo", "Ovos", "Leite"],
            "allergens_deriv": ["Trigo", "Leite", "Soja"],
            "ingredients": [
                {"c": f_lc["c"], "d": f_lc["d"], "f": f_lc["f"], "w": 790.0, "cost_kg": 20.00, "yield_factor": 1.0, "n": f_lc["n"]},
                {"c": f_cl["c"], "d": f_cl["d"], "f": f_cl["f"], "w": 400.0, "cost_kg": 19.50, "yield_factor": 1.0, "n": f_cl["n"]},
                {"c": f_mo["c"], "d": f_mo["d"], "f": f_mo["f"], "w": 300.0, "cost_kg": 28.00, "yield_factor": 1.10, "n": f_mo["n"]},
                {"c": f_ft["c"], "d": f_ft["d"], "f": f_ft["f"], "w": 250.0, "cost_kg": 6.50, "yield_factor": 1.0, "n": f_ft["n"]},
                {"c": f_ac["c"], "d": f_ac["d"], "f": f_ac["f"], "w": 180.0, "cost_kg": 5.50, "yield_factor": 1.0, "n": f_ac["n"]},
                {"c": f_lp["c"], "d": f_lp["d"], "f": f_lp["f"], "w": 150.0, "cost_kg": 42.00, "yield_factor": 1.0, "n": f_lp["n"]},
                {"c": f_ov["c"], "d": f_ov["d"], "f": f_ov["f"], "w": 150.0, "cost_kg": 18.00, "yield_factor": 1.0, "n": f_ov["n"]},
            ]
        },
        "pao_mel": {
            "label": "🍯 Pão de Mel Recheado (15 un)",
            "nome_produto": "Pão de Mel Artesanal com Doce de Leite (65g)",
            "yield_units": 15,
            "weight_final": 975.0,
            "peso_embalagem": 65.0,
            "portion_size": 65.0,
            "case_measure": "1 unidade",
            "custo_embalagem": 0.60,
            "tempo_preparo_min": 50.0,
            "custo_hora_mao_obra": 20.0,
            "custo_operacional_pct": 10.0,
            "taxas_venda_pct": 4.5,
            "margem_desejada_pct": 35.0,
            "preco_venda_praticado": 8.00,
            "gluten_opt": "CONTÉM GLÚTEN",
            "lactose_opt": "CONTÉM LACTOSE",
            "allergens_direct": ["Trigo", "Leite"],
            "allergens_deriv": ["Trigo", "Leite", "Soja"],
            "ingredients": [
                {"c": f_lc["c"], "d": f_lc["d"], "f": f_lc["f"], "w": 395.0, "cost_kg": 20.00, "yield_factor": 1.0, "n": f_lc["n"]},
                {"c": f_cb["c"], "d": f_cb["d"], "f": f_cb["f"], "w": 300.0, "cost_kg": 42.00, "yield_factor": 1.0, "n": f_cb["n"]},
                {"c": f_ft["c"], "d": f_ft["d"], "f": f_ft["f"], "w": 200.0, "cost_kg": 6.50, "yield_factor": 1.0, "n": f_ft["n"]},
                {"c": f_me["c"], "d": f_me["d"], "f": f_me["f"], "w": 100.0, "cost_kg": 38.00, "yield_factor": 1.0, "n": f_me["n"]},
                {"c": f_ac["c"], "d": f_ac["d"], "f": f_ac["f"], "w": 100.0, "cost_kg": 5.50, "yield_factor": 1.0, "n": f_ac["n"]},
                {"c": f_mt["c"], "d": f_mt["d"], "f": f_mt["f"], "w": 50.0, "cost_kg": 48.00, "yield_factor": 1.0, "n": f_mt["n"]},
            ]
        },
        "geleia": {
            "label": "🍓 Geleia de Morango (5 potes)",
            "nome_produto": "Geleia Artesanal de Morango (Pote 200g)",
            "yield_units": 5,
            "weight_final": 1000.0,
            "peso_embalagem": 200.0,
            "portion_size": 20.0,
            "case_measure": "1 colher de sopa",
            "custo_embalagem": 2.80,
            "tempo_preparo_min": 45.0,
            "custo_hora_mao_obra": 20.0,
            "custo_operacional_pct": 10.0,
            "taxas_venda_pct": 4.5,
            "margem_desejada_pct": 35.0,
            "preco_venda_praticado": 24.00,
            "gluten_opt": "NÃO CONTÉM GLÚTEN",
            "lactose_opt": "NÃO CONTÉM LACTOSE",
            "allergens_direct": [],
            "allergens_deriv": [],
            "ingredients": [
                {"c": f_mo["c"], "d": f_mo["d"], "f": f_mo["f"], "w": 1000.0, "cost_kg": 25.00, "yield_factor": 1.10, "n": f_mo["n"]},
                {"c": f_ac["c"], "d": f_ac["d"], "f": f_ac["f"], "w": 450.0, "cost_kg": 5.50, "yield_factor": 1.0, "n": f_ac["n"]},
            ]
        }
    }

def apply_model_recipe(tpl: dict):
    """Carrega uma receita modelo completa no estado da sessão."""
    st.session_state.recipe = [ing.copy() for ing in tpl["ingredients"]]
    st.session_state.nome_produto = tpl["nome_produto"]
    st.session_state.yield_units = int(tpl["yield_units"])
    st.session_state.yield_mode = "Por Unidades Prontas (ex: 25 brigadeiros)"
    st.session_state.weight_final = float(tpl["weight_final"])
    st.session_state.peso_embalagem = float(tpl["peso_embalagem"])
    st.session_state.portion_size = float(tpl["portion_size"])
    st.session_state.case_measure = tpl["case_measure"]
    st.session_state.custo_embalagem = float(tpl["custo_embalagem"])
    st.session_state.tempo_preparo_min = float(tpl["tempo_preparo_min"])
    st.session_state.custo_hora_mao_obra = float(tpl["custo_hora_mao_obra"])
    st.session_state.custo_operacional_pct = float(tpl["custo_operacional_pct"])
    st.session_state.taxas_venda_pct = float(tpl["taxas_venda_pct"])
    st.session_state.margem_desejada_pct = float(tpl["margem_desejada_pct"])
    st.session_state.preco_venda_praticado = float(tpl["preco_venda_praticado"])
    st.session_state.gluten_opt = tpl["gluten_opt"]
    st.session_state.lactose_opt = tpl["lactose_opt"]
    st.session_state.allergens_direct = list(tpl["allergens_direct"])
    st.session_state.allergens_deriv = list(tpl["allergens_deriv"])
    st.session_state.allergens_may_contain = []
    st.session_state.calculated = True

def build_anvisa_pdf_bytes(
    prod_name, weight_final, peso_embalagem, col_unit, n_porcoes_str,
    portion_size, safe_case_measure, col_100_label, col_portion_label,
    display_100g, display_portion, vd_percents,
    alto_acucar, alto_gordura, alto_sodio,
    ing_text_pdf, gluten_opt, lactose_opt, alergenicos_text
) -> bytes:
    """Função única e centralizada para geração do PDF oficial da Tabela Nutricional ANVISA."""
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    story = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=18, spaceAfter=15)
    section_style = ParagraphStyle('Section', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=12, spaceAfter=8, spaceBefore=12)
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=11)
    legal_style = ParagraphStyle('Legal', parent=styles['Normal'], fontName='Courier-Bold', fontSize=10, leading=13)

    story.append(Paragraph("<b>RELATÓRIO DE ROTULAGEM NUTRICIONAL OFICIAL</b>", title_style))
    p_title = prod_name if prod_name else "Não Informado"
    story.append(Paragraph(f"<b>Nome Comercial do Produto:</b> {html.escape(p_title)}", ParagraphStyle('PName', parent=body_style, fontSize=10, leading=12)))
    ref_emb = f"{peso_embalagem:.1f} {col_unit}" if peso_embalagem > 0.0 else "Não Informado"
    story.append(Paragraph(f"<b>Rendimento da Receita:</b> {weight_final:.1f} {col_unit} | <b>Peso Líquido na Embalagem:</b> {ref_emb}", ParagraphStyle('PDetails', parent=body_style, fontSize=9, leading=11)))
    story.append(Paragraph("Gerado em conformidade com RDC 429/2020 e IN 75/2020 (Fontes: TBCA USP / TACO UNICAMP)", ParagraphStyle('PSub', parent=body_style, fontName='Helvetica-Oblique', fontSize=8, leading=10, textColor=colors.gray)))
    story.append(Spacer(1, 10))

    table_data = [
        [Paragraph("<b>INFORMAÇÃO NUTRICIONAL</b>", ParagraphStyle('H', parent=body_style, fontName='Helvetica-Bold', fontSize=11)), "", "", ""],
        [Paragraph(f"{n_porcoes_str} porções por embalagem<br/>Porção: {int(portion_size)} {col_unit} ({safe_case_measure})", body_style), "", "", ""],
        [Paragraph("<b>Nutrientes</b>", body_style), Paragraph(f"<b>{col_100_label}</b>", body_style), Paragraph(f"<b>{col_portion_label}</b>", body_style), Paragraph("<b>%VD*</b>", body_style)],
        [Paragraph("Valor energético (kcal)", body_style), display_100g['Energia (kcal)'], display_portion['Energia (kcal)'], str(int(vd_percents['Energia (kcal)']))],
        [Paragraph("Carboidratos (g)", body_style), display_100g['Carboidrato total (g)'], display_portion['Carboidrato total (g)'], str(int(vd_percents['Carboidrato total (g)']))],
        [Paragraph("&nbsp;&nbsp;Açúcares totais (g)", body_style), display_100g['Açúcares totais (g)'], display_portion['Açúcares totais (g)'], "-"],
        [Paragraph("&nbsp;&nbsp;Açúcares adicionados (g)", body_style), display_100g['Açúcares adicionados (g)'], display_portion['Açúcares adicionados (g)'], str(int(vd_percents['Açúcares adicionados (g)']))],
        [Paragraph("Proteínas (g)", body_style), display_100g['Proteína (g)'], display_portion['Proteína (g)'], str(int(vd_percents['Proteína (g)']))],
        [Paragraph("Gorduras totais (g)", body_style), display_100g['Lipídios (g)'], display_portion['Lipídios (g)'], str(int(vd_percents['Lipídios (g)']))],
        [Paragraph("&nbsp;&nbsp;Gorduras saturadas (g)", body_style), display_100g['Gorduras saturadas (g)'], display_portion['Gorduras saturadas (g)'], str(int(vd_percents['Gorduras saturadas (g)']))],
        [Paragraph("&nbsp;&nbsp;Gorduras trans (g)", body_style), display_100g['Gorduras trans (g)'], display_portion['Gorduras trans (g)'], "-"],
        [Paragraph("Fibra alimentar (g)", body_style), display_100g['Fibra alimentar (g)'], display_portion['Fibra alimentar (g)'], str(int(vd_percents['Fibra alimentar (g)']))],
        [Paragraph("Sódio (mg)", body_style), display_100g['Sódio (mg)'], display_portion['Sódio (mg)'], str(int(vd_percents['Sódio (mg)']))],
        [Paragraph("<font size=7>* Percentual de valores diários fornecidos pela porção.</font>", body_style), "", "", ""]
    ]

    t = Table(table_data, colWidths=[180, 70, 80, 50])
    t.setStyle(TableStyle([
        ('SPAN', (0, 0), (3, 0)),
        ('SPAN', (0, 1), (3, 1)),
        ('SPAN', (0, 13), (3, 13)),
        ('BOX', (0, 0), (-1, -1), 1.5, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor("#EEEEEE")),
        ('ALIGN', (1, 2), (-1, -2), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(t)
    story.append(Spacer(1, 15))

    if alto_acucar or alto_gordura or alto_sodio:
        img_path = get_lupa_image_path(alto_acucar, alto_gordura, alto_sodio)
        if img_path:
            try:
                from reportlab.platypus import Image as RLImage
                from PIL import Image as PILImage
                with PILImage.open(img_path) as pil_img:
                    w_px, h_px = pil_img.size
                aspect = h_px / w_px
                pdf_width = 120
                pdf_height = pdf_width * aspect
                story.append(RLImage(img_path, width=pdf_width, height=pdf_height))
                story.append(Spacer(1, 15))
            except Exception:
                img_path = None

    story.append(Paragraph("<b>DECLARAÇÃO DE INGREDIENTES E AVISOS LEGAIS</b>", section_style))
    clean_ing = ing_text_pdf.strip()
    if not clean_ing.endswith("."):
        clean_ing += "."
    story.append(Paragraph(f"<b>INGREDIENTES:</b> {html.escape(clean_ing)}", legal_style))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"<b>{html.escape(gluten_opt)}</b>", legal_style))
    story.append(Paragraph(f"<b>{html.escape(lactose_opt)}</b>", legal_style))
    if alergenicos_text:
        story.append(Paragraph(f"<b>{html.escape(alergenicos_text)}</b>", legal_style))

    doc.build(story)
    pdf_buffer.seek(0)
    return pdf_buffer.getvalue()


def build_ficha_tecnica_pdf_bytes(
    prod_name: str,
    recipe_ingredients: list,
    fb: dict,
    num_units: float,
    unit_weight_g: float,
    prep_time_min: float,
    hourly_rate: float,
    overhead_pct: float,
    sales_fees_pct: float
) -> bytes:
    """
    Gera o PDF da Ficha Técnica de Produção & Custos para a confeiteira/produtor
    imprimir para a cozinha ou salvar no celular/WhatsApp (100% gratuito).
    """
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, leftMargin=32, rightMargin=32, topMargin=32, bottomMargin=32)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('FTTitle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=16, textColor=colors.HexColor("#0B3B4C"), spaceAfter=6)
    sub_style = ParagraphStyle('FTSub', parent=styles['Normal'], fontName='Helvetica', fontSize=9.5, textColor=colors.HexColor("#374151"), leading=13, spaceAfter=10)
    sec_style = ParagraphStyle('FTSec', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=11.5, textColor=colors.HexColor("#059669"), spaceBefore=10, spaceAfter=6)
    cell_style = ParagraphStyle('FTCell', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=11)
    cell_bold = ParagraphStyle('FTCellB', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8.5, leading=11)

    p_title = (prod_name or "Receita sem Nome").strip()
    data_hoje = pd.Timestamp.now().strftime("%d/%m/%Y %H:%M")

    story.append(Paragraph(f"<b>FICHA TÉCNICA DE PRODUÇÃO & PRECIFICAÇÃO</b>", title_style))
    story.append(Paragraph(
        f"<b>Produto:</b> {html.escape(p_title)} &nbsp;|&nbsp; "
        f"<b>Rendimento:</b> {num_units:.0f} un. (~{unit_weight_g:.0f}g/un) &nbsp;|&nbsp; "
        f"<b>Tempo de Preparo:</b> {prep_time_min:.0f} min &nbsp;|&nbsp; "
        f"<b>Data:</b> {data_hoje}",
        sub_style
    ))

    # 1. Tabela de Ingredientes (Checklist de Cozinha + Custos)
    story.append(Paragraph("1. INGREDIENTES E PESOS DE PRODUÇÃO (CHECKLIST DE COZINHA)", sec_style))
    ing_rows = [[
        Paragraph("<b>OK</b>", cell_bold),
        Paragraph("<b>Ingrediente</b>", cell_bold),
        Paragraph("<b>Qtd (g/ml)</b>", cell_bold),
        Paragraph("<b>FC</b>", cell_bold),
        Paragraph("<b>R$/kg</b>", cell_bold),
        Paragraph("<b>Custo (R$)</b>", cell_bold),
        Paragraph("<b>% CMV</b>", cell_bold),
    ]]

    total_cmv_safe = max(0.01, float(fb.get("total_cmv", 0.0) or 0.01))
    for ing in recipe_ingredients:
        w_g = float(ing.get("w", 0.0) or 0.0)
        c_kg = float(ing.get("cost_kg", 0.0) or 0.0)
        yf = float(ing.get("yield_factor", 1.0) or 1.0)
        c_item = calculate_ingredient_cost(w_g, c_kg, yf)
        pct_cmv = (c_item / total_cmv_safe * 100.0) if fb.get("total_cmv", 0.0) > 0 else 0.0
        clean_name = html.escape((ing.get("d", "") or "").rstrip(", "))
        ing_rows.append([
            "[  ]",
            Paragraph(clean_name, cell_style),
            f"{w_g:.1f}",
            f"{yf:.2f}x",
            f"R$ {c_kg:.2f}",
            f"R$ {c_item:.2f}",
            f"{pct_cmv:.0f}%",
        ])

    ing_rows.append([
        "",
        Paragraph("<b>TOTAL DE INGREDIENTES (CMV)</b>", cell_bold),
        f"{sum(float(i.get('w', 0.0) or 0.0) for i in recipe_ingredients):.1f} g",
        "-",
        "-",
        Paragraph(f"<b>R$ {fb['total_cmv']:.2f}</b>", cell_bold),
        "100%"
    ])

    t_ing = Table(ing_rows, colWidths=[28, 222, 58, 38, 62, 70, 50])
    t_ing.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#E6F4F1")),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#F3F4F6")),
        ('BOX', (0, 0), (-1, -1), 1.0, colors.HexColor("#0B3B4C")),
        ('INNERGRID', (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(t_ing)
    story.append(Spacer(1, 10))

    # 2. Anatomia de Custos de Produção
    story.append(Paragraph("2. RESUMO DE CUSTOS DE PRODUÇÃO (POR UNIDADE E LOTE INTEIRO)", sec_style))
    cost_rows = [
        [Paragraph("<b>Componente de Custo</b>", cell_bold), Paragraph("<b>Por Unidade</b>", cell_bold), Paragraph("<b>Receita Completa (Lote)</b>", cell_bold)],
        ["Ingredientes (Matéria-prima / CMV)", f"R$ {fb['unit_cmv']:.2f}", f"R$ {fb['total_cmv']:.2f}"],
        ["Embalagem (Pote, forminha, caixa, fita)", f"R$ {fb['unit_packaging']:.2f}", f"R$ {fb['total_packaging']:.2f}"],
        [f"Sua Mão de Obra ({prep_time_min:.0f} min a R$ {hourly_rate:.2f}/h)", f"R$ {fb['unit_labor']:.2f}", f"R$ {fb['total_labor']:.2f}"],
        [f"Contas Fixas: Gás, Luz, Água, MEI ({overhead_pct:.0f}%)", f"R$ {fb['unit_overhead']:.2f}", f"R$ {fb['total_overhead']:.2f}"],
        [Paragraph("<b>CUSTO TOTAL DE PRODUÇÃO</b>", cell_bold), Paragraph(f"<b>R$ {fb['unit_total_cost']:.2f}</b>", cell_bold), Paragraph(f"<b>R$ {fb['total_production_cost']:.2f}</b>", cell_bold)],
    ]
    t_cost = Table(cost_rows, colWidths=[308, 110, 110])
    t_cost.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#E6F4F1")),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#FEF3C7")),
        ('BOX', (0, 0), (-1, -1), 1.0, colors.HexColor("#0B3B4C")),
        ('INNERGRID', (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(t_cost)
    story.append(Spacer(1, 10))

    # 3. Faixas de Preço Recomendadas e Lucro Livre
    story.append(Paragraph(f"3. FAIXAS DE PREÇO E LUCRO LIVRE (Considerando {sales_fees_pct:.1f}% de Taxa de Venda)", sec_style))
    price_rows = [
        [Paragraph("<b>Faixa de Preço</b>", cell_bold), Paragraph("<b>Preço / un.</b>", cell_bold), Paragraph("<b>Venda do Lote</b>", cell_bold), Paragraph("<b>Lucro Livre / un.</b>", cell_bold), Paragraph("<b>Lucro no Lote</b>", cell_bold)],
        ["1. Preço Mínimo (Zero Prejuízo)", f"R$ {fb['min_unit_price']:.2f}", f"R$ {fb['min_total_price']:.2f}", "R$ 0.00 (0%)", "R$ 0.00"],
        ["2. Preço Ideal Sugerido", f"R$ {fb['suggested_unit_price']:.2f}", f"R$ {fb['suggested_total_price']:.2f}", f"R$ {fb['sug_net_profit']:.2f} ({fb['sug_net_margin_pct']:.0f}%)", f"R$ {fb['sug_net_profit'] * num_units:.2f}"],
        ["3. Preço Gourmet / Premium", f"R$ {fb['premium_unit_price']:.2f}", f"R$ {fb['premium_total_price']:.2f}", "-", "-"],
        [Paragraph("<b>SEU PREÇO PRATICADO ATUAL</b>", cell_bold), Paragraph(f"<b>R$ {fb['prac_unit_price']:.2f}</b>", cell_bold), Paragraph(f"<b>R$ {fb['prac_unit_price'] * num_units:.2f}</b>", cell_bold), Paragraph(f"<b>R$ {fb['prac_net_profit']:.2f} ({fb['prac_net_margin_pct']:.1f}%)</b>", cell_bold), Paragraph(f"<b>R$ {fb['prac_net_profit'] * num_units:.2f}</b>", cell_bold)],
    ]
    t_price = Table(price_rows, colWidths=[188, 80, 85, 95, 80])
    t_price.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#E6F4F1")),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#D1FAE5")),
        ('BOX', (0, 0), (-1, -1), 1.0, colors.HexColor("#0B3B4C")),
        ('INNERGRID', (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(t_price)
    story.append(Spacer(1, 10))
    story.append(Paragraph("<i>Gerado gratuitamente pelo Rotulei App — Gestão de Custos, Ficha Técnica e Rotulagem de Alimentos.</i>", ParagraphStyle('FTFoot', parent=cell_style, textColor=colors.gray, fontSize=7.5)))

    doc.build(story)
    pdf_buffer.seek(0)
    return pdf_buffer.getvalue()

def trigger_consume_credit():
    """Callback atômico e unificado para débito de 1 crédito ao baixar o PDF."""
    if st.session_state.get("credito_sendo_consumido", False):
        return
    st.session_state.credito_sendo_consumido = True
    try:
        ok, msg = consume_user_credit(st.session_state.username, db_lock)
        if not ok:
            logger.warning(f"Aviso ao debitar crédito para '{st.session_state.username}': {msg}")
    except Exception as e:
        logger.error(f"Exceção ao consumir crédito: {e}", exc_info=True)
    finally:
        st.session_state.credito_sendo_consumido = False

# --- LOGIN / CADASTRO FLOW ---
if not st.session_state.logged_in:
    # CSS injetado específico para a tela de login (foco no 'Above the Fold')
    st.markdown("""
        <style>
        /* Reduzir padding do container principal apenas no login */
        .block-container {
            padding-top: 1.2rem !important;
            padding-bottom: 1rem !important;
        }
        
        /* Centralizar e limitar tamanho do logo */
        div[data-testid="stImage"] > img {
            margin: 0 auto !important;
            display: block !important;
            max-width: 250px !important;
            max-height: 80px !important;
            object-fit: contain !important;
        }
        
        /* Compactar o título alternativo caso o logo não carregue */
        .main-title {
            font-size: 1.8rem !important;
            margin-top: 5px !important;
            margin-bottom: 2px !important;
            text-align: center !important;
        }
        
        /* Compactar subtítulo e margens descritivas */
        .subtitle {
            font-size: 0.85rem !important;
            margin-top: 2px !important;
            margin-bottom: 12px !important;
            text-align: center !important;
            line-height: 1.3 !important;
        }
        
        /* Otimizar espaçamentos do formulário e das abas */
        div[data-testid="stTabBar"] {
            margin-bottom: 5px !important;
        }
        div[data-testid="stForm"] {
            padding: 15px 20px !important;
            border-radius: 12px !important;
        }
        div[data-testid="stForm"] input {
            padding: 8px 12px !important;
        }
        div[data-testid="stForm"] label {
            font-size: 0.85rem !important;
            margin-bottom: 2px !important;
        }
        div[data-testid="element-container"] {
            margin-bottom: 6px !important;
        }
        </style>
    """, unsafe_allow_html=True)

    # Criar uma caixa centralizada com colunas
    col_left, col_center, col_right = st.columns([1, 1.3, 1])
    
    with col_center:
        # Inserção do logotipo oficial centralizado no topo
        if os.path.exists("assets/logo.jpg"):
            st.image("assets/logo.jpg", width=250)
        else:
            st.markdown('<h1 class="main-title" style="text-align: center; font-size: 2.2rem; margin-top: 10px;">Rotulei App</h1>', unsafe_allow_html=True)
            
        st.markdown('<p class="subtitle" style="text-align: center; margin-bottom: 25px;">Engenharia de Custos, Ficha Técnica Financeira & Rotulagem ANVISA unificada TBCA + TACO.</p>', unsafe_allow_html=True)

        # Verificação silenciosa de erros de banco — log interno apenas (não exposto ao usuário)
        error_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db_error.log")
        if os.path.exists(error_log_path):
            try:
                with open(error_log_path, "r", encoding="utf-8") as f:
                    log_content = f.read()
                logger.error(f"[db_error.log detectado na inicialização]:\n{log_content}")
            except Exception as read_err:
                logger.warning(f"Falha ao ler db_error.log: {read_err}")

        # Estrutura de abas (st.tabs) limpa e minimalista no topo do formulário
        tab_login, tab_registro, tab_recuperar = st.tabs(["Entrar", "Criar Conta Grátis", "Recuperar Senha"])
        
        with tab_login:
            st.markdown('<h4 style="margin-top: 15px; margin-bottom: 15px; color: #0b3b4c; text-align: center;">Entrar no Sistema</h4>', unsafe_allow_html=True)
            with st.form("form_login_usuario"):
                login_user = st.text_input("Usuário ou E-mail:", placeholder="Digite seu usuário ou e-mail", key="login_username_field")
                login_pass = st.text_input("Senha:", type="password", placeholder="Digite sua senha", key="login_password_field")
                
                submit_login = st.form_submit_button("Acessar Painel", type="primary", use_container_width=True)
                if submit_login:
                    success, result, is_admin = authenticate_user(login_user, login_pass, db_lock)
                    if success:
                        st.session_state.logged_in = True
                        st.session_state.username = result
                        st.session_state.is_admin = is_admin
                        st.toast(f"Bem-vindo(a) de volta, {result}!")
                        st.rerun()
                    else:
                        st.error(result)
                        
        with tab_registro:
            st.markdown('<h4 style="margin-top: 15px; margin-bottom: 6px; color: #0b3b4c; text-align: center;">Criar Conta Rápida</h4>', unsafe_allow_html=True)
            st.caption("✨ Sem burocracia: não pedimos CPF agora e você já começa com 1 crédito de rótulo grátis!")
            with st.form("form_registro_usuario"):
                new_user = st.text_input("Seu Nome ou Nome do Ateliê (Usuário):", placeholder="Ex: marcia_doces", key="reg_username_field")
                new_email = st.text_input("Seu E-mail:", placeholder="Ex: marcia@email.com", key="reg_email_field")
                new_pass = st.text_input("Crie uma Senha:", type="password", placeholder="Mínimo de 8 caracteres", key="reg_password_field")
                
                with st.expander("🛡️ Ler Termos de Uso e Política de Privacidade (LGPD)"):
                    st.markdown("""
                    **TERMO DE CONSENTIMENTO E PRIVACIDADE (LGPD)**
                    
                    De acordo com a Lei Geral de Proteção de Dados (Lei nº 13.709/2018), este termo informa como tratamos suas informações:
                    
                    1. **Quais dados coletamos:** Coletamos seu nome de usuário e e-mail para fins de identificação e segurança, além do hash criptografado (`bcrypt`) da sua senha e as fichas técnicas que você salvar.
                    2. **Finalidade:** Permitir que você gerencie, edite e visualize suas próprias fichas técnicas e rótulos de forma privada.
                    3. **Armazenamento e Compartilhamento:** Não compartilhamos, vendemos ou divulgamos suas receitas ou credenciais para terceiros em hipótese alguma.
                    4. **Exclusão de Dados:** Você é proprietária(o) dos seus dados e pode excluir suas receitas a qualquer momento.
                    """)
                
                lgpd_accept = st.checkbox("Li e concordo com os Termos de Uso e Privacidade (LGPD).", value=True, key="lgpd_checkbox")
                
                submit_register = st.form_submit_button("🚀 Criar Conta e Começar Agora", type="primary", use_container_width=True)
                if submit_register:
                    if not new_user.strip() or not new_email.strip() or not new_pass:
                        st.error("Por favor, preencha seu nome de usuário, e-mail e senha.")
                    elif len(new_pass) < 8:
                        st.error("A senha deve ter pelo menos 8 caracteres para sua segurança.")
                    elif not lgpd_accept:
                        st.error("Você precisa aceitar os termos de privacidade da LGPD para prosseguir.")
                    else:
                        success, msg = register_user(new_user, new_email, "", new_pass, lgpd_accept, db_lock)
                        if success:
                            st.session_state.logged_in = True
                            st.session_state.username = new_user.strip()
                            st.session_state.is_admin = False
                            st.success(msg)
                            st.toast(f"Conta criada! Bem-vinda(o), {new_user.strip()}!")
                            st.rerun()
                        else:
                            st.error(msg)
                            
        with tab_recuperar:
            st.markdown('<h4 style="margin-top: 15px; margin-bottom: 15px; color: #0b3b4c; text-align: center;">Recuperação de Senha</h4>', unsafe_allow_html=True)
            st.info("Para redefinir sua senha, informe o e-mail cadastrado na sua conta. Você receberá uma senha temporária.")
            with st.form("form_recuperar_senha"):
                rec_email = st.text_input("E-mail cadastrado:", key="rec_email")
                
                submit_rec = st.form_submit_button("Enviar E-mail de Recuperação", type="primary", use_container_width=True)
                if submit_rec:
                    if not rec_email:
                        st.error("Preencha o campo de e-mail para recuperar a senha.")
                    else:
                        with st.spinner("Enviando e-mail..."):
                            success, msg = recover_password_email(rec_email, db_lock)
                        if success:
                            st.success(msg)
                        else:
                            st.error(msg)

        # --- CALCULADORA RÁPIDA PÚBLICA (ONBOARDING ANTES DO CADASTRO) ---
        with st.expander("⚡ Quer testar antes de criar conta? Simule o preço de 1 receita em 30 segundos"):
            st.caption("Descubra se o preço que você cobra hoje dá lucro ou prejuízo:")
            d_c1, d_c2 = st.columns(2)
            demo_ing_total = d_c1.number_input("Gasto total com ingredientes (R$):", min_value=0.5, value=16.50, step=1.0, key="demo_ing")
            demo_units = d_c2.number_input("Rende quantas unidades?", min_value=1, value=25, step=1, key="demo_un")
            d_c3, d_c4 = st.columns(2)
            demo_emb = d_c3.number_input("Embalagem por unidade (R$):", min_value=0.0, value=0.25, step=0.1, key="demo_emb")
            demo_margin = d_c4.slider("Margem de lucro desejada (%):", min_value=10, max_value=60, value=35, key="demo_m")
            demo_fb = calculate_financial_breakdown(
                recipe_ingredients=[{"w": 1000.0, "cost_kg": demo_ing_total, "yield_factor": 1.0}],
                packaging_cost=demo_emb,
                prep_time_min=30.0,
                hourly_rate=20.0,
                overhead_pct=10.0,
                target_margin_pct=float(demo_margin),
                sales_fees_pct=4.5,
                num_units=float(demo_units)
            )
            st.markdown(f"""
            <div style="background:#ecfdf5; border-left:4px solid #10b981; padding:10px 14px; border-radius:8px; margin-top:6px;">
                <strong>Preço Mínimo (sem prejuízo):</strong> R$ {demo_fb['min_unit_price']:.2f}/un<br>
                <strong style="color:#065f46; font-size:1.05rem;">🎯 Preço Ideal Sugerido: R$ {demo_fb['suggested_unit_price']:.2f}/un</strong><br>
                <small style="color:#047857;">Inclui ingredientes, embalagem, seu tempo de preparo (30 min) e gás/luz. Lucro livre no lote: <strong>R$ {demo_fb['sug_net_profit'] * demo_units:.2f}</strong>!</small>
            </div>
            """, unsafe_allow_html=True)
            st.caption("👆 Clique na aba **Criar Conta Grátis** acima para salvar suas fichas técnicas completas!")
    st.stop()

# --- NAVEGAÇÃO NA SIDEBAR ---
if "selected_page" not in st.session_state:
    st.session_state.selected_page = "Ficha Técnica & Precificação"

nav_options = [
    "Ficha Técnica & Precificação", 
    "Tabela Nutricional & ANVISA",
    "Minhas Fichas Técnicas", 
    "Cadastrar Novo Ingrediente",
    "Meu Perfil",
    "Suporte & Ajuda"
]
is_admin = st.session_state.get("is_admin", False)
if is_admin:
    nav_options.append("Painel Administrador")

# Sidebar do Usuário Conectado
with st.sidebar:
    # 1. Logo oficial
    if os.path.exists("assets/logo.jpg"):
        st.image("assets/logo.jpg", use_container_width=True)
    else:
        st.markdown('<h2 style="font-family: \'Outfit\', sans-serif; color: #0b3b4c; margin: 0; font-weight: 800;">Rotulei App</h2>', unsafe_allow_html=True)
        st.markdown('<p style="font-size: 0.8rem; color: #6b7280; margin-bottom: 20px;">Precificação & Rotulagem de Alimentos</p>', unsafe_allow_html=True)
        
    st.markdown("---")
    
    # Renderizar botões de navegação estilizados (sem bolinhas)
    for option in nav_options:
        is_selected = (st.session_state.selected_page == option)
        btn_type = "primary" if is_selected else "secondary"
        if st.button(option, type=btn_type, use_container_width=True, key=f"nav_btn_{option}"):
            st.session_state.selected_page = option
            st.rerun()
    
    # 2. Exibição do Saldo (Estilo SaaS Premium)
    from utils.db import get_user_credits_cached
    current_user_side = get_user_credits_cached(st.session_state.username)
    
    st.markdown("---")
    if st.session_state.get("is_admin", False):
        st.markdown(f"""
        <div style="background-color: #f3f4f6; border-left: 4px solid #9ca3af; padding: 12px; border-radius: 8px; margin-bottom: 12px; margin-top: 30px;">
            <p style="margin: 0; font-size: 0.75rem; color: #4b5563; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px;">Saldo</p>
            <p style="margin: 0; font-size: 1.1rem; color: #111827; font-weight: 800;">Ilimitado (Admin)</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        creditos_side = current_user_side.get("creditos_disponiveis", 0) if current_user_side else 0
        st.markdown(f"""
        <div style="background-color: #e6f7f4; border-left: 4px solid #00a88f; padding: 12px 12px 6px 12px; border-radius: 8px 8px 0px 0px; margin-bottom: 0px; margin-top: 30px;">
            <p style="margin: 0; font-size: 0.75rem; color: #007d70; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px;">Saldo de Créditos</p>
            <p style="margin: 0; font-size: 1.3rem; color: #0b3b4c; font-weight: 800; line-height: 1.2;">{creditos_side} <span style="font-size: 0.85rem; font-weight: normal; color: #007d70;">disponíveis</span></p>
        </div>
        """, unsafe_allow_html=True)
        
        # Botão elegante para adquirir créditos (com classe de wrapper para estilo sólido)
        st.markdown('<div class="buy-credits-wrapper"></div>', unsafe_allow_html=True)
        if st.button("Adquirir Créditos", type="primary", use_container_width=True):
            st.session_state.selected_page = "Meu Perfil"
            st.rerun()

        # Botão discreto para atualizar o saldo e invalidar o cache local
        if st.button("🔄 Atualizar Saldo", type="secondary", use_container_width=True):
            try:
                from utils.db import get_user_credits_cached
                get_user_credits_cached.clear()
            except Exception:
                pass
            st.rerun()
            
    # Bloco de Usuário no Rodapé (Estilo SaaS Premium)
    plan_info_sb = get_user_plan_status(st.session_state.username, db_lock)
    st.markdown("---")
    st.markdown(f"""
    <div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px; font-size: 0.8rem; color: #4b5563; margin-top: 15px;">
        <p style="margin: 0; font-weight: bold; font-size: 0.7rem; text-transform: uppercase; color: #9ca3af; letter-spacing: 0.5px;">Sessão Ativa</p>
        <p style="margin: 3px 0 4px 0; font-size: 0.85rem; color: #111827;"><strong>{html.escape(st.session_state.username)}</strong></p>
        <p style="margin: 0; font-size: 0.76rem; color: #059669; font-weight: 700;">{plan_info_sb['plan_label']}</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown('<div class="logout-wrapper"></div>', unsafe_allow_html=True)
    if st.button("Sair da Conta", type="secondary", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state.is_admin = False
        st.session_state.recipe = []
        st.session_state.calculated = False
        st.session_state.nome_produto = ""
        st.session_state.peso_embalagem = 0.0
        st.toast("Você saiu da conta.")
        st.rerun()

# --- SUCESSO NO PAGAMENTO MERCADO PAGO ---
if st.query_params.get("status") == "approved":
    st.success("🎉 **Pagamento Aprovado com Sucesso!** Seus créditos foram adicionados à sua conta.")
    st.balloons()
    st.query_params.clear()

# ==============================================================================
# TAB 1: FICHA TÉCNICA & PRECIFICAÇÃO DE PRODUTOS (PRODUTO PRINCIPAL)
# ==============================================================================
if st.session_state.selected_page == "Ficha Técnica & Precificação":
    st.markdown('<h1 class="main-title">Ficha Técnica & Precificação</h1>', unsafe_allow_html=True)
    st.markdown('<p class="subtitle">Descubra o custo real da sua receita, quanto cobrar em cada canal e quanto sobra de lucro livre no seu bolso.</p>', unsafe_allow_html=True)

    model_recipes = get_model_recipes(foods_data)

    # --- ESTADO VAZIO ACOLHEDOR / RECEITAS MODELO EM 1 CLIQUE ---
    if len(st.session_state.recipe) == 0:
        st.markdown("""
        <div style="background: linear-gradient(135deg, #f0fdfa 0%, #e0f2fe 100%); border: 2px solid #00a896; border-radius: 16px; padding: 18px 20px; margin-bottom: 18px;">
            <h4 style="margin: 0 0 6px 0; color: #0b3b4c;">👋 Primeira vez por aqui? Comece em 1 clique!</h4>
            <p style="margin: 0; font-size: 0.92rem; color: #374151;">
                Toque em uma das receitas prontas abaixo para ver na hora o custo de cada ingrediente, o preço sugerido e o lucro real — ou adicione seus próprios ingredientes no Passo 1.
            </p>
        </div>
        """, unsafe_allow_html=True)
        t_cols = st.columns(4)
        for idx_t, (t_key, tpl) in enumerate(model_recipes.items()):
            if t_cols[idx_t].button(tpl["label"], key=f"btn_tpl_empty_{t_key}", type="primary" if idx_t == 0 else "secondary", use_container_width=True):
                apply_model_recipe(tpl)
                st.toast(f"Receita modelo '{tpl['nome_produto']}' carregada!")
                st.rerun()
    else:
        with st.expander("✨ Quer testar outra Receita Modelo pronta? (Brigadeiro, Bolo no Pote, Pão de Mel, Geleia)"):
            t_cols = st.columns(4)
            for idx_t, (t_key, tpl) in enumerate(model_recipes.items()):
                if t_cols[idx_t].button(tpl["label"], key=f"btn_tpl_bar_{t_key}", use_container_width=True):
                    apply_model_recipe(tpl)
                    st.toast(f"Receita modelo '{tpl['nome_produto']}' carregada!")
                    st.rerun()

        # --- RESUMO NO TOPO (MOBILE-FIRST HERO BANNER) ---
        ref_unit_top = st.session_state.peso_embalagem if st.session_state.peso_embalagem > 0 else st.session_state.weight_final
        num_units_top = max(1.0, st.session_state.weight_final / ref_unit_top) if ref_unit_top > 0 else 1.0
        fb_top = calculate_financial_breakdown(
            recipe_ingredients=st.session_state.recipe,
            packaging_cost=st.session_state.custo_embalagem,
            prep_time_min=st.session_state.tempo_preparo_min,
            hourly_rate=st.session_state.custo_hora_mao_obra,
            overhead_pct=st.session_state.custo_operacional_pct,
            target_margin_pct=st.session_state.margem_desejada_pct,
            sales_fees_pct=st.session_state.taxas_venda_pct,
            num_units=num_units_top,
            practiced_price=st.session_state.preco_venda_praticado
        )
        lucro_lote_top = fb_top["prac_net_profit"] * num_units_top
        st.markdown(f"""
        <div class="hero-profit-banner">
            <div class="hero-profit-item">
                <div class="hero-profit-label">Custo Total / Unidade</div>
                <div class="hero-profit-val">R$ {fb_top['unit_total_cost']:.2f}</div>
                <div class="hero-profit-sub">Ingredientes: R$ {fb_top['unit_cmv']:.2f}/un</div>
            </div>
            <div class="hero-profit-item">
                <div class="hero-profit-label">🎯 Preço Ideal Sugerido</div>
                <div class="hero-profit-val">R$ {fb_top['suggested_unit_price']:.2f}</div>
                <div class="hero-profit-sub">Mínimo s/ prejuízo: R$ {fb_top['min_unit_price']:.2f}</div>
            </div>
            <div class="hero-profit-item">
                <div class="hero-profit-label">💰 Seu Lucro por Unidade</div>
                <div class="hero-profit-val">R$ {fb_top['prac_net_profit']:.2f}</div>
                <div class="hero-profit-sub">Margem livre: {fb_top['prac_net_margin_pct']:.1f}%</div>
            </div>
            <div class="hero-profit-item">
                <div class="hero-profit-label">Lucro do Lote ({num_units_top:.0f} un)</div>
                <div class="hero-profit-val">R$ {lucro_lote_top:.2f}</div>
                <div class="hero-profit-sub">Custo do lote: R$ {fb_top['total_production_cost']:.2f}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Grid de Layout
    col_input, col_label = st.columns([1.12, 0.88])

    with col_input:
        st.markdown("### 🍳 1. Ingredientes da sua Receita")

        from utils.data_loader import (
            get_recipes_as_ingredients,
            INGREDIENT_CATEGORIES,
            TOP_CONFECTIONERY_MAP,
            filter_and_rank_ingredients,
            format_ingredient_option_label,
        )

        curr_user = st.session_state.get("username", "")
        sub_recipes = get_recipes_as_ingredients(db_lock, curr_user)
        dynamic_foods = foods_data + sub_recipes

        col_cat, col_search = st.columns([1.0, 1.3])
        selected_cat = col_cat.selectbox(
            "Categoria de Insumo:",
            options=INGREDIENT_CATEGORIES,
            key="recipe_cat_filter",
            help="Filtre rapidamente por laticínios, chocolates, farinhas, frutas ou veja os mais usados na confeitaria."
        )
        search_query = col_search.text_input(
            "Buscar pelo nome (ex: Leite condensado, Ninho, Maisena):",
            placeholder="Digite para filtrar (ex: Manteiga, Cacau, Morango)...",
            key="recipe_search"
        )

        include_prepared = st.checkbox(
            "🔎 Mostrar também pratos prontos e base completa da TBCA (6.265 itens)",
            value=False,
            key="inc_prep_dishes",
            help="Por padrão ocultamos ~4.500 pratos prontos de restaurante (lasanhas, canelones, carnes temperadas) para você encontrar os ingredientes puros muito mais rápido."
        )

        filtered_for_recipe = filter_and_rank_ingredients(
            foods_list=dynamic_foods,
            search_query=search_query,
            category=selected_cat,
            include_prepared_dishes=include_prepared
        )

        # Fallback inteligente: se não encontrou nos ingredientes puros mas existe na base completa, busca automaticamente
        if not filtered_for_recipe and search_query.strip() and not include_prepared:
            filtered_for_recipe = filter_and_rank_ingredients(
                foods_list=dynamic_foods,
                search_query=search_query,
                category="⭐ Todos os Ingredientes Base",
                include_prepared_dishes=True
            )
            if filtered_for_recipe:
                st.caption("ℹ️ *Exibindo resultados da base completa da TBCA para sua busca.*")

        if not filtered_for_recipe:
            st.warning("Nenhum ingrediente encontrado com esse termo. Tente outra palavra ou cadastre na aba 'Cadastrar Novo Ingrediente'.")
            selected_recipe_food = foods_data[0]
        else:
            selected_recipe_food = st.selectbox(
                "Selecione o ingrediente (⭐ = Mais usados na confeitaria):",
                options=filtered_for_recipe,
                format_func=format_ingredient_option_label,
                key="recipe_ing_selectbox"
            )

        modo_custo_ing = st.radio(
            "Como prefere informar o preço deste ingrediente?",
            options=[
                "📦 Pelo preço da embalagem que comprei (Mais fácil)",
                "⚖️ Pelo preço por Quilo (R$/kg)"
            ],
            horizontal=True,
            key="modo_custo_ing_radio",
            help="Ex: Se você pagou R$ 7,90 numa lata de 395g de leite condensado, use a primeira opção e o sistema faz a conta sozinho!"
        )

        default_cost_kg = float(selected_recipe_food["n"].get("Custo (R$/kg)", 0.0) or 0.0)

        if modo_custo_ing.startswith("📦"):
            c_p1, c_p2, c_p3, c_p4 = st.columns([1.1, 1.1, 1.0, 1.1])
            ing_weight = c_p1.number_input("Usado na receita (g/ml):", min_value=0.1, value=395.0, step=10.0, key="add_ing_weight_pkg", help="Quantidade em gramas ou ml que vai na sua receita.")
            pkg_price = c_p2.number_input("Paguei na embalagem (R$):", min_value=0.0, value=7.90 if default_cost_kg == 0 else round(default_cost_kg * 0.395, 2), step=0.50, key="add_pkg_price", help="Valor pago no pacote, lata, caixa ou dúzia fechada.")
            pkg_qty = c_p3.number_input("Tamanho da emb.:", min_value=0.1, value=395.0, step=50.0, key="add_pkg_qty", help="Ex: 395 para uma lata de 395g, 1 para 1kg ou 1 dúzia.")
            pkg_unit = c_p4.selectbox("Unidade da emb.:", options=["g", "kg", "ml", "L", "dúzia (12 ovos)", "cartela 30 ovos", "un (ovo ~50g)"], key="add_pkg_unit")
            ing_cost_init = convert_package_to_cost_kg(pkg_price, pkg_qty, pkg_unit)
            custo_nesta_receita_preview = calculate_ingredient_cost(ing_weight, ing_cost_init, 1.0)
            st.caption(f"💡 **Conversão automática:** esta embalagem equivale a **R$ {ing_cost_init:.2f}/kg** → Custo dos **{ing_weight:.0f}g** nesta receita = **R$ {custo_nesta_receita_preview:.2f}**")
        else:
            col_w, col_cost = st.columns(2)
            ing_weight = col_w.number_input("Peso usado na receita (g/ml):", min_value=0.1, value=100.0, step=10.0, key="add_ing_weight")
            ing_cost_init = col_cost.number_input("Custo por Quilo (R$/kg):", min_value=0.0, value=default_cost_kg, step=1.0, key="add_ing_cost")

        with st.expander("🍓 Este ingrediente tem perda ao descascar ou limpar? (Opcional — Fator de Correção)"):
            perda_preparo_pct = st.slider(
                "Perda de limpeza/descasque (%):",
                min_value=0, max_value=60, value=0, step=5,
                key="add_ing_loss_pct",
                help="Ex: Morango ou abacaxi perde ~10% a 20% com cabinho/casca. Se não há perda (leite condensado, farinha, açúcar), deixe 0%."
            )
            yf_init = round(100.0 / (100.0 - perda_preparo_pct), 2) if perda_preparo_pct > 0 else 1.0
            if perda_preparo_pct > 0:
                st.caption(f"Fator de Correção aplicado: **{yf_init:.2f}x** (considera a perda no custo real).")

        if st.button("➕ Adicionar Ingrediente à Receita", type="primary", use_container_width=True):
            st.session_state.recipe.append({
                "c": selected_recipe_food["c"],
                "d": selected_recipe_food["d"],
                "f": selected_recipe_food["f"],
                "w": ing_weight,
                "cost_kg": ing_cost_init,
                "yield_factor": yf_init,
                "n": selected_recipe_food["n"]
            })
            st.session_state.calculated = True
            st.session_state.weight_final = sum(ing["w"] for ing in st.session_state.recipe)
            if st.session_state.yield_units > 0:
                st.session_state.peso_embalagem = round(st.session_state.weight_final / st.session_state.yield_units, 1)
            st.toast(f"**{selected_recipe_food['d']}** adicionado à receita!")
            st.rerun()

        st.markdown("---")

        if len(st.session_state.recipe) > 0:
            col_hdr, col_mul, col_div, col_clr = st.columns([2.0, 0.6, 0.6, 0.9])
            col_hdr.markdown("### 🛒 Ingredientes na Receita")
            if col_mul.button("✖️ 2x", type="secondary", use_container_width=True, help="Dobrar a receita inteira"):
                for ing in st.session_state.recipe:
                    ing["w"] *= 2.0
                st.session_state.weight_final *= 2.0
                st.session_state.yield_units = max(1, int(st.session_state.yield_units * 2))
                st.rerun()
            if col_div.button("➗ ½", type="secondary", use_container_width=True, help="Fazer meia receita"):
                for ing in st.session_state.recipe:
                    ing["w"] /= 2.0
                st.session_state.weight_final /= 2.0
                st.session_state.yield_units = max(1, int(round(st.session_state.yield_units / 2)))
                st.rerun()
            if col_clr.button("🗑️ Limpar", type="secondary", use_container_width=True):
                st.session_state.recipe = []
                st.session_state.weight_final = 0.0
                st.session_state.calculated = False
                st.toast("Receita limpa!")
                st.rerun()

            new_recipe_list = []
            for idx, ing in enumerate(st.session_state.recipe):
                col_ing_name, col_ing_weight, col_ing_cost, col_ing_del = st.columns([2.1, 1.0, 1.0, 0.35])
                safe_d = html.escape(ing['d'])
                yf_item = float(ing.get('yield_factor', 1.0) or 1.0)
                custo_item_receita = calculate_ingredient_cost(float(ing['w']), float(ing.get('cost_kg', 0.0)), yf_item)
                fc_badge = f" · FC {yf_item:.2f}x" if yf_item > 1.01 else ""
                col_ing_name.markdown(
                    f"**{safe_d}**<br>"
                    f"<span style='color:#059669; font-weight:700; font-size:0.84rem;'>Custo na receita: R$ {custo_item_receita:.2f}</span>"
                    f"<small style='color:gray;'> ({html.escape(ing['f'])}{fc_badge})</small>",
                    unsafe_allow_html=True
                )

                w_val = col_ing_weight.number_input("Qtd (g/ml)", min_value=0.1, value=float(ing['w']), key=f"fin_ing_w_{idx}_{ing['c']}", step=5.0)
                c_val = col_ing_cost.number_input("R$/kg", min_value=0.0, value=float(ing.get('cost_kg', 0.0)), key=f"fin_ing_c_{idx}_{ing['c']}", step=1.0)
                rem_val = col_ing_del.checkbox("🗑️", key=f"fin_ing_rem_{idx}_{ing['c']}", help="Marque para remover este ingrediente")

                if not rem_val:
                    ing_copy = ing.copy()
                    ing_copy["w"] = w_val
                    ing_copy["cost_kg"] = c_val
                    new_recipe_list.append(ing_copy)

            if len(new_recipe_list) != len(st.session_state.recipe) or any(
                n['w'] != o['w'] or n.get('cost_kg', 0.0) != o.get('cost_kg', 0.0)
                for n, o in zip(new_recipe_list, st.session_state.recipe)
            ):
                st.session_state.recipe = new_recipe_list
                st.session_state.calculated = True
                st.rerun()

            st.markdown("---")
            st.markdown("### 📦 2. Rendimento, Embalagem & Seu Trabalho")

            nome_produto = st.text_input(
                "Nome do seu Produto:",
                placeholder="Ex: Brigadeiro Gourmet Tradicional, Bolo no Pote de Ninho...",
                value=st.session_state.nome_produto,
                key="fin_nome_prod"
            )

            yield_mode_options = [
                "Por Unidades Prontas (ex: 25 brigadeiros)",
                "Por Peso Total em Gramas (g/ml)"
            ]
            curr_ym_idx = 0 if st.session_state.yield_mode.startswith("Por Unidades") else 1
            yield_mode_sel = st.radio(
                "Como você conta o rendimento desta receita?",
                options=yield_mode_options,
                index=curr_ym_idx,
                horizontal=True,
                key="fin_yield_mode_radio"
            )
            st.session_state.yield_mode = yield_mode_sel

            soma_pesos_brutos = max(1.0, sum(float(i["w"]) for i in st.session_state.recipe))

            if yield_mode_sel.startswith("Por Unidades"):
                col_u1, col_u2, col_u3 = st.columns(3)
                default_units = max(1, int(round(st.session_state.weight_final / st.session_state.peso_embalagem))) if st.session_state.peso_embalagem > 0 else int(max(1, st.session_state.yield_units))
                yield_units_val = col_u1.number_input(
                    "Rende quantas unidades?",
                    min_value=1,
                    value=default_units,
                    step=1,
                    key="fin_yield_units_input",
                    help="Quantos doces, potes, fatias ou pacotes prontos essa receita rende."
                )
                default_unit_w = st.session_state.peso_embalagem if st.session_state.peso_embalagem > 0 else round(soma_pesos_brutos / yield_units_val, 1)
                peso_embalagem = col_u2.number_input(
                    "Peso de cada unidade (g/ml):",
                    min_value=1.0,
                    value=float(max(1.0, default_unit_w)),
                    step=5.0,
                    key="fin_p_emb_unit_mode",
                    help="Peso aproximado de 1 unidade pronta (usado na Tabela Nutricional)."
                )
                custo_embalagem = col_u3.number_input(
                    "Custo Embalagem por un. (R$):",
                    min_value=0.0,
                    value=float(st.session_state.custo_embalagem),
                    step=0.10,
                    key="fin_c_emb_unit_mode",
                    help="Forminha, pote, tampa, colherzinha, fita e etiqueta de 1 unidade."
                )
                weight_final = float(yield_units_val * peso_embalagem)
                st.session_state.yield_units = int(yield_units_val)
            else:
                col_pkg1, col_pkg2, col_pkg3 = st.columns(3)
                weight_final = col_pkg1.number_input(
                    "Peso Total da Receita Pronta (g/ml):",
                    min_value=1.0,
                    value=float(max(st.session_state.weight_final, 1.0)),
                    key="fin_w_final",
                    help="Peso total do lote depois de pronto/cozido."
                )
                peso_embalagem = col_pkg2.number_input(
                    "Peso de cada Unidade Vendida (g/ml):",
                    min_value=0.0,
                    value=float(st.session_state.peso_embalagem),
                    key="fin_p_emb",
                    help="Peso líquido de cada unidade comercializada."
                )
                custo_embalagem = col_pkg3.number_input(
                    "Custo Embalagem por un. (R$):",
                    min_value=0.0,
                    value=float(st.session_state.custo_embalagem),
                    step=0.10,
                    key="fin_c_emb",
                    help="Pote, tampa, caixa, rótulo por unidade."
                )

            col_op1, col_op2, col_op3 = st.columns(3)
            tempo_preparo_min = col_op1.number_input(
                "Seu Tempo de Preparo (min):",
                min_value=0.0,
                value=float(st.session_state.tempo_preparo_min),
                step=5.0,
                key="fin_t_prep",
                help="Quantos minutos você gasta preparando, enrolando e embalando este lote."
            )
            custo_hora_mao_obra = col_op2.number_input(
                "Valor da sua Hora (R$/h):",
                min_value=0.0,
                value=float(st.session_state.custo_hora_mao_obra),
                step=2.0,
                key="fin_c_hora",
                help="Quanto vale 1 hora do seu trabalho na cozinha. Use a calculadora abaixo se não souber!"
            )
            custo_operacional_pct = col_op3.number_input(
                "Contas Fixas: Gás, Luz, MEI (%):",
                min_value=0.0,
                value=float(st.session_state.custo_operacional_pct),
                step=1.0,
                key="fin_c_op",
                help="Percentual para cobrir gás de cozinha, energia elétrica, água, detergente e DAS do MEI (costuma ficar entre 8% e 15%)."
            )

            # --- ASSISTENTES DE CÁLCULO (MÃO DE OBRA & CONTAS FIXAS) ---
            col_help1, col_help2 = st.columns(2)
            with col_help1:
                with st.expander("🧮 Não sabe quanto vale sua hora? Calcule aqui"):
                    sal_desejado = st.number_input("Quanto quer tirar de salário no mês? (R$):", min_value=100.0, value=2500.0, step=100.0, key="calc_sal_mes")
                    horas_dia = st.number_input("Quantas horas trabalha por dia?", min_value=1.0, max_value=16.0, value=6.0, step=1.0, key="calc_h_dia")
                    dias_sem = st.number_input("Quantos dias por semana?", min_value=1.0, max_value=7.0, value=5.0, step=1.0, key="calc_d_sem")
                    res_hora = calculate_hourly_labor_rate(sal_desejado, horas_dia, dias_sem)
                    st.info(f"👩‍🍳 Trabalhando ~**{res_hora['monthly_hours']:.0f}h/mês**, sua hora vale **R$ {res_hora['hourly_rate']:.2f}/h**.")
                    if st.button(f"✅ Usar R$ {res_hora['hourly_rate']:.2f}/h na receita", key="btn_apply_hora", use_container_width=True):
                        st.session_state.custo_hora_mao_obra = res_hora["hourly_rate"]
                        st.session_state.fin_c_hora = res_hora["hourly_rate"]
                        st.toast(f"Valor da hora atualizado para R$ {res_hora['hourly_rate']:.2f}/h!")
                        st.rerun()

            with col_help2:
                with st.expander("🔥 Ajuda para calcular Gás, Luz e Contas Fixas (%)"):
                    g_gas = st.number_input("Gás de cozinha no mês (R$):", min_value=0.0, value=120.0, step=10.0, key="calc_f_gas")
                    g_luz = st.number_input("Luz + Água da produção (R$):", min_value=0.0, value=150.0, step=10.0, key="calc_f_luz")
                    g_mei = st.number_input("DAS MEI + Internet/Outros (R$):", min_value=0.0, value=80.0, step=10.0, key="calc_f_mei")
                    g_fat = st.number_input("Quanto você vende por mês em média? (R$):", min_value=100.0, value=3000.0, step=200.0, key="calc_f_fat")
                    soma_fixos = g_gas + g_luz + g_mei
                    pct_sugerido = calculate_overhead_rate_pct(soma_fixos, g_fat)
                    st.info(f"💡 Suas contas somam **R$ {soma_fixos:.2f}/mês**, o que representa **{pct_sugerido:.1f}%** das vendas.")
                    if st.button(f"✅ Usar {pct_sugerido:.1f}% na receita", key="btn_apply_ov", use_container_width=True):
                        st.session_state.custo_operacional_pct = pct_sugerido
                        st.session_state.fin_c_op = pct_sugerido
                        st.toast(f"Contas fixas atualizadas para {pct_sugerido:.1f}%!")
                        st.rerun()

            st.markdown("---")
            st.markdown("### 🏷️ 3. Canal de Venda, Taxas & Margem de Lucro")

            presets_canal = {
                " Personalizado (digitar taxa abaixo)": None,
                "💵 PIX ou Dinheiro Direto (0% de taxa)": 0.0,
                "💳 Cartão de Crédito na Maquininha (~4,5%)": 4.5,
                "🛵 iFood Plano Básico (~15,2% c/ pagamento online)": 15.2,
                "🚀 iFood Plano Entrega Parceira (~26,2%)": 26.2,
            }
            canal_escolhido = st.selectbox(
                "Onde você vai vender este produto? (Atalho de taxas):",
                options=list(presets_canal.keys()),
                key="fin_canal_preset_sel",
                help="Escolha um canal para preencher a taxa automaticamente ou deixe em Personalizado."
            )
            if presets_canal[canal_escolhido] is not None:
                st.session_state.taxas_venda_pct = float(presets_canal[canal_escolhido])

            col_sim1, col_sim2, col_sim3 = st.columns(3)
            margem_desejada_pct = col_sim1.number_input(
                "Lucro Livre Desejado (%):",
                min_value=1.0, max_value=80.0,
                value=float(st.session_state.margem_desejada_pct),
                step=5.0,
                key="fin_m_desejada",
                help="Quanto do preço final você quer que sobre livre para crescer o negócio (recomendado em confeitaria: 25% a 45%)."
            )
            taxas_venda_pct = col_sim2.number_input(
                "Taxa de Maquininha / iFood (%):",
                min_value=0.0, max_value=50.0,
                value=float(st.session_state.taxas_venda_pct),
                step=0.5,
                key="fin_tx_venda",
                help="Desconto da maquininha de cartão, comissão do iFood ou imposto."
            )
            preco_venda_praticado = col_sim3.number_input(
                "Testar Meu Preço Atual (R$):",
                min_value=0.0,
                value=float(st.session_state.preco_venda_praticado),
                step=0.50,
                key="fin_p_praticado",
                help="Digite por quanto você vende hoje para ver se está lucrando! Deixe 0 para usar o Preço Ideal Sugerido."
            )

            # Atualizar session state
            st.session_state.nome_produto = nome_produto
            st.session_state.weight_final = weight_final
            st.session_state.peso_embalagem = peso_embalagem
            st.session_state.custo_embalagem = custo_embalagem
            st.session_state.tempo_preparo_min = tempo_preparo_min
            st.session_state.custo_hora_mao_obra = custo_hora_mao_obra
            st.session_state.custo_operacional_pct = custo_operacional_pct
            st.session_state.taxas_venda_pct = taxas_venda_pct
            st.session_state.margem_desejada_pct = margem_desejada_pct
            st.session_state.preco_venda_praticado = preco_venda_praticado
            st.session_state.calculated = True

        else:
            st.info("👆 Escolha uma **Receita Modelo** no topo ou adicione seu primeiro ingrediente acima para ver o cálculo completo.")

    with col_label:
        if len(st.session_state.recipe) > 0:
            ref_unit_w = st.session_state.peso_embalagem if st.session_state.peso_embalagem > 0 else st.session_state.weight_final
            num_units = max(1.0, st.session_state.weight_final / ref_unit_w) if ref_unit_w > 0 else 1.0

            fb = calculate_financial_breakdown(
                recipe_ingredients=st.session_state.recipe,
                packaging_cost=st.session_state.custo_embalagem,
                prep_time_min=st.session_state.tempo_preparo_min,
                hourly_rate=st.session_state.custo_hora_mao_obra,
                overhead_pct=st.session_state.custo_operacional_pct,
                target_margin_pct=st.session_state.margem_desejada_pct,
                sales_fees_pct=st.session_state.taxas_venda_pct,
                num_units=num_units,
                practiced_price=st.session_state.preco_venda_praticado
            )

            st.markdown("### 📊 Resultado & Faixas de Preço")
            st.caption(f"Rendimento considerado: **{num_units:.0f} unidade(s)** de **{ref_unit_w:.0f}g** cada.")

            # --- 3 FAIXAS DE PREÇO (COMBATE O MEDO DE COBRAR) ---
            t_c1, t_c2, t_c3 = st.columns(3)
            with t_c1:
                st.markdown(f"""
                <div class="tier-card min-tier">
                    <div class="tier-title">🛡️ Preço Mínimo</div>
                    <div class="tier-price">R$ {fb['min_unit_price']:.2f}</div>
                    <div class="tier-desc">Empate (Zero prejuízo)</div>
                </div>
                """, unsafe_allow_html=True)
            with t_c2:
                st.markdown(f"""
                <div class="tier-card ideal-tier">
                    <div class="tier-title">🎯 Preço Ideal</div>
                    <div class="tier-price">R$ {fb['suggested_unit_price']:.2f}</div>
                    <div class="tier-desc">Lucro de {st.session_state.margem_desejada_pct:.0f}% (R$ {fb['sug_net_profit']:.2f}/un)</div>
                </div>
                """, unsafe_allow_html=True)
            with t_c3:
                st.markdown(f"""
                <div class="tier-card prem-tier">
                    <div class="tier-title">✨ Preço Gourmet</div>
                    <div class="tier-price">R$ {fb['premium_unit_price']:.2f}</div>
                    <div class="tier-desc">Linha presente / especial</div>
                </div>
                """, unsafe_allow_html=True)

            # Diagnóstico claro do preço praticado
            if st.session_state.preco_venda_praticado > 0:
                diff_ideal = st.session_state.preco_venda_praticado - fb["suggested_unit_price"]
                if fb["prac_net_profit"] <= 0:
                    st.error(
                        f"🚨 **Cuidado! Prejuízo detectado:** Cobrando **R$ {st.session_state.preco_venda_praticado:.2f}**, "
                        f"você perde **R$ {abs(fb['prac_net_profit']):.2f}** em cada unidade vendida. "
                        f"O mínimo para não pagar para trabalhar é **R$ {fb['min_unit_price']:.2f}**."
                    )
                elif diff_ideal < -0.05:
                    st.warning(
                        f"⚠️ **Atenção à margem:** Vendendo a **R$ {st.session_state.preco_venda_praticado:.2f}**, "
                        f"sobram **R$ {fb['prac_net_profit']:.2f}/un ({fb['prac_net_margin_pct']:.1f}%)**, "
                        f"mas você está cobrando **R$ {abs(diff_ideal):.2f} a menos** que o preço ideal para sua meta."
                    )
                else:
                    st.success(
                        f"✅ **Preço Saudável!** Vendendo a **R$ {st.session_state.preco_venda_praticado:.2f}**, "
                        f"você paga todos os seus custos (incluindo sua hora e gás/luz) e lucra **R$ {fb['prac_net_profit']:.2f} livres por unidade ({fb['prac_net_margin_pct']:.1f}%)**!"
                    )

            m_col1, m_col2 = st.columns(2)
            with m_col1:
                st.markdown(f"""
                <div class="metric-card-fin primary">
                    <div class="fin-label">Ingredientes / Unidade</div>
                    <div class="fin-val">R$ {fb['unit_cmv']:.2f}</div>
                    <div class="fin-sub">Receita toda: R$ {fb['total_cmv']:.2f}</div>
                </div>
                """, unsafe_allow_html=True)

            with m_col2:
                st.markdown(f"""
                <div class="metric-card-fin warning">
                    <div class="fin-label">Custo Completo / Unidade</div>
                    <div class="fin-val">R$ {fb['unit_total_cost']:.2f}</div>
                    <div class="fin-sub">Lote todo: R$ {fb['total_production_cost']:.2f}</div>
                </div>
                """, unsafe_allow_html=True)

            m_col3, m_col4 = st.columns(2)
            with m_col3:
                st.markdown(f"""
                <div class="metric-card-fin success">
                    <div class="fin-label">Venda do Lote ({num_units:.0f} un)</div>
                    <div class="fin-val">R$ {fb['prac_unit_price'] * num_units:.2f}</div>
                    <div class="fin-sub">A R$ {fb['prac_unit_price']:.2f} cada unidade</div>
                </div>
                """, unsafe_allow_html=True)

            with m_col4:
                lucro_color = "success" if fb['prac_net_profit'] > 0 else "danger"
                st.markdown(f"""
                <div class="metric-card-fin {lucro_color}">
                    <div class="fin-label">Lucro Livre no Bolso</div>
                    <div class="fin-val">R$ {fb['prac_net_profit']:.2f}/un</div>
                    <div class="fin-sub">Lote todo: R$ {fb['prac_net_profit'] * num_units:.2f} ({fb['prac_net_margin_pct']:.1f}%)</div>
                </div>
                """, unsafe_allow_html=True)

            st.markdown("---")
            st.markdown(f"##### 🍰 Para onde vai cada centavo de R$ {fb['prac_unit_price']:.2f}?")

            bd = fb["breakdown_pct"]
            st.markdown(f"""
            - 🛒 **Ingredientes (Matéria-prima):** {bd['cmv']}% (`R$ {fb['unit_cmv']:.2f}`)
            - 📦 **Embalagem (Pote, forminha, fita):** {bd['packaging']}% (`R$ {fb['unit_packaging']:.2f}`)
            - 👩‍🍳 **Seu Trabalho ({st.session_state.tempo_preparo_min:.0f} min no lote):** {bd['labor']}% (`R$ {fb['unit_labor']:.2f}`)
            - 🔥 **Contas Fixas (Gás, luz, água, MEI):** {bd['overhead']}% (`R$ {fb['unit_overhead']:.2f}`)
            - 💳 **Taxas de Venda (Maquininha / iFood):** {bd['fees']}% (`R$ {fb['prac_sales_fee_val']:.2f}`)
            - 💰 **Seu Lucro Livre:** **{bd['profit']}%** (`R$ {fb['prac_net_profit']:.2f}`)
            """, unsafe_allow_html=True)

            st.markdown("---")

            # --- SIMULADORES DE DECISÃO DA CONFEITEIRA (FASE 2) ---
            with st.expander("🎯 Meta do Mês: Quantas unidades preciso vender para tirar meu salário?", expanded=False):
                meta_lucro_mes = st.number_input(
                    "Quanto você quer colocar de LUCRO LIVRE no bolso com este produto no mês? (R$):",
                    min_value=100.0,
                    value=2000.0,
                    step=100.0,
                    key="sim_meta_lucro_mes"
                )
                dias_trab_mes = st.slider(
                    "Dias de venda no mês:",
                    min_value=4, max_value=30, value=24, step=1,
                    key="sim_dias_trab_mes"
                )
                goal_res = calculate_monthly_sales_goal(
                    monthly_profit_goal=meta_lucro_mes,
                    unit_net_profit=fb["prac_net_profit"],
                    unit_price=fb["prac_unit_price"],
                    batch_units=num_units,
                    working_days_per_month=dias_trab_mes
                )
                if not goal_res["achievable"]:
                    st.error("⚠️ Com o preço atual, o lucro unitário está zerado ou negativo. Aumente o preço de venda acima para simular sua meta mensal!")
                else:
                    st.success(
                        f"🚀 Para colocar **R$ {meta_lucro_mes:.2f} livres no bolso**, você precisa vender:\n\n"
                        f"- **{goal_res['units_per_month']} unidades no mês** (~**{goal_res['units_per_day']} unidades por dia**)\n"
                        f"- Isso equivale a produzir **{goal_res['batches_per_month']} receitas (fornadas)** no mês\n"
                        f"- Faturamento bruto total: **R$ {goal_res['gross_revenue']:.2f}/mês**"
                    )

            with st.expander("🤝 Encomenda de Festa / Atacado: Posso dar desconto sem ter prejuízo?", expanded=False):
                c_bk1, c_bk2 = st.columns(2)
                qtd_encomenda = c_bk1.number_input("Qtd. da encomenda (un.):", min_value=5, value=50, step=5, key="sim_bulk_qty")
                desc_encomenda = c_bk2.slider("Desconto para o cliente (%):", min_value=0, max_value=40, value=10, step=2, key="sim_bulk_disc")
                bulk_res = calculate_bulk_discount_simulation(
                    unit_total_cost=fb["unit_total_cost"],
                    sales_fees_pct=st.session_state.taxas_venda_pct,
                    base_unit_price=fb["prac_unit_price"],
                    discount_pct=desc_encomenda,
                    order_qty=qtd_encomenda
                )
                if bulk_res["is_profitable"]:
                    st.info(
                        f"✅ **Encomenda de {qtd_encomenda} un. com {desc_encomenda}% de desconto:**\n\n"
                        f"- Novo preço por unidade: **R$ {bulk_res['discounted_unit_price']:.2f}** (de R$ {fb['prac_unit_price']:.2f})\n"
                        f"- Valor total a cobrar do cliente: **R$ {bulk_res['total_order_revenue']:.2f}**\n"
                        f"- **Seu Lucro Livre nesta encomenda:** **R$ {bulk_res['total_order_net_profit']:.2f}** (`R$ {bulk_res['unit_net_profit']:.2f}/un` · margem de `{bulk_res['margin_after_discount_pct']:.1f}%`)"
                    )
                else:
                    st.error(
                        f"🚨 **CUIDADO! Desconto de {desc_encomenda}% dá PREJUÍZO!**\n\n"
                        f"- O preço cairia para **R$ {bulk_res['discounted_unit_price']:.2f}/un**, que é menor que seu custo + taxas (**R$ {fb[' min_unit_price' if ' min_unit_price' in fb else 'min_unit_price']:.2f}/un**).\n"
                        f"- Prejuízo total no pedido: **R$ {bulk_res['total_order_net_profit']:.2f}**. Reduza o desconto!"
                    )

            st.markdown("---")

            # --- EXPORTAÇÃO GRATUITA DE PDF DA FICHA TÉCNICA DE PRODUÇÃO & SALVAMENTO ---
            ft_pdf_bytes = build_ficha_tecnica_pdf_bytes(
                prod_name=st.session_state.nome_produto or "Minha Receita",
                recipe_ingredients=st.session_state.recipe,
                fb=fb,
                num_units=num_units,
                unit_weight_g=ref_weight,
                prep_time_min=st.session_state.tempo_preparo_min,
                hourly_rate=st.session_state.custo_hora_mao_obra,
                overhead_pct=st.session_state.custo_operacional_pct,
                sales_fees_pct=st.session_state.taxas_venda_pct
            )
            safe_ft_filename = "".join(c if c.isalnum() else "_" for c in (st.session_state.nome_produto or "ficha_tecnica")).strip("_").lower() or "ficha_tecnica"

            st.download_button(
                label="📄 Baixar PDF da Ficha Técnica (Cozinha & Custos — Grátis)",
                data=ft_pdf_bytes,
                file_name=f"ficha_tecnica_{safe_ft_filename}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
                key="btn_dl_ficha_tecnica_pdf"
            )

            col_act1, col_act2 = st.columns(2)
            with col_act1:
                if st.button("💾 Salvar Ficha no Sistema", type="secondary", use_container_width=True):
                    st.session_state.show_save_dialog = True
            with col_act2:
                if st.button("🏷️ Gerar Rótulo ANVISA", type="secondary", use_container_width=True):
                    st.session_state.selected_page = "Tabela Nutricional & ANVISA"
                    st.rerun()

            if st.session_state.get("show_save_dialog", False):
                st.markdown("---")
                plan_st = get_user_plan_status(st.session_state.username, db_lock)
                st.markdown(f"##### 💾 Salvar na Minha Lista ({plan_st['plan_label']})")
                name_save = st.text_input("Nome da Receita/Produto:", value=st.session_state.nome_produto, placeholder="Ex: Brigadeiro Gourmet Tradicional", key="save_fin_name")
                c_sv1, c_sv2 = st.columns(2)
                if c_sv1.button("✅ Confirmar e Salvar", type="primary", use_container_width=True):
                    if name_save.strip():
                        can_sv, msg_sv = can_user_save_recipe(st.session_state.username, name_save.strip(), db_lock)
                        if not can_sv:
                            st.warning(f"🔒 {msg_sv}")
                            if st.button("💎 Liberar Fichas Ilimitadas (Plano Pro)", key="btn_up_pro_save", type="primary", use_container_width=True):
                                st.session_state.selected_page = "Meu Perfil"
                                st.rerun()
                        else:
                            st.session_state.nome_produto = name_save.strip()
                            if save_recipe(name_save.strip(), db_lock):
                                st.toast(f"Ficha Técnica '{name_save.strip()}' salva com sucesso!")
                                st.session_state.show_save_dialog = False
                                st.rerun()
                            else:
                                st.error("Erro ao salvar ficha técnica no banco de dados.")
                    else:
                        st.error("Digite um nome para identificar sua receita.")
                if c_sv2.button("Cancelar", type="secondary", use_container_width=True):
                    st.session_state.show_save_dialog = False
                    st.rerun()
        else:
            st.markdown("### 📊 Resultado & Faixas de Preço")
            st.info("Assim que você escolher uma **Receita Modelo** acima ou adicionar seus ingredientes ao lado, você verá aqui:\n\n- 🛡️ **Preço Mínimo** (para nunca ter prejuízo)\n- 🎯 **Preço Ideal Sugerido** (com seu lucro)\n- ✨ **Preço Gourmet / Premium**\n- 👩‍🍳 Quanto custa seu tempo, embalagem e gás em cada unidade!")

# ==============================================================================
# TAB 2: TABELA NUTRICIONAL & ROTULAGEM ANVISA (PRODUTO SECUNDÁRIO)
# ==============================================================================
if st.session_state.selected_page == "Tabela Nutricional & ANVISA":
    st.markdown('<h1 class="main-title">Tabela Nutricional & ANVISA</h1>', unsafe_allow_html=True)
    st.markdown('<p class="subtitle">Gerador de Rótulos oficiais (RDC 429 / IN 75), Lupas frontais e Alérgenos a partir dos dados da sua Ficha Técnica.</p>', unsafe_allow_html=True)

    with st.expander("❓ Dúvida rápida: meu produto artesanal precisa de Tabela Nutricional ANVISA?"):
        st.markdown("""
        - **Quando é OBRIGATÓRIO (RDC 429/2020):** quando o alimento é **embalado na ausência do cliente** e vendido pronto para levar (ex: exposto em prateleiras de mercados, padarias, empórios, cafeterias parceiras ou feiras).
        - **Quando costuma ser DISPENSADO:** encomendas feitas sob medida e entregues diretamente ao consumidor final (ex: bolo de festa encomendado pelo WhatsApp) ou produtos vendidos e pesados na presença do cliente.
        - **Segurança Técnica sem custo de laboratório:** a legislação da ANVISA permite calcular a tabela nutricional a partir de tabelas oficiais reconhecidas (**TBCA da USP** e **TACO da UNICAMP**), exatamente as fontes utilizadas pelo **Rotulei App**!
        """)
    
    col_input, col_label = st.columns([1.1, 0.9])
    
    with col_input:
        st.markdown("### 📋 1. Parametrização do Rótulo ANVISA")
        
        if len(st.session_state.recipe) == 0:
            st.warning("Nenhum insumo encontrado na Ficha Técnica ativa. Vá para a aba **Ficha Técnica & Precificação** e monte sua receita primeiro.")
            if st.button("⬅️ Ir para Ficha Técnica & Precificação", type="primary", use_container_width=True):
                st.session_state.selected_page = "Ficha Técnica & Precificação"
                st.rerun()
        else:
            nome_prod_display = st.session_state.nome_produto if st.session_state.nome_produto else "Produto Sem Nome"
            st.info(f"**Produto Selecionado:** {nome_prod_display} ({len(st.session_state.recipe)} insumos adicionados)")
            
            with st.container():
                col_rend1, col_rend2, col_rend3 = st.columns(3)
                
                product_type_options = ["Sólido ou Semissólido", "Líquido"]
                product_type_index = product_type_options.index(st.session_state.product_type) if st.session_state.product_type in product_type_options else 0
                product_type = col_rend1.selectbox(
                    "Tipo de Alimento:",
                    options=product_type_options,
                    index=product_type_index,
                    key="anvisa_product_type_widget"
                )
                
                weight_final = col_rend2.number_input(
                    "Rendimento Lote (g/ml):",
                    min_value=1.0,
                    value=float(max(st.session_state.weight_final, 1.0)),
                    key="anvisa_weight_final_widget"
                )
                
                peso_embalagem = col_rend3.number_input(
                    "Peso Líquido Embalagem (g/ml):",
                    min_value=0.0,
                    value=float(st.session_state.peso_embalagem),
                    step=10.0,
                    key="anvisa_peso_embalagem_widget"
                )
                
                col_rend4, col_rend5 = st.columns(2)
                portion_size = col_rend4.number_input(
                    "Tamanho da Porção (g/ml):",
                    min_value=1.0,
                    value=float(st.session_state.portion_size),
                    step=5.0,
                    key="anvisa_portion_size_widget"
                )
                
                case_measure = col_rend5.text_input(
                    "Medida Caseira:",
                    placeholder="Ex: 1 unidade, 2 fatias...",
                    value=st.session_state.case_measure,
                    key="anvisa_case_measure_widget"
                )
                
                st.markdown("##### 🏷️ Declarações Obrigatórias e Alérgenos")
                col_dec1, col_dec2 = st.columns(2)
                
                gluten_options = ["NÃO CONTÉM GLÚTEN", "CONTÉM GLÚTEN"]
                gluten_index = gluten_options.index(st.session_state.gluten_opt) if st.session_state.gluten_opt in gluten_options else 0
                gluten_opt = col_dec1.radio("Glúten:", options=gluten_options, index=gluten_index, key="anvisa_gluten_opt_widget")
                
                lactose_options = ["NÃO CONTÉM LACTOSE", "CONTÉM LACTOSE"]
                lactose_index = lactose_options.index(st.session_state.lactose_opt) if st.session_state.lactose_opt in lactose_options else 0
                lactose_opt = col_dec2.radio("Lactose:", options=lactose_options, index=lactose_index, key="anvisa_lactose_opt_widget")
                
                allergens_list = [
                    "Trigo", "Centeio", "Cevada", "Aveia", "Crustáceos", "Ovos", "Peixes", 
                    "Amendoim", "Soja", "Leite", "Amêndoa", "Avelãs", "Castanha-de-caju", 
                    "Castanha-do-pará", "Macadâmias", "Nozes", "Pecãs", "Pistaches", "Pinoli"
                ]
                selected_allergens_direct = st.multiselect("1. CONTÉM (Ingredientes alérgenos diretos):", options=allergens_list, default=st.session_state.allergens_direct, key="anvisa_allergens_direct_widget")
                selected_allergens_deriv = st.multiselect("2. CONTÉM DERIVADOS DE:", options=allergens_list, default=st.session_state.allergens_deriv, key="anvisa_allergens_deriv_widget")
                selected_allergens_may_contain = st.multiselect("3. PODE CONTER (Cruzada/traços):", options=allergens_list, default=st.session_state.allergens_may_contain, key="anvisa_allergens_may_contain_widget")
                
                if st.button("⚡ Atualizar Tabela & Lupas ANVISA", type="primary", use_container_width=True):
                    st.session_state.weight_final = weight_final
                    st.session_state.portion_size = portion_size
                    st.session_state.case_measure = case_measure
                    st.session_state.gluten_opt = gluten_opt
                    st.session_state.lactose_opt = lactose_opt
                    st.session_state.allergens_direct = selected_allergens_direct
                    st.session_state.allergens_deriv = selected_allergens_deriv
                    st.session_state.allergens_may_contain = selected_allergens_may_contain
                    st.session_state.product_type = product_type
                    st.session_state.peso_embalagem = peso_embalagem
                    st.session_state.calculated = True
                    st.toast("Tabela ANVISA atualizada com sucesso!")
                    st.rerun()

    # --- PROCESSAMENTO DOS TOTAIS DA RECEITA PARA ROTULAGEM ---
    if len(st.session_state.recipe) > 0:
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

        # 1. Somar nutrientes totais
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
            
        totals_100g = {}
        for key in raw_totals.keys():
            totals_100g[key] = (raw_totals[key] / weight_final) * 100.0
            
        totals_portion = {}
        for key in raw_totals.keys():
            totals_portion[key] = (totals_100g[key] * portion_size) / 100.0
            
        vd_percents = {}
        for key, vdr_val in VDR.items():
            vd_percents[key] = round((totals_portion[key] / vdr_val) * 100)
            
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

        display_100g = {}
        display_portion = {}
        for key in raw_totals.keys():
            display_100g[key] = round_anvisa(totals_100g[key], key)
            display_portion[key] = round_anvisa(totals_portion[key], key)

        with col_label:
            st.markdown("### Pré-visualização do Rótulo")
            if st.session_state.nome_produto:
                safe_nome_produto = html.escape(st.session_state.nome_produto)
                st.markdown(f"##### Produto: **{safe_nome_produto}**")
            
            st.divider()
            
            if alto_acucar or alto_gordura or alto_sodio:
                lupa_content_html = get_lupa_html(alto_acucar, alto_gordura, alto_sodio)
            else:
                lupa_content_html = '<div style="height: 180px;"></div>'

            ref_weight = peso_embalagem if peso_embalagem > 0.0 else weight_final
            n_raw = ref_weight / portion_size
            if n_raw < 1.5:
                n_porcoes_str = "Cerca de 1"
            elif n_raw <= 10.0:
                val_rounded = round(n_raw * 2) / 2
                n_porcoes_str = f"Cerca de {str(val_rounded).replace('.', ',')}"
                if n_porcoes_str.endswith(',0'):
                    n_porcoes_str = n_porcoes_str[:-2]
            else:
                n_porcoes_str = f"Cerca de {int(round(n_raw))}"
            
            safe_case_measure = html.escape(case_measure)
            
            combined_preview_html = f"""
            <div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 16px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.01); max-width: 440px; margin: 0 auto; box-sizing: border-box;">
                <div class="watermarked-preview" style="max-width: 420px; min-height: 180px; display: flex; align-items: center; justify-content: center; margin: 10px auto; position: relative; box-sizing: border-box;">
                    {lupa_content_html}
                </div>
                <p style='text-align: center; font-size: 11px; color: gray; line-height: 1.2; margin-top: 5px; margin-bottom: 20px;'>* Os selos de rotulagem frontal (Lupa) são gerados automaticamente caso o produto atinja os limites da RDC 429/2020 por 100g (Açúcar Adicionado &ge; 15g, Gordura Saturada &ge; 6g, Sódio &ge; 600mg).</p>
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
            </div>
            """
            st.markdown(combined_preview_html, unsafe_allow_html=True)
            st.divider()

            lista_base = gerar_lista_ingredientes_rotulo(st.session_state.recipe)
            if (
                "lista_ingredientes_editavel" not in st.session_state
                or st.session_state.get("_recipe_hash") != hash(str(st.session_state.recipe))
            ):
                st.session_state["lista_ingredientes_editavel"] = lista_base
                st.session_state["_recipe_hash"] = hash(str(st.session_state.recipe))

            st.markdown("""
            <div style="background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%); border: 2px solid #22c55e; border-radius: 14px; padding: 16px 20px 4px 20px; margin: 12px 0 4px 0;">
                <div style="display:flex; align-items:center; gap:10px; margin-bottom:6px;">
                    <span style="font-size:1.25rem;">✏️</span>
                    <strong style="font-size:1rem; color:#15803d;">Lista de Ingredientes</strong>
                    <span style="background:#22c55e; color:#fff; font-size:0.68rem; font-weight:700; padding:2px 9px; border-radius:20px; text-transform:uppercase;">Editável</span>
                </div>
                <p style="margin:0 0 10px 0; font-size:0.82rem; color:#166534;">Nomes convertidos para o padrão comercial ANVISA (maior para o menor peso).</p>
            </div>
            """, unsafe_allow_html=True)

            lista_editada = st.text_area("Lista de Ingredientes:", value=st.session_state["lista_ingredientes_editavel"], height=120, key="lista_ing_anvisa_widget", label_visibility="collapsed")
            st.session_state["lista_ingredientes_editavel"] = lista_editada
            ing_text = lista_editada.rstrip(".").strip()
            
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
            
            st.markdown("##### Textos Legais (Cópia Rápida)")
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
            
            # --- GERAÇÃO DE PDF EM MEMÓRIA E DOWNLOAD (FUNÇÃO CENTRALIZADA & ATÔMICA) ---
            ing_text_pdf = st.session_state.get("lista_ingredientes_editavel", ing_text)
            pdf_data = build_anvisa_pdf_bytes(
                prod_name=st.session_state.nome_produto,
                weight_final=weight_final,
                peso_embalagem=peso_embalagem,
                col_unit=col_unit,
                n_porcoes_str=n_porcoes_str,
                portion_size=portion_size,
                safe_case_measure=safe_case_measure,
                col_100_label=col_100_label,
                col_portion_label=col_portion_label,
                display_100g=display_100g,
                display_portion=display_portion,
                vd_percents=vd_percents,
                alto_acucar=alto_acucar,
                alto_gordura=alto_gordura,
                alto_sodio=alto_sodio,
                ing_text_pdf=ing_text_pdf,
                gluten_opt=gluten_opt,
                lactose_opt=lactose_opt,
                alergenicos_text=alergenicos_text
            )
            
            from utils.db import get_user_credits_cached
            current_user_pdf = get_user_credits_cached(st.session_state.username)
            is_admin_pdf = current_user_pdf.get("is_admin", False) if current_user_pdf else False
            creditos_disponiveis = current_user_pdf.get("creditos_disponiveis", 0) if current_user_pdf else 0
            
            col_pdf, col_save = st.columns(2)
            with col_pdf:
                if not is_admin_pdf and creditos_disponiveis <= 0:
                    st.warning("Você não possui créditos de impressão disponíveis. Adquira um pacote para liberar o PDF oficial:")
                    packages = [
                        {"credits": 1, "price": 19.90, "name": "Avulso (1 Rótulo)"},
                        {"credits": 5, "price": 49.90, "name": "Empreendedor (5 Rótulos)"},
                        {"credits": 15, "price": 99.90, "name": "Consultor / Nutri (15 Rótulos)"}
                    ]
                    access_token = get_secrets_key("MERCADOPAGO_ACCESS_TOKEN", "")
                    back_url = get_secrets_key("APP_BASE_URL", "https://rotuleiapp.streamlit.app/")
                    from utils.webhook_handler import create_mercado_pago_preference
                    selected_pkg = st.selectbox("Selecione um pacote:", options=packages, format_func=lambda x: f"{x['name']} - R$ {x['price']:.2f}", key="pdf_buy_credits_select")
                    if access_token:
                        init_point = create_mercado_pago_preference(username=st.session_state.username, email=current_user_pdf.get("email", "") if current_user_pdf else "", credits=selected_pkg['credits'], price=selected_pkg['price'], access_token=access_token, back_url=back_url)
                        if init_point:
                            st.link_button(f"💳 Comprar (R$ {selected_pkg['price']:.2f})", init_point, type="primary", use_container_width=True)
                else:
                    if pdf_data and len(pdf_data) > 100:
                        st.download_button(
                            label="📄 Baixar PDF do Rótulo Oficial",
                            data=pdf_data,
                            file_name=f"rotulo_anvisa_{st.session_state.username}.pdf",
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True,
                            on_click=trigger_consume_credit
                        )

# ==============================================================================
# TAB 3: MINHAS FICHAS TÉCNICAS SALVAS
# ==============================================================================
if st.session_state.selected_page in ("Minhas Fichas Técnicas", "Minhas Receitas Salvas"):
    st.markdown('<h1 class="main-title">Minhas Fichas Técnicas</h1>', unsafe_allow_html=True)
    st.markdown('<p class="subtitle">Consulte, baixe o PDF de produção para a cozinha, edite, duplique ou exclua suas fichas técnicas.</p>', unsafe_allow_html=True)
    
    current_username = st.session_state.get("username", "")
    plan_info_tab3 = get_user_plan_status(current_username, db_lock)
    if plan_info_tab3["is_pro"]:
        st.success(f"💎 **{plan_info_tab3['plan_label']} Ativo:** Você pode salvar fichas técnicas ilimitadas e exportar quantos PDFs de produção desejar.")
    else:
        st.info(
            f"🌱 **{plan_info_tab3['plan_label']}:** Você ainda pode salvar **{plan_info_tab3['remaining_free']}** nova(s) ficha(s) grátis (e editar as já salvas à vontade). "
            "Precisa de fichas ilimitadas para todo o seu cardápio? Ative o **Plano Confeiteira Pro** em **Meu Perfil**!"
        )

    saved_recipes = load_saved_recipes(db_lock, current_username)
    
    if not saved_recipes:
        st.info("Você ainda não salvou nenhuma Ficha Técnica. Monte uma receita na aba **Ficha Técnica & Precificação** e clique em **Salvar Ficha Técnica**!")
        if st.button("➕ Criar Minha Primeira Ficha Técnica", type="primary"):
            st.session_state.selected_page = "Ficha Técnica & Precificação"
            st.rerun()
    else:
        recipes_dict = {r["nome"]: r for r in saved_recipes}
        
        selected_name = st.selectbox(
            "Selecione uma ficha técnica para visualizar ou carregar:",
            options=list(recipes_dict.keys()),
            key="saved_recipes_select"
        )
        
        if selected_name:
            recipe = recipes_dict[selected_name]
            st.caption(f"📅 Última atualização: `{recipe.get('date_saved', 'N/A')}`")
            
            # Calcular resumo financeiro da receita salva
            r_w_final = float(recipe.get("weight_final", 1.0) or 1.0)
            r_p_emb = float(recipe.get("peso_embalagem", 0.0) or 0.0)
            r_ref_w = r_p_emb if r_p_emb > 0 else r_w_final
            r_units = max(1.0, r_w_final / r_ref_w) if r_ref_w > 0 else 1.0
            r_fb = calculate_financial_breakdown(
                recipe_ingredients=recipe.get("ingredients", []),
                packaging_cost=float(recipe.get("custo_embalagem", 0.0) or 0.0),
                prep_time_min=float(recipe.get("tempo_preparo_min", 0.0) or 0.0),
                hourly_rate=float(recipe.get("custo_hora_mao_obra", 0.0) or 0.0),
                overhead_pct=float(recipe.get("custo_operacional_pct", 0.0) or 0.0),
                target_margin_pct=float(recipe.get("margem_desejada_pct", 30.0) or 30.0),
                sales_fees_pct=float(recipe.get("taxas_venda_pct", 0.0) or 0.0),
                num_units=r_units,
                practiced_price=float(recipe.get("preco_venda_praticado", 0.0) or 0.0)
            )

            sc1, sc2, sc3, sc4 = st.columns(4)
            sc1.metric("Rendimento", f"{r_units:.0f} un ({r_ref_w:.0f}g)")
            sc2.metric("Custo Total / un", f"R$ {r_fb['unit_total_cost']:.2f}")
            sc3.metric("Preço Sugerido", f"R$ {r_fb['suggested_unit_price']:.2f}")
            sc4.metric("Lucro Livre / un", f"R$ {r_fb['prac_net_profit']:.2f} ({r_fb['prac_net_margin_pct']:.0f}%)")

            ing_details = []
            for ing in recipe["ingredients"]:
                yf_saved = float(ing.get("yield_factor", 1.0) or 1.0)
                c_kg_saved = float(ing.get("cost_kg", 0.0) or 0.0)
                c_item = calculate_ingredient_cost(float(ing["w"]), c_kg_saved, yf_saved)
                ing_details.append({
                    "Ingrediente": ing["d"],
                    "Quantidade": f"{ing['w']:.1f} g",
                    "Custo R$/kg": f"R$ {c_kg_saved:.2f}",
                    "Custo na Receita": f"R$ {c_item:.2f}"
                })
            
            st.markdown("##### 🛒 Ingredientes da Ficha Técnica:")
            st.table(pd.DataFrame(ing_details))
            
            def _load_recipe_into_session(rec_obj, as_copy=False):
                st.session_state.recipe = [i.copy() for i in rec_obj["ingredients"]]
                st.session_state.weight_final = float(rec_obj.get("weight_final", 100.0) or 100.0)
                st.session_state.portion_size = float(rec_obj.get("portion_size", 60.0) or 60.0)
                st.session_state.case_measure = rec_obj.get("case_measure", "1 unidade")
                st.session_state.gluten_opt = rec_obj.get("gluten_opt", "NÃO CONTÉM GLÚTEN")
                st.session_state.lactose_opt = rec_obj.get("lactose_opt", "NÃO CONTÉM LACTOSE")
                st.session_state.allergens_direct = rec_obj.get("allergens_direct", rec_obj.get("selected_allergens", []))
                st.session_state.allergens_deriv = rec_obj.get("allergens_deriv", [])
                st.session_state.allergens_may_contain = rec_obj.get("allergens_may_contain", [])
                st.session_state.product_type = rec_obj.get("product_type", "Sólido ou Semissólido")
                base_nome = rec_obj.get("nome_produto", "") or rec_obj.get("nome", "")
                st.session_state.nome_produto = (base_nome + " (Cópia)") if as_copy else base_nome
                st.session_state.peso_embalagem = float(rec_obj.get("peso_embalagem", 0.0) or 0.0)
                # Campos financeiros
                st.session_state.custo_embalagem = float(rec_obj.get("custo_embalagem", 0.0) or 0.0)
                st.session_state.tempo_preparo_min = float(rec_obj.get("tempo_preparo_min", 0.0) or 0.0)
                st.session_state.custo_hora_mao_obra = float(rec_obj.get("custo_hora_mao_obra", 0.0) or 0.0)
                st.session_state.custo_operacional_pct = float(rec_obj.get("custo_operacional_pct", 0.0) or 0.0)
                st.session_state.taxas_venda_pct = float(rec_obj.get("taxas_venda_pct", 0.0) or 0.0)
                st.session_state.margem_desejada_pct = float(rec_obj.get("margem_desejada_pct", 30.0) or 30.0)
                st.session_state.preco_venda_praticado = float(rec_obj.get("preco_venda_praticado", 0.0) or 0.0)
                if st.session_state.peso_embalagem > 0:
                    st.session_state.yield_units = max(1, int(round(st.session_state.weight_final / st.session_state.peso_embalagem)))
                st.session_state.calculated = True
                st.session_state.selected_page = "Ficha Técnica & Precificação"

            st.markdown("---")
            saved_ft_pdf = build_ficha_tecnica_pdf_bytes(
                prod_name=recipe.get("nome_produto", "") or selected_name,
                recipe_ingredients=recipe.get("ingredients", []),
                fb=r_fb,
                num_units=r_units,
                unit_weight_g=r_ref_w,
                prep_time_min=float(recipe.get("tempo_preparo_min", 0.0) or 0.0),
                hourly_rate=float(recipe.get("custo_hora_mao_obra", 0.0) or 0.0),
                overhead_pct=float(recipe.get("custo_operacional_pct", 0.0) or 0.0),
                sales_fees_pct=float(recipe.get("taxas_venda_pct", 0.0) or 0.0)
            )
            safe_sv_fname = "".join(c if c.isalnum() else "_" for c in selected_name).strip("_").lower() or "ficha_tecnica"
            st.download_button(
                label=f"📄 Baixar PDF da Ficha Técnica '{selected_name}' (Cozinha & Custos)",
                data=saved_ft_pdf,
                file_name=f"ficha_tecnica_{safe_sv_fname}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
                key="btn_dl_saved_ft_pdf"
            )

            col_load, col_clone, col_del = st.columns(3)
            
            with col_load:
                if st.button("🔌 Abrir na Calculadora de Preço", type="primary", use_container_width=True):
                    _load_recipe_into_session(recipe, as_copy=False)
                    st.toast(f"Ficha Técnica **{selected_name}** carregada!")
                    st.rerun()

            with col_clone:
                if st.button("📄 Duplicar Receita (Criar Cópia)", type="secondary", use_container_width=True):
                    _load_recipe_into_session(recipe, as_copy=True)
                    st.toast("Cópia da ficha técnica pronta para edição!")
                    st.rerun()

            with col_del:
                st.markdown('<div class="danger-button-wrapper"></div>', unsafe_allow_html=True)
                if st.button("🗑️ Excluir Permanentemente", type="secondary", use_container_width=True):
                    if delete_recipe(selected_name, db_lock):
                        st.toast(f"Ficha Técnica **{selected_name}** excluída com sucesso!")
                        st.rerun()

# ==============================================================================
# TAB 2: CADASTRAR NOVO INGREDIENTE
# ==============================================================================
if st.session_state.selected_page == "Cadastrar Novo Ingrediente":
    st.markdown("### Cadastrar Novo Ingrediente")
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
if st.session_state.selected_page == "Meu Perfil":
    st.markdown('### Meu Perfil')
    st.markdown('Edite suas informações cadastrais.')
    
    current_username = st.session_state.username
    all_users = load_users(db_lock)
    user_data = next((u for u in all_users if u['username'] == current_username), None)
    
    if user_data:
        with st.form('form_meu_perfil'):
            edit_email = st.text_input('E-mail:', value=user_data.get('email', ''))
            
            # Formatar CPF atual (se for hash, exibe mascarado por privacidade)
            c = user_data.get('cpf', '')
            from utils.auth import is_hashed_cpf
            if is_hashed_cpf(c):
                cpf_display = "***.***.***-**"
            else:
                c_digits = ''.join(filter(str.isdigit, c))
                if len(c_digits) == 11:
                    cpf_display = f'{c_digits[:3]}.{c_digits[3:6]}.{c_digits[6:9]}-{c_digits[9:]}'
                else:
                    cpf_display = c
                
            edit_cpf = st.text_input('CPF (Edite apenas se for alterar):', value=cpf_display)
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
        
        # --- SEÇÃO DE PLANOS E CRÉDITOS NO PERFIL ---
        st.markdown("---")
        plan_prof = get_user_plan_status(current_username, db_lock)
        st.markdown(f"### 💎 Seu Plano Atual: **{plan_prof['plan_label']}**")
        st.markdown("Desbloqueie **Fichas Técnicas Ilimitadas** para todo o seu cardápio e créditos para exportar PDFs de **Tabelas Nutricionais Oficiais ANVISA**:")
        
        col1, col2, col3 = st.columns(3)
        packages = [
            {"credits": 1, "price": 19.90, "name": "Confeiteira Pro", "desc": "Libera Fichas Técnicas Ilimitadas + 1 Rótulo Oficial ANVISA"},
            {"credits": 5, "price": 49.90, "name": "Empreendedor (Mais Vendido)", "desc": "Fichas Técnicas Ilimitadas + 5 Rótulos Oficiais ANVISA"},
            {"credits": 15, "price": 99.90, "name": "Consultor / Nutri", "desc": "Fichas Técnicas Ilimitadas + 15 Rótulos Oficiais ANVISA"}
        ]
        
        access_token = get_secrets_key("MERCADOPAGO_ACCESS_TOKEN", "")
        back_url = get_secrets_key("APP_BASE_URL", "https://rotuleiapp.streamlit.app/")
        
        from utils.webhook_handler import create_mercado_pago_preference
        
        for idx, col in enumerate([col1, col2, col3]):
            pkg = packages[idx]
            with col:
                st.markdown(f"""
                <div style="background: rgba(255, 255, 255, 0.85); border: 2px solid #059669; border-radius: 12px; padding: 15px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 10px;">
                    <h4 style="margin: 0; color: #111827;">Pacote {pkg['name']}</h4>
                    <h2 style="color: #059669; margin: 10px 0; font-size: 1.8rem;">{pkg['credits']} Créditos</h2>
                    <p style="font-size: 1.2rem; font-weight: bold; margin: 5px 0; color: #374151;">R$ {pkg['price']:.2f}</p>
                    <p style="font-size: 0.8rem; color: #6B7280; min-height: 35px; line-height: 1.2;">{pkg['desc']}</p>
                </div>
                """, unsafe_allow_html=True)
                
                if not access_token:
                    st.warning("Mercado Pago não configurado.")
                else:
                    init_point = create_mercado_pago_preference(
                        username=current_username,
                        email=user_data.get("email", ""),
                        credits=pkg['credits'],
                        price=pkg['price'],
                        access_token=access_token,
                        back_url=back_url
                    )
                    if init_point:
                        st.link_button(f"Comprar {pkg['name']}", init_point, type="primary", use_container_width=True)
                    else:
                        st.error("Erro no checkout.")
    else:
        st.error('Não foi possível carregar os dados do seu perfil.')

# ==============================================================================
# TAB: SUPORTE & AJUDA
# ==============================================================================
if st.session_state.selected_page == "Suporte & Ajuda":

    st.markdown("### 🎧 Suporte & Ajuda")
    st.markdown("Encontrou um problema ou tem uma sugestão? Preencha o formulário abaixo e nossa equipe retornará no seu e-mail.")

    # Carregar e-mail do usuário logado
    all_users_sup = load_users(db_lock)
    user_data_sup = next((u for u in all_users_sup if u['username'] == st.session_state.username), None)
    email_sup = user_data_sup.get('email', '') if user_data_sup else ''

    with st.form('formulario_suporte', clear_on_submit=True):
        st.markdown("**📧 E-mail de contato** *(pré-preenchido com seu cadastro)*")
        st.text_input(
            "E-mail:",
            value=email_sup,
            disabled=True,
            key="suporte_email_display",
            label_visibility="collapsed"
        )

        categoria_sup = st.selectbox(
            "Categoria do chamado:",
            options=[
                "Problema com Créditos / Pagamento",
                "Erro na Geração do Rótulo/PDF",
                "Dúvida Técnica sobre a ANVISA",
                "Sugestão de Melhoria / Feedback",
                "Outros"
            ],
            key="suporte_categoria"
        )

        assunto_sup = st.text_input(
            "Assunto:",
            placeholder="Descreva brevemente o problema ou sua dúvida",
            max_chars=200,
            key="suporte_assunto"
        )

        mensagem_sup = st.text_area(
            "Descrição detalhada:",
            placeholder="Descreva com detalhes o que aconteceu, quais passos você seguiu e qual resultado esperava...",
            height=180,
            max_chars=2000,
            key="suporte_mensagem"
        )

        enviar_sup = st.form_submit_button("📨 Enviar Chamado", type="primary", use_container_width=True)

        if enviar_sup:
            if not assunto_sup.strip():
                st.error("Por favor, preencha o campo Assunto antes de enviar.")
            elif not mensagem_sup.strip():
                st.error("Por favor, preencha a Descrição do problema antes de enviar.")
            else:
                ticket_id = save_ticket_sql(
                    username=st.session_state.username,
                    email=email_sup,
                    categoria=categoria_sup,
                    assunto=assunto_sup.strip(),
                    mensagem=mensagem_sup.strip()
                )
                if ticket_id > 0:
                    st.success(
                        f"✅ **Chamado enviado com sucesso!** Nossa equipe analisará o seu caso e retornará "
                        f"no e-mail **{email_sup}** em breve.\n\n"
                        f"🔖 **Número do protocolo:** `#SUP-{ticket_id:05d}`"
                    )
                else:
                    st.error("Ocorreu um erro ao enviar o chamado. Por favor, tente novamente ou entre em contato por e-mail.")

if is_admin:
    if st.session_state.selected_page == "Painel Administrador":
        st.markdown("### Painel do Administrador")
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
                "Créditos": u.get("creditos_disponiveis", 0),
                "Aceite LGPD": u.get("lgpd_accepted_at", "N/A")
            })
            
        st.markdown("#### 👥 Usuários Cadastrados")
        st.dataframe(pd.DataFrame(users_display), use_container_width=True)
        
        admin_action = st.radio(
            "Selecione uma ação administrativa:",
            ["💰 Ajustar Créditos", "✏️ Editar Usuário", "➕ Criar Usuário", "🗑️ Excluir Usuário"],
            horizontal=True
        )
        
        if admin_action == "💰 Ajustar Créditos":
            st.markdown("##### 💰 Ajuste Rápido de Créditos")
            st.caption("Altere o saldo de créditos de qualquer usuário sem precisar preencher CPF ou outros dados.")

            # Excluir o próprio admin da lista para evitar auto-edição acidental
            non_admin_users = [u for u in users if not u.get("is_admin", False)]
            all_editable = [u["username"] for u in users]

            with st.form("form_ajuste_creditos"):
                cred_username = st.selectbox(
                    "Selecione o usuário:",
                    options=all_editable,
                    key="cred_user_select"
                )

                # Mostra o saldo atual dinamicamente
                user_sel = next((u for u in users if u["username"] == cred_username), None)
                saldo_atual = int(user_sel.get("creditos_disponiveis", 0)) if user_sel else 0
                st.info(f"📊 Saldo atual de **{cred_username}**: **{saldo_atual} crédito(s)**")

                col_cred1, col_cred2 = st.columns(2)
                operacao = col_cred1.radio(
                    "Operação:",
                    ["➕ Adicionar", "➖ Remover", "🔄 Definir valor exato"],
                    key="cred_operacao"
                )
                qtd_creditos = col_cred2.number_input(
                    "Quantidade de créditos:",
                    min_value=0,
                    value=1,
                    step=1,
                    key="cred_qtd"
                )

                submit_cred = st.form_submit_button("💾 Salvar Créditos", type="primary", use_container_width=True)
                if submit_cred and user_sel:
                    if operacao == "➕ Adicionar":
                        novo_saldo = saldo_atual + int(qtd_creditos)
                    elif operacao == "➖ Remover":
                        novo_saldo = max(0, saldo_atual - int(qtd_creditos))
                    else:  # Definir valor exato
                        novo_saldo = int(qtd_creditos)

                    # Preserva todos os dados existentes, altera apenas créditos
                    success, msg = admin_update_user(
                        cred_username,
                        user_sel.get("username", cred_username),
                        user_sel.get("email", ""),
                        user_sel.get("cpf", ""),
                        db_lock,
                        None,           # senha inalterada
                        user_sel.get("is_admin", False),
                        novo_saldo,
                        skip_validation=True  # não valida CPF/e-mail no ajuste de créditos
                    )
                    if success:
                        st.success(
                            f"✅ Créditos de **{cred_username}** atualizados: "
                            f"{saldo_atual} → **{novo_saldo}** crédito(s)."
                        )
                        st.rerun()
                    else:
                        st.error(f"Erro ao atualizar créditos: {msg}")

        elif admin_action == "✏️ Editar Usuário":
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
                        edit_credits = st.number_input("Créditos Disponíveis:", min_value=0, value=int(user_data.get("creditos_disponiveis", 0)), step=1)
                        
                        submit_edit = st.form_submit_button("Confirmar Alterações", type="primary")
                        if submit_edit:
                            success, msg = admin_update_user(
                                selected_username, 
                                edit_name, 
                                edit_email, 
                                edit_cpf, 
                                db_lock,
                                edit_pass if edit_pass.strip() else None, 
                                edit_is_admin,
                                edit_credits
                            )
                            if success:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
                                
        elif admin_action == "➕ Criar Usuário":
            st.markdown("##### 📝 Cadastrar Novo Usuário (Comum ou Admin)")
            with st.form("form_create_user_admin"):
                create_name = st.text_input("Nome de Usuário:", placeholder="Ex: joao_silva")
                create_email = st.text_input("E-mail:", placeholder="Ex: joao@provedor.com")
                create_cpf = st.text_input("CPF (Opcional):", placeholder="Ex: 123.456.789-00")
                create_pass = st.text_input("Senha:", type="password", placeholder="Mínimo 8 caracteres")
                create_is_admin = st.checkbox("Privilégios de Administrador")
                create_credits = st.number_input("Créditos Iniciais:", min_value=0, value=1, step=1)
                
                submit_create = st.form_submit_button("Cadastrar Usuário", type="primary")
                if submit_create:
                    success, msg = register_user(create_name, create_email, create_cpf, create_pass, lgpd_accepted=True, db_lock=db_lock)
                    if success:
                        admin_update_user(create_name, create_name, create_email, create_cpf, db_lock, None, is_admin_val=create_is_admin, creditos_val=create_credits)
                        st.success(f"Usuário '{create_name}' cadastrado com sucesso!")
                        st.rerun()
                    else:
                        st.error(msg)
                        
        elif admin_action == "🗑️ Excluir Usuário":
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
                
                st.markdown('<div class="danger-button-wrapper"></div>', unsafe_allow_html=True)
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

        # ── SEÇÃO DE CHAMADOS DE SUPORTE (Admin) ──────────────────────────────
        st.markdown("---")
        st.markdown("#### 🎧 Chamados de Suporte")

        filtro_status = st.radio(
            "Filtrar por status:",
            ["Todos", "Aberto", "Em Análise", "Resolvido"],
            horizontal=True,
            key="admin_ticket_filtro"
        )
        tickets = load_tickets_sql(None if filtro_status == "Todos" else filtro_status)

        if not tickets:
            st.info("Nenhum chamado encontrado para o filtro selecionado.")
        else:
            st.markdown(f"**{len(tickets)} chamado(s) encontrado(s):**")
            for t in tickets:
                criado = str(t.get('criado_em', ''))[:16]
                status_cor = {"Aberto": "🔴", "Em Análise": "🟡", "Resolvido": "🟢"}.get(t.get('status', ''), "⚪")
                with st.expander(
                    f"{status_cor} **#SUP-{t['id']:05d}** | {t.get('categoria','—')} | "
                    f"{t.get('username','—')} | {criado}"
                ):
                    st.markdown(f"**E-mail:** {t.get('email','—')}")
                    st.markdown(f"**Assunto:** {t.get('assunto','—')}")
                    st.markdown(f"**Mensagem:**")
                    st.text_area(
                        "",
                        value=t.get('mensagem', ''),
                        height=120,
                        disabled=True,
                        key=f"ticket_msg_{t['id']}"
                    )
                    novo_status = st.selectbox(
                        "Alterar status:",
                        ["Aberto", "Em Análise", "Resolvido"],
                        index=["Aberto", "Em Análise", "Resolvido"].index(t.get('status', 'Aberto'))
                            if t.get('status', 'Aberto') in ["Aberto", "Em Análise", "Resolvido"] else 0,
                        key=f"ticket_status_{t['id']}"
                    )
                    if st.button("Salvar Status", key=f"ticket_save_{t['id']}"):
                        if update_ticket_status_sql(t['id'], novo_status):
                            st.success(f"Status do chamado #SUP-{t['id']:05d} atualizado para '{novo_status}'.")
                            st.rerun()
                        else:
                            st.error("Erro ao atualizar o status. Tente novamente.")


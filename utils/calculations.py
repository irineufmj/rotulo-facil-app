from decimal import Decimal, ROUND_HALF_UP

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

NUTRIENT_KEY_MAPPING = {
    "Energia (kcal)": ["Energia (kcal)"],
    "Carboidrato total (g)": ["Carboidrato total (g)", "Carboidrato disponível (g)", "Carboidrato disponí\xadvel (g)"],
    "Açúcares adicionados (g)": ["Açúcares adicionados (g)", "Açúcar de adição (g)", "Açúcar de adi\u00e7\u00e3o (g)", "Acar de adio (g)"],
    "Açúcares totais (g)": ["Açúcares totais (g)", "Açúcares totais", "Açúcar de adição (g)", "Açúcar de adi\u00e7\u00e3o (g)", "Acar de adio (g)"],
    "Proteína (g)": ["Proteína (g)", "Prote\u00edna (g)", "Protena (g)"],
    "Lipídios (g)": ["Lipídios (g)", "Lip\u00eddios (g)", "Lipdios (g)"],
    "Gorduras saturadas (g)": ["Gorduras saturadas (g)", "Ácidos graxos saturados (g)", "\u00c1cidos graxos saturados (g)", "cidos graxos saturados (g)"],
    "Gorduras trans (g)": ["Gorduras trans (g)", "Ácidos graxos trans (g)", "\u00c1cidos graxos trans (g)", "cidos graxos trans (g)"],
    "Fibra alimentar (g)": ["Fibra alimentar (g)"],
    "Sódio (mg)": ["Sódio (mg)", "S\u00f3dio (mg)", "Sdio (mg)"]
}

def get_num_val(nutrients_dict, key, food_desc=""):
    candidates = NUTRIENT_KEY_MAPPING.get(key, [key])
    val = None
    
    for cand in candidates:
        if cand in nutrients_dict:
            val = nutrients_dict[cand]
            break
            
    if val is None and key in ["Açúcares adicionados (g)", "Açúcares totais (g)"] and food_desc:
        desc_lower = food_desc.lower()
        is_sugar_product = (
            "açúcar" in desc_lower or 
            "acucar" in desc_lower or 
            "melaço" in desc_lower or 
            "melaco" in desc_lower or 
            desc_lower == "mel" or 
            desc_lower.startswith("mel ") or 
            desc_lower.startswith("mel,")
        )
        if is_sugar_product:
            val = get_num_val(nutrients_dict, "Carboidrato total (g)")
            
    if val is None:
        return 0.0
        
    if isinstance(val, (int, float)):
        return float(val)
        
    if isinstance(val, str):
        val_clean = val.strip().lower()
        if val_clean in ["tr", "nd", "na", "", "-", "n.d."]:
            return 0.0
        try:
            return float(val_clean.replace(',', '.'))
        except ValueError:
            return 0.0
            
    return 0.0

def round_anvisa(value, nutrient_name):
    if value is None:
        return "0"
    
    def dec_round(val, decs):
        d = Decimal(f"{val:.10f}")
        prec = Decimal('1') if decs == 0 else Decimal('.' + '0' * decs)
        return float(d.quantize(prec, rounding=ROUND_HALF_UP))
    
    if nutrient_name == "Energia (kcal)":
        return f"{int(dec_round(value, 0))}"
        
    if nutrient_name == "Sódio (mg)":
        if value <= 5.0:
            return "0"
        return f"{int(dec_round(value, 0))}"
        
    if nutrient_name == "Gorduras trans (g)":
        if value <= 0.2:
            return "0"
        res = dec_round(value, 1)
        if res.is_integer():
            return f"{int(res)}"
        return f"{res}".replace('.', ',')

    if value <= 0.5:
        return "0"
    elif value < 10.0:
        res = dec_round(value, 1)
        if res.is_integer():
            return f"{int(res)}"
        return f"{res}".replace('.', ',')
    else:
        return f"{int(dec_round(value, 0))}"


# ==============================================================================
# ENGENHARIA FINANCEIRA DE ALIMENTOS & PRECIFICAÇÃO DE PRODUTOS
# ==============================================================================

def calculate_ingredient_cost(weight_g: float, cost_kg: float, yield_factor: float = 1.0) -> float:
    """
    Calcula o custo de um ingrediente considerando o peso (g), custo por kg (R$/kg)
    e o Fator de Correção / Rendimento (yield_factor, padrão 1.0 = sem desperdício).
    Fator de Correção (FC) = Peso Bruto / Peso Limpo. Se FC > 1.0, o custo efetivo aumenta.
    """
    if weight_g <= 0 or cost_kg <= 0:
        return 0.0
    yf = max(0.01, float(yield_factor))
    # Peso Bruto Efetivo = weight_g * yf
    effective_weight_kg = (weight_g * yf) / 1000.0
    return float(effective_weight_kg * cost_kg)


def calculate_cmv(ingredients: list) -> float:
    """
    Calcula o CMV (Custo de Mercadoria Vendida) Total dos Ingredientes da receita.
    """
    total = 0.0
    for ing in ingredients:
        w = float(ing.get("w", 0.0))
        c_kg = float(ing.get("cost_kg", 0.0))
        yf = float(ing.get("yield_factor", 1.0))
        total += calculate_ingredient_cost(w, c_kg, yf)
    return total


def calculate_financial_breakdown(
    recipe_ingredients: list,
    packaging_cost: float = 0.0,
    prep_time_min: float = 0.0,
    hourly_rate: float = 0.0,
    overhead_pct: float = 0.0,
    target_margin_pct: float = 30.0,
    sales_fees_pct: float = 0.0,
    num_units: float = 1.0,
    practiced_price: float = 0.0
) -> dict:
    """
    Calcula a ficha técnica financeira completa do produto:
    - CMV Total e CMV Unitário
    - Custo de Embalagem por Unidade
    - Custo de Mão de Obra por Lote e por Unidade
    - Custos Operacionais Indiretos (Overhead %)
    - Custo Total de Produção por Lote e por Unidade
    - Preço de Venda Sugerido (baseado na Margem de Lucro Desejada e Taxas de Venda)
    - Lucro Líquido Real e Margem Líquida Real (para Preço Sugerido e para Preço Praticado)
    """
    n_units = max(1.0, float(num_units))
    
    # 1. CMV dos Ingredientes
    total_cmv = calculate_cmv(recipe_ingredients)
    unit_cmv = total_cmv / n_units
    
    # 2. Custos de Embalagem
    unit_packaging = max(0.0, float(packaging_cost))
    total_packaging = unit_packaging * n_units
    
    # 3. Mão de Obra
    total_labor = (max(0.0, float(prep_time_min)) / 60.0) * max(0.0, float(hourly_rate))
    unit_labor = total_labor / n_units
    
    # Subtotal Custo Direto por Unidade
    unit_direct_cost = unit_cmv + unit_packaging + unit_labor
    
    # 4. Custos Operacionais / Indiretos (Overhead %)
    ov_pct = max(0.0, float(overhead_pct)) / 100.0
    unit_overhead = unit_direct_cost * ov_pct
    total_overhead = unit_overhead * n_units
    
    # 5. Custo Total de Produção por Unidade
    unit_total_cost = unit_direct_cost + unit_overhead
    total_production_cost = unit_total_cost * n_units
    
    # 6. Cálculo do Preço de Venda Sugerido
    # Preço Sugerido = Custo Total / (1 - (Taxas% + Margem%))
    t_margin = max(0.0, min(90.0, float(target_margin_pct))) / 100.0
    s_fees = max(0.0, min(90.0, float(sales_fees_pct))) / 100.0
    
    divisor = 1.0 - (s_fees + t_margin)
    if divisor <= 0.05: # Evitar divisão por zero ou margens matematicamente impossíveis
        divisor = 0.05
        
    suggested_unit_price = unit_total_cost / divisor
    suggested_total_price = suggested_unit_price * n_units
    
    # Métricas do Preço Sugerido
    sug_sales_fee_val = suggested_unit_price * s_fees
    sug_net_profit = suggested_unit_price - unit_total_cost - sug_sales_fee_val
    sug_net_margin_pct = (sug_net_profit / suggested_unit_price * 100.0) if suggested_unit_price > 0 else 0.0
    
    # Métricas do Preço Praticado (se informado pelo usuário)
    p_price = max(0.0, float(practiced_price))
    if p_price > 0:
        prac_unit_price = p_price
    else:
        prac_unit_price = suggested_unit_price
        
    prac_sales_fee_val = prac_unit_price * s_fees
    prac_net_profit = prac_unit_price - unit_total_cost - prac_sales_fee_val
    prac_net_margin_pct = (prac_net_profit / prac_unit_price * 100.0) if prac_unit_price > 0 else 0.0
    
    # Percentuais de decomposição do Preço Praticado (para gráfico/progress bar)
    if prac_unit_price > 0:
        cmv_pct = (unit_cmv / prac_unit_price) * 100.0
        pkg_pct = (unit_packaging / prac_unit_price) * 100.0
        labor_pct = (unit_labor / prac_unit_price) * 100.0
        overhead_pct_val = (unit_overhead / prac_unit_price) * 100.0
        fees_pct_val = (prac_sales_fee_val / prac_unit_price) * 100.0
        profit_pct_val = (prac_net_profit / prac_unit_price) * 100.0
    else:
        cmv_pct = pkg_pct = labor_pct = overhead_pct_val = fees_pct_val = profit_pct_val = 0.0

    return {
        "total_cmv": round(total_cmv, 2),
        "unit_cmv": round(unit_cmv, 2),
        "total_packaging": round(total_packaging, 2),
        "unit_packaging": round(unit_packaging, 2),
        "total_labor": round(total_labor, 2),
        "unit_labor": round(unit_labor, 2),
        "total_overhead": round(total_overhead, 2),
        "unit_overhead": round(unit_overhead, 2),
        "unit_total_cost": round(unit_total_cost, 2),
        "total_production_cost": round(total_production_cost, 2),
        "suggested_unit_price": round(suggested_unit_price, 2),
        "suggested_total_price": round(suggested_total_price, 2),
        "sug_sales_fee_val": round(sug_sales_fee_val, 2),
        "sug_net_profit": round(sug_net_profit, 2),
        "sug_net_margin_pct": round(sug_net_margin_pct, 1),
        "prac_unit_price": round(prac_unit_price, 2),
        "prac_sales_fee_val": round(prac_sales_fee_val, 2),
        "prac_net_profit": round(prac_net_profit, 2),
        "prac_net_margin_pct": round(prac_net_margin_pct, 1),
        "breakdown_pct": {
            "cmv": round(cmv_pct, 1),
            "packaging": round(pkg_pct, 1),
            "labor": round(labor_pct, 1),
            "overhead": round(overhead_pct_val, 1),
            "fees": round(fees_pct_val, 1),
            "profit": round(profit_pct_val, 1)
        }
    }


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

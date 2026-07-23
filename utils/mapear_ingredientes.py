"""
utils/mapear_ingredientes.py
─────────────────────────────────────────────────────────────────────────────
Converte nomes técnicos/catalográficos das tabelas TACO e TBCA em nomes
comerciais limpos, adequados para impressão no rótulo de acordo com as
normas da ANVISA (RDC 429/2020 e IN 75/2020).

Fluxo de processamento (em ordem de prioridade):
  1. Verifica no OVERRIDE_MAP se há substituição direta (30+ ingredientes).
  2. Inverte a estrutura com vírgulas (ex: "Farinha, de trigo" → "Farinha de trigo").
  3. Aplica regex para remover sufixos técnicos (cru, cozido, fresco, etc.).
  4. Faz capitalização correta (Title Case).
  5. Fallback: retorna o nome original em Title Case se nenhuma regra se aplicar.

Uso:
  from utils.mapear_ingredientes import nome_rotulo
  nome_limpo = nome_rotulo("Farinha, de trigo, especial")  # → "Farinha de trigo"
"""

import re

# ──────────────────────────────────────────────────────────────────────────────
# MAPA DE SUBSTITUIÇÃO DIRETA (Override)
# Cobre os 50+ ingredientes mais comuns da indústria alimentícia brasileira.
# Chave: parte do nome técnico (lowercase, sem acentos opcionais).
# Valor: nome comercial final para o rótulo.
# ──────────────────────────────────────────────────────────────────────────────
OVERRIDE_MAP: dict[str, str] = {
    # Açúcares e adoçantes
    "açúcar, cristal":                    "Açúcar cristal",
    "açúcar, refinado":                   "Açúcar refinado",
    "açúcar, demerara":                   "Açúcar demerara",
    "açúcar, mascavo":                    "Açúcar mascavo",
    "açúcar, de confeiteiro":             "Açúcar de confeiteiro",
    "açúcar, orgânico":                   "Açúcar orgânico",
    "mel, de abelha":                     "Mel",
    "mel":                                "Mel",
    "xarope de glicose":                  "Xarope de glicose",
    "glucose de milho":                   "Xarope de glicose de milho",
    "frutose":                            "Frutose",
    "lactose":                            "Lactose",

    # Farinhas e amidos
    "farinha, de trigo, especial":        "Farinha de trigo",
    "farinha, de trigo, integral":        "Farinha de trigo integral",
    "farinha, de mandioca, crua":         "Farinha de mandioca",
    "farinha, de mandioca":               "Farinha de mandioca",
    "farinha, de milho, amarela, crua":   "Fubá",
    "farinha, de milho":                  "Farinha de milho",
    "farinha, de aveia":                  "Farinha de aveia",
    "farinha, de arroz":                  "Farinha de arroz",
    "farinha, de soja":                   "Farinha de soja",
    "farinha, de centeio":                "Farinha de centeio",
    "fécula de batata":                   "Fécula de batata",
    "amido de milho":                     "Amido de milho",
    "amido, de milho":                    "Amido de milho",
    "polvilho, azedo":                    "Polvilho azedo",
    "polvilho, doce":                     "Polvilho doce",
    "polvilho":                           "Polvilho",

    # Laticínios
    "leite, de vaca, integral, fluido":   "Leite integral",
    "leite, de vaca, desnatado, fluido":  "Leite desnatado",
    "leite, de vaca, semidesnatado":      "Leite semidesnatado",
    "leite, em pó, integral":             "Leite em pó integral",
    "leite, em pó, desnatado":            "Leite em pó desnatado",
    "manteiga, com sal":                  "Manteiga com sal",
    "manteiga, sem sal":                  "Manteiga",
    "manteiga":                           "Manteiga",
    "margarina, com sal":                 "Margarina com sal",
    "margarina, sem sal":                 "Margarina",
    "margarina":                          "Margarina",
    "creme de leite":                     "Creme de leite",
    "queijo, minas, frescal":             "Queijo minas frescal",
    "queijo, mussarela":                  "Queijo mussarela",
    "queijo, parmesão":                   "Queijo parmesão",
    "iogurte, integral, natural":         "Iogurte natural",
    "iogurte, natural":                   "Iogurte natural",
    "requeijão, cremoso":                 "Requeijão cremoso",

    # Ovos
    "ovo, de galinha, inteiro, cru":      "Ovo",
    "ovo, de galinha, inteiro, cozido":   "Ovo cozido",
    "ovo, de galinha, clara, crua":       "Clara de ovo",
    "ovo, de galinha, gema, crua":        "Gema de ovo",
    "ovo":                                "Ovo",

    # Óleos e gorduras
    "óleo, de soja, refinado":            "Óleo de soja",
    "óleo, de soja":                      "Óleo de soja",
    "óleo, de milho":                     "Óleo de milho",
    "óleo, de girassol":                  "Óleo de girassol",
    "óleo, de canola":                    "Óleo de canola",
    "óleo, de coco":                      "Óleo de coco",
    "óleo, de oliva, extra virgem":       "Azeite de oliva extra virgem",
    "azeite, de oliva":                   "Azeite de oliva",
    "gordura vegetal, de palma":          "Gordura de palma",
    "gordura vegetal, hidrogenada":       "Gordura vegetal hidrogenada",

    # Carnes e proteínas
    "frango, peito, sem pele, cru":       "Peito de frango",
    "frango, coxa, sem pele, cru":        "Coxa de frango",
    "carne bovina, patinho, cru":         "Carne bovina",
    "carne, bovina, acém, cru":           "Carne bovina",
    "peixe, tilápia, filé, cru":          "Filé de tilápia",
    "proteína, de soja, texturizada":     "Proteína de soja texturizada",
    "proteína de soja":                   "Proteína de soja",

    # Leguminosas e cereais
    "arroz, branco, cozido":              "Arroz branco",
    "arroz, branco, cru":                 "Arroz branco",
    "arroz, integral, cru":               "Arroz integral",
    "feijão, carioca, cru":               "Feijão carioca",
    "feijão, preto, cru":                 "Feijão preto",
    "feijão, cozido":                     "Feijão",
    "aveia, em flocos":                   "Flocos de aveia",
    "aveia, farinha":                     "Farinha de aveia",
    "granola":                            "Granola",
    "quinoa, grão, cru":                  "Quinoa",

    # Frutas e derivados
    "banana, nanica, crua":               "Banana",
    "maçã, fuji, crua":                   "Maçã",
    "uva passa, preta":                   "Uva passa",
    "uva, passa":                         "Uva passa",
    "coco, ralado, seco, adoçado":        "Coco ralado adoçado",
    "coco, ralado, seco":                 "Coco ralado",

    # Condimentos e temperos
    "sal, refinado":                      "Sal",
    "sal":                                "Sal",
    "vinagre, de álcool":                 "Vinagre",
    "bicarbonato de sódio":               "Bicarbonato de sódio",
    "fermento, em pó, químico":           "Fermento químico em pó",
    "fermento, biológico, seco":          "Fermento biológico",
    "cacau, em pó, sem açúcar":           "Cacau em pó",
    "chocolate, em pó":                   "Chocolate em pó",
    "canela, em pó":                      "Canela em pó",
    "baunilha, extrato":                  "Extrato de baunilha",
    "essência de baunilha":               "Essência de baunilha",
    "lecitina de soja":                   "Lecitina de soja",

    # Bebidas e derivados
    "café, torrado, moído":               "Café torrado e moído",
    "suco, de laranja, pasteurizado":     "Suco de laranja",
    "água":                               "Água",
}


# ──────────────────────────────────────────────────────────────────────────────
# SUFIXOS TÉCNICOS A REMOVER (Regex)
# Padrões encontrados frequentemente nos catálogos TACO e TBCA.
# ──────────────────────────────────────────────────────────────────────────────
_SUFFIXES_PATTERN = re.compile(
    r",?\s*("
    r"cru[ao]?|cozido[ao]?|assado[ao]?|frito[ao]?|grelhado[ao]?"
    r"|fresco[ao]?|seco[ao]?|desidratado[ao]?"
    r"|fluido[ao]?|pasteurizado[ao]?|esterilizado[ao]?"
    r"|industrializado[ao]?|processado[ao]?"
    r"|light|diet|zero"
    r"|de vaca|de cabra|de búfala"
    r"|de galinha|de codorna"
    r"|inteiro[ao]?|especial|simples|refinado[ao]?|comum"
    r"|tipo\s+\w+"
    r")",
    flags=re.IGNORECASE | re.UNICODE,
)

_COMMA_PREP_PATTERN = re.compile(r"^([^,]+),\s*(.+)$", re.UNICODE)


def _invert_comma_structure(name: str) -> str:
    """
    Inverte a estrutura "Substantivo, complemento" do catálogo.
    Ex: "Farinha, de trigo, especial" → "Farinha de trigo especial"
    Ex: "Leite, de vaca, integral" → "Leite de vaca integral"
    """
    parts = [p.strip() for p in name.split(",")]
    if len(parts) == 1:
        return name.strip()
    # Primeiro elemento é o substantivo principal
    main = parts[0].strip()
    rest = " ".join(p.strip() for p in parts[1:] if p.strip())
    return f"{main} {rest}".strip()


def nome_rotulo(nome_tecnico: str) -> str:
    """
    Converte um nome técnico TACO/TBCA para o nome comercial do rótulo.

    Prioridade de resolução:
      1. OVERRIDE_MAP: substituição direta e exata.
      2. Inversão de vírgulas + remoção de sufixos técnicos.
      3. Fallback: nome original em Title Case.

    Args:
        nome_tecnico: Nome técnico conforme TACO/TBCA
                      (ex: "Farinha, de trigo, especial").

    Returns:
        Nome comercial limpo para uso no rótulo
        (ex: "Farinha de trigo").
    """
    if not nome_tecnico or not isinstance(nome_tecnico, str):
        return ""

    nome_tecnico = nome_tecnico.strip()
    chave = nome_tecnico.lower()

    # 1. Verificação no OVERRIDE_MAP (prioridade máxima)
    if chave in OVERRIDE_MAP:
        return OVERRIDE_MAP[chave]

    # Também verifica correspondência parcial de prefixo para nomes longos
    for override_key, override_val in OVERRIDE_MAP.items():
        if chave.startswith(override_key):
            return override_val

    # 2. Inversão da estrutura com vírgulas
    nome_invertido = _invert_comma_structure(nome_tecnico)

    # 3. Remoção de sufixos técnicos via Regex
    nome_limpo = _SUFFIXES_PATTERN.sub("", nome_invertido).strip()

    # 4. Limpar vírgulas e espaços residuais
    nome_limpo = re.sub(r"\s*,\s*", " ", nome_limpo).strip()
    nome_limpo = re.sub(r"\s{2,}", " ", nome_limpo).strip()

    # 5. Title Case e fallback para o nome original se o resultado ficou vazio
    if nome_limpo:
        return nome_limpo.title()

    return nome_tecnico.title()


def gerar_lista_ingredientes_rotulo(recipe: list[dict]) -> str:
    """
    Gera o texto completo da lista de ingredientes para o rótulo.

    Regras ANVISA (IN 75/2020):
      - Ordenado do maior para o menor peso (decrescente).
      - Nomes comerciais em letras maiúsculas.
      - Separados por vírgula, finalizando com ponto.

    Args:
        recipe: Lista de ingredientes da receita. Cada item é um dict com
                pelo menos as chaves 'w' (peso em g) e 'd' (descrição técnica).

    Returns:
        String formatada para o campo INGREDIENTES do rótulo.
        Ex: "FARINHA DE TRIGO, AÇÚCAR, OVO, MANTEIGA."
    """
    if not recipe:
        return ""

    # Ordenar por peso decrescente (norma ANVISA)
    sorted_recipe = sorted(recipe, key=lambda x: x.get("w", 0), reverse=True)

    nomes = []
    for ing in sorted_recipe:
        nome_tecnico = ing.get("d", "")
        nome_limpo = nome_rotulo(nome_tecnico)
        nomes.append(nome_limpo.upper())

    return ", ".join(nomes) + "."


if __name__ == "__main__":
    # Teste rápido dos casos de uso mais comuns
    testes = [
        "Farinha, de trigo, especial",
        "Açúcar, cristal",
        "Leite, de vaca, integral, fluido",
        "Ovo, de galinha, inteiro, cru",
        "Manteiga, sem sal",
        "Sal, refinado",
        "Fermento, em pó, químico",
        "Óleo, de soja, refinado",
        "Cacau, em pó, sem açúcar",
        "Feijão, carioca, cru",
        "Arroz, branco, cru",
        "Proteína, de soja, texturizada",
        "Frango, peito, sem pele, cru",
        "Banana, nanica, crua",
        "Aveia, em flocos",
    ]
    print(f"{'Nome Técnico (TACO/TBCA)':<45} → Nome do Rótulo")
    print("-" * 75)
    for t in testes:
        print(f"{t:<45} → {nome_rotulo(t)}")

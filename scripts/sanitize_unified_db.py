"""
scripts/sanitize_unified_db.py
─────────────────────────────────────────────────────────────────────────────
Pipeline reprodutível e auditável de saneamento de `alimentos_unified.json`
(Onda 2 da Auditoria RotuleiApp — DB-02, DB-04, DB-05, DB-06, DB-07, DB-08,
DB-09, DB-11, P-3.2, P-8.1, P-13.1).

Regras aplicadas:
  1. DB-02 / P-3.1: Restaura os 15 grupos oficiais da TACO 4ª Ed. a partir de
     `Taco-4a-Edicao.CSV` (elimina 363 registros com grupo 'Número do').
  2. P-3.2: Unifica capitalização de grupos ('Pescados e Frutos do mar' ->
     'Pescados e frutos do mar').
  3. DB-04 / P-6.1: Calcula 'Carboidrato disponível (g) = max(0, Carboidrato
     total - Fibra alimentar)' nos 597 itens da TACO (elimina dupla contagem de fibras).
  4. DB-05 / P-6.2: Corrige falsos positivos de açúcar adicionado na TACO
     (TACO-1 Arroz integral, TACO-5 Arroz tipo 2, TACO-475 Chá erva-doce -> 0.0)
     e marca açúcares/ácidos graxos imputados na TACO com metadado '_est'.
  5. DB-06 / P-6.3 e DB-09 / P-10.1: Preserva rastreabilidade de valores 'NA'
     e 'Tr' originais (via metadados '_na' e '_tr') sem quebrar o cálculo numérico;
     registra '_na' para 'Açúcares totais (g)' quando ausente na fonte original TBCA.
  6. DB-07 / P-5.1: Normaliza a chave 'Colesterol (g)' -> 'Colesterol (mg)' em
     269 registros da TBCA.
  7. DB-08 / P-8.2: Corrige violações físico-químicas (Açúcares totais <= Carboidrato
     total, Carboidrato disponível <= Carboidrato total, anulação de trans > lipídios
     com registro em '_na' e '_anomalias').
  8. P-8.1: Corrige valor malformado ',0,02' de Vitamina B6 em TACO-373.
  9. P-13.1: Gera `DATABASE_MANIFEST.json` com versões, contagens e SHA-256.
"""

import csv
import datetime
import hashlib
import json
import os
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TBCA_ORIG_PATH = os.path.join(BASE_DIR, "alimentos.json")
TACO_CSV_PATH = os.path.join(BASE_DIR, "Taco-4a-Edicao.CSV")
UNIFIED_PATH = os.path.join(BASE_DIR, "alimentos_unified.json")
MANIFEST_PATH = os.path.join(BASE_DIR, "DATABASE_MANIFEST.json")

# Colunas principais de Taco-4a-Edicao.CSV (0-indexed)
TACO_COL_MAP = {
    3: "Energia (kcal)",
    5: "Proteína (g)",
    6: "Lipídios (g)",
    7: "Colesterol (mg)",
    8: "Carboidrato total (g)",
    9: "Fibra alimentar (g)",
    16: "Sódio (mg)",
}


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def _to_float_or_none(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if s.lower() in ("", "na", "nd", "tr", "*", "-", "n.d."):
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def parse_taco_csv(csv_path: str):
    """Lê Taco-4a-Edicao.CSV em latin-1 e retorna grupos oficiais e tokens NA/Tr por TACO-ID."""
    groups = {}
    na_map = {}
    tr_map = {}
    cur_group = ""
    with open(csv_path, "r", encoding="latin-1") as f:
        reader = csv.reader(f, delimiter=";")
        for row in reader:
            if not row:
                continue
            c0 = (row[0] or "").strip()
            c1 = (row[1] or "").strip() if len(row) > 1 else ""
            if c0.isdigit():
                tid = f"TACO-{int(c0)}"
                groups[tid] = cur_group
                nas = []
                trs = []
                for idx, nut_name in TACO_COL_MAP.items():
                    if idx < len(row):
                        tok = (row[idx] or "").strip().lower()
                        if tok in ("na", "*", "", "-"):
                            nas.append(nut_name)
                        elif tok == "tr":
                            trs.append(nut_name)
                na_map[tid] = nas
                tr_map[tid] = trs
            elif c0 and not c1 and not c0.lower().startswith(
                ("número", "numero", "tabela", "1 ", "2 ", "*", "tr", "na", "obs")
            ):
                cur_group = c0
    return groups, na_map, tr_map


def sanitize():
    taco_groups, taco_na, taco_tr = parse_taco_csv(TACO_CSV_PATH)
    with open(TBCA_ORIG_PATH, "r", encoding="utf-8-sig") as f:
        tbca_orig = {x["c"]: x for x in json.load(f)}
    with open(UNIFIED_PATH, "r", encoding="utf-8-sig") as f:
        unified = json.load(f)

    stats = Counter()
    taco_false_sugar_ids = {"TACO-1", "TACO-5", "TACO-475"}

    for item in unified:
        code = item.get("c", "")
        n = item.get("n") or {}
        na_list = []
        tr_list = []
        est_list = []
        anomalias = []

        # 1. P-3.2: Normalização de capitalização de grupos
        if item.get("g") == "Pescados e Frutos do mar":
            item["g"] = "Pescados e frutos do mar"
            stats["grupo_pescados_normalizado"] += 1

        # 2. DB-07: Colesterol (g) -> Colesterol (mg)
        if "Colesterol (g)" in n:
            if "Colesterol (mg)" not in n:
                n["Colesterol (mg)"] = n.pop("Colesterol (g)")
            else:
                n.pop("Colesterol (g)")
            stats["colesterol_chave_corrigida"] += 1

        if code.startswith("TACO-"):
            # DB-02: Restaurar grupo oficial da TACO 4ª Ed.
            if code in taco_groups and taco_groups[code]:
                if item.get("g") != taco_groups[code]:
                    item["g"] = taco_groups[code]
                    stats["taco_grupo_restaurado"] += 1

            # DB-09: Preservar metadados NA/Tr originais do CSV da TACO
            na_list.extend(taco_na.get(code, []))
            tr_list.extend(taco_tr.get(code, []))
            # TACO 4ª Ed. tabela principal não analisa açúcares totais/adicionados nem ácidos graxos
            est_list.extend(["Açúcares totais (g)", "Açúcar de adição (g)", "Ácidos graxos saturados (g)", "Ácidos graxos trans (g)"])

            # DB-04: Carboidrato disponível = max(0, Carboidrato total - Fibra alimentar)
            ct = _to_float_or_none(n.get("Carboidrato total (g)"))
            fib = _to_float_or_none(n.get("Fibra alimentar (g)")) or 0.0
            if ct is not None:
                c_disp = round(max(0.0, ct - fib), 2)
                if _to_float_or_none(n.get("Carboidrato disponível (g)")) != c_disp:
                    n["Carboidrato disponível (g)"] = c_disp
                    stats["taco_carb_disp_corrigido"] += 1

            # DB-05: Corrigir falsos positivos grosseiros de açúcar adicionado (Arroz, Chá)
            if code in taco_false_sugar_ids:
                n["Açúcar de adição (g)"] = 0.0
                n["Açúcares totais (g)"] = 0.0
                stats["taco_acucar_falso_corrigido"] += 1

            # P-8.1: TACO-373 Vitamina B6 malformada ',0,02' -> 0.02
            if code == "TACO-373" and str(n.get("Vitamina B6 (mg)", "")).strip() == ",0,02":
                n["Vitamina B6 (mg)"] = 0.02
                stats["taco_373_b6_corrigido"] += 1

        else:
            # Registro TBCA
            orig = tbca_orig.get(code)
            orig_n = (orig.get("n") or {}) if orig else {}

            # DB-09: Preservar NA/Tr originais da TBCA
            for k, v in orig_n.items():
                if isinstance(v, str):
                    vl = v.strip().lower()
                    if vl in ("na", "nd", "*", "-", ""):
                        na_list.append(k)
                    elif vl == "tr":
                        tr_list.append(k)

            # DB-06: Se 'Açúcares totais (g)' não existia na TBCA original e está 0.0, marcar como NA
            if "Açúcares totais (g)" not in orig_n:
                st_val = _to_float_or_none(n.get("Açúcares totais (g)"))
                sa_val = _to_float_or_none(n.get("Açúcar de adição (g)"))
                if (st_val is None or st_val == 0.0) and (sa_val is None or sa_val == 0.0):
                    na_list.append("Açúcares totais (g)")
                    stats["tbca_acucar_total_marcado_na"] += 1
                else:
                    est_list.append("Açúcares totais (g)")

            # Marcar chaves adicionadas não presentes em alimentos.json como estimadas
            for extra_k in ("Açúcar de adição (g)", "Ácidos graxos trans (g)", "Ácidos graxos saturados (g)"):
                if extra_k in n and extra_k not in orig_n:
                    est_list.append(extra_k)
            if code == "C0030G":
                est_list.append("Açúcar de adição (g)")

        # DB-08: Consistência físico-química
        ct = _to_float_or_none(n.get("Carboidrato total (g)"))
        cd = _to_float_or_none(n.get("Carboidrato disponível (g)"))
        st_v = _to_float_or_none(n.get("Açúcares totais (g)"))
        sa_v = _to_float_or_none(n.get("Açúcar de adição (g)"))
        lip = _to_float_or_none(n.get("Lipídios (g)"))
        sat = _to_float_or_none(n.get("Ácidos graxos saturados (g)"))
        tra = _to_float_or_none(n.get("Ácidos graxos trans (g)"))

        if ct is not None and cd is not None and cd > ct + 0.01:
            n["Carboidrato disponível (g)"] = round(ct, 2)
            anomalias.append("carb_disp_limitado_ao_total")
            stats["violacao_carb_disp_corrigida"] += 1

        if ct is not None and st_v is not None and st_v > ct + 0.01:
            n["Açúcares totais (g)"] = round(ct, 2)
            if sa_v is not None and sa_v > ct + 0.01:
                n["Açúcar de adição (g)"] = round(ct, 2)
            anomalias.append("acucar_limitado_ao_carb_total")
            stats["violacao_acucar_corrigida"] += 1

        # Anomalia severa na origem (ex.: C0862F coelho com 24.5g trans em 5.7g lipídios)
        if lip is not None and tra is not None and tra > lip + 0.5:
            n["Ácidos graxos trans (g)"] = None
            na_list.append("Ácidos graxos trans (g)")
            anomalias.append(f"trans_impossivel_removido({tra}g_em_{lip}g_lip)")
            stats["violacao_trans_impossivel_corrigida"] += 1
        elif lip is not None and sat is not None and sat > lip + 0.5:
            anomalias.append(f"sat_maior_que_lip({sat}g_em_{lip}g_lip)")
            stats["alerta_sat_maior_lip"] += 1

        item["n"] = n
        # Gravar metadados compactos apenas quando não vazios (mantém JSON enxuto)
        na_dedup = sorted(set(na_list))
        tr_dedup = sorted(set(tr_list))
        est_dedup = sorted(set(est_list))
        if na_dedup:
            item["_na"] = na_dedup
        else:
            item.pop("_na", None)
        if tr_dedup:
            item["_tr"] = tr_dedup
        else:
            item.pop("_tr", None)
        if est_dedup:
            item["_est"] = est_dedup
        else:
            item.pop("_est", None)
        if anomalias:
            item["_anomalias"] = anomalias
        else:
            item.pop("_anomalias", None)

    with open(UNIFIED_PATH, "w", encoding="utf-8") as f:
        json.dump(unified, f, indent=4, ensure_ascii=False)

    manifest = {
        "schema_version": "2.0.0",
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "generator_script": "scripts/sanitize_unified_db.py",
        "sources": {
            "TBCA": {
                "file": "alimentos.json",
                "records": len(tbca_orig),
                "version_note": "TBCA USP/FoRC (versão/data de extração original não informada nos metadados brutos; compatível com série v7.1/v7.2)",
                "sha256": _sha256_file(TBCA_ORIG_PATH),
            },
            "TACO": {
                "file": "Taco-4a-Edicao.CSV",
                "records": len(taco_groups),
                "version_note": "TACO NEPA/UNICAMP 4ª Edição Revisada e Ampliada (2011) — Tabela principal (sem CSV de Ácidos Graxos)",
                "sha256": _sha256_file(TACO_CSV_PATH),
            },
        },
        "output": {
            "file": "alimentos_unified.json",
            "total_records": len(unified),
            "sha256": _sha256_file(UNIFIED_PATH),
        },
        "sanitization_stats": dict(stats),
    }
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print("Saneamento concluído:", json.dumps(dict(stats), indent=2, ensure_ascii=False))
    print("SHA-256 alimentos_unified.json:", manifest["output"]["sha256"])


if __name__ == "__main__":
    sanitize()

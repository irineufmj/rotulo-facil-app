# Script para unificar dados da TBCA e TACO em SQL e JSON
$tbcaRawPath = "C:\Users\IRINEU\.gemini\antigravity\scratch\alimentos_raw.json"
$tacoCsvPath = "C:\Users\IRINEU\.gemini\antigravity\brain\dc7db576-c340-4f7c-8def-bf6fa99b4b55\Taco-4a-Edicao.CSV"
$sqlOutputPath = "C:\Users\IRINEU\.gemini\antigravity\scratch\tbca-app\tbca_taco.sql"
$jsonOutputPath = "C:\Users\IRINEU\.gemini\antigravity\scratch\tbca-app\alimentos_unified.json"

Write-Output "Iniciando processo de unificação TBCA + TACO..."

# Inicializar SQL unificado
$sqlHeader = @"
-- Script Unificado TBCA + TACO
-- Gerado automaticamente em $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS alimento (
    codigo TEXT PRIMARY KEY,
    classe TEXT NOT NULL,
    descricao TEXT NOT NULL,
    fonte TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alimento_nutriente (
    alimento_codigo TEXT REFERENCES alimento(codigo),
    componente TEXT NOT NULL,
    unidades TEXT NOT NULL,
    valor_raw TEXT NOT NULL,
    valor_numerico REAL,
    PRIMARY KEY (alimento_codigo, componente)
);

BEGIN TRANSACTION;
"@

[System.IO.File]::WriteAllText($sqlOutputPath, $sqlHeader + "`r`n", [System.Text.Encoding]::UTF8)

# Lista para unificar objetos para alimentos_unified.json
$unifiedFoodsList = [System.Collections.Generic.List[Object]]::new()

# ==========================================
# 1. PROCESSAR TBCA (do arquivo bruto)
# ==========================================
Write-Output "Processando registros da TBCA..."
$tbcaCount = 0
$tbcaLines = Get-Content $tbcaRawPath

foreach ($line in $tbcaLines) {
    $trimmed = $line.Trim()
    if ([string]::IsNullOrEmpty($trimmed)) { continue }
    
    $obj = ConvertFrom-Json $trimmed
    $tbcaCount++
    
    $codigo = $obj.codigo.Replace("'", "''")
    $classe = $obj.classe.Replace("'", "''")
    $descricao = $obj.descricao.Replace("'", "''")
    
    # Inserir alimento TBCA
    $sqlFood = "INSERT INTO alimento (codigo, classe, descricao, fonte) VALUES ('$codigo', '$classe', '$descricao', 'TBCA');"
    [System.IO.File]::AppendAllText($sqlOutputPath, $sqlFood + "`r`n", [System.Text.Encoding]::UTF8)
    
    $nutDict = [System.Collections.Generic.Dictionary[string, object]]::new()
    
    foreach ($n in $obj.nutrientes) {
        $comp = $n.Componente
        $compEscaped = $comp.Replace("'", "''")
        $unit = $n.Unidades
        $unitEscaped = $unit.Replace("'", "''")
        $valRaw = $n.'Valor por 100g'
        $valRawEscaped = $valRaw.Replace("'", "''")
        
        $valNumSql = "NULL"
        $cleanVal = $valRaw.Replace(",", ".").Trim()
        if ($cleanVal -match '^-?[0-9]+(\.[0-9]+)?$') {
            $valNumSql = $cleanVal
            $key = "$comp ($unit)"
            $nutDict[$key] = [double]$cleanVal
        } else {
            if ($valRaw -ne "NA") {
                $key = "$comp ($unit)"
                $nutDict[$key] = $valRaw
            }
        }
        
        $sqlNut = "INSERT INTO alimento_nutriente (alimento_codigo, componente, unidades, valor_raw, valor_numerico) VALUES ('$codigo', '$compEscaped', '$unitEscaped', '$valRawEscaped', $valNumSql);"
        [System.IO.File]::AppendAllText($sqlOutputPath, $sqlNut + "`r`n", [System.Text.Encoding]::UTF8)
    }
    
    $foodOpt = [PSCustomObject]@{
        c = $obj.codigo
        g = $obj.classe
        d = $obj.descricao
        f = "TBCA"
        n = $nutDict
    }
    $unifiedFoodsList.Add($foodOpt)
}
Write-Output "TBCA Concluído! $tbcaCount registros processados."

# ==========================================
# 2. PROCESSAR TACO (do arquivo CSV)
# ==========================================
Write-Output "Processando registros da TACO..."
$tacoCount = 0
$tacoLines = Get-Content -Encoding Default -Path $tacoCsvPath
$currentCategory = "Outros"

# Mapeamento dos índices do CSV do TACO para nome de componente e unidade do TBCA
$tacoNutrientsMap = @{
    2  = @{ name = "Umidade"; unit = "g" }
    3  = @{ name = "Energia"; unit = "kcal" }
    4  = @{ name = "Energia"; unit = "kJ" }
    5  = @{ name = "Proteína"; unit = "g" }
    6  = @{ name = "Lipídios"; unit = "g" }
    7  = @{ name = "Colesterol"; unit = "mg" }
    8  = @{ name = "Carboidrato total"; unit = "g" } # Mapeado para total
    9  = @{ name = "Fibra alimentar"; unit = "g" }
    10 = @{ name = "Cinzas"; unit = "g" }
    11 = @{ name = "Cálcio"; unit = "mg" }
    12 = @{ name = "Magnésio"; unit = "mg" }
    14 = @{ name = "Manganês"; unit = "mg" }
    15 = @{ name = "Fósforo"; unit = "mg" }
    16 = @{ name = "Ferro"; unit = "mg" }
    17 = @{ name = "Sódio"; unit = "mg" }
    18 = @{ name = "Potássio"; unit = "mg" }
    19 = @{ name = "Cobre"; unit = "mg" }
    20 = @{ name = "Zinco"; unit = "mg" }
    21 = @{ name = "Retinol"; unit = "mcg" }
    22 = @{ name = "Vitamina A (RE)"; unit = "mcg" }
    23 = @{ name = "Vitamina A (RAE)"; unit = "mcg" }
    24 = @{ name = "Tiamina"; unit = "mg" }
    25 = @{ name = "Riboflavina"; unit = "mg" }
    26 = @{ name = "Vitamina B6"; unit = "mg" }
    27 = @{ name = "Niacina"; unit = "mg" }
    28 = @{ name = "Vitamina C"; unit = "mg" }
}

for ($i = 3; $i -lt $tacoLines.Length; $i++) {
    $line = $tacoLines[$i].Trim()
    if ([string]::IsNullOrEmpty($line)) { continue }
    
    $cols = $line.Split(';')
    if ($cols.Length -lt 2) { continue }
    
    $col0 = $cols[0].Trim()
    $col1 = $cols[1].Trim()
    
    # Ignorar linhas de cabeçalho interno
    if ($col0 -eq "Número do" -or $col0 -eq "Alimento" -or $col0 -eq "Legenda") {
        continue
    }
    
    # Se col0 é numérico, é um alimento
    if ($col0 -match '^[0-9]+$') {
        $tacoCount++
        $code = "TACO-$col0"
        $descricao = $col1.Replace("'", "''")
        $classe = $currentCategory.Replace("'", "''")
        
        # Inserir alimento TACO
        $sqlFood = "INSERT INTO alimento (codigo, classe, descricao, fonte) VALUES ('$code', '$classe', '$descricao', 'TACO');"
        [System.IO.File]::AppendAllText($sqlOutputPath, $sqlFood + "`r`n", [System.Text.Encoding]::UTF8)
        
        $nutDict = [System.Collections.Generic.Dictionary[string, object]]::new()
        
        # Iterar nas colunas de nutrientes mapeadas
        foreach ($index in $tacoNutrientsMap.Keys) {
            if ($index -ge $cols.Length) { continue }
            
            $valRaw = $cols[$index].Trim()
            if ([string]::IsNullOrEmpty($valRaw)) { continue }
            
            $mapping = $tacoNutrientsMap[$index]
            $comp = $mapping.name
            $compEscaped = $comp.Replace("'", "''")
            $unit = $mapping.unit
            $unitEscaped = $unit.Replace("'", "''")
            $valRawEscaped = $valRaw.Replace("'", "''")
            
            $valNumSql = "NULL"
            $cleanVal = $valRaw.Replace(",", ".").Trim()
            
            if ($cleanVal -match '^-?[0-9]+(\.[0-9]+)?$') {
                $valNumSql = $cleanVal
                $key = "$comp ($unit)"
                $nutDict[$key] = [double]$cleanVal
                
                # Se for Carboidrato total, vamos adicionar também como Carboidrato disponível para manter compatibilidade
                if ($comp -eq "Carboidrato total") {
                    $keyDisp = "Carboidrato disponível ($unit)"
                    $nutDict[$keyDisp] = [double]$cleanVal
                }
            } else {
                # Omitir NA do JSON para salvar espaço
                if ($valRaw -ne "NA") {
                    $key = "$comp ($unit)"
                    $nutDict[$key] = $valRaw
                    
                    if ($comp -eq "Carboidrato total") {
                        $keyDisp = "Carboidrato disponível ($unit)"
                        $nutDict[$keyDisp] = $valRaw
                    }
                }
            }
            
            # Escrever insert do nutriente
            $sqlNut = "INSERT INTO alimento_nutriente (alimento_codigo, componente, unidades, valor_raw, valor_numerico) VALUES ('$code', '$compEscaped', '$unitEscaped', '$valRawEscaped', $valNumSql);"
            [System.IO.File]::AppendAllText($sqlOutputPath, $sqlNut + "`r`n", [System.Text.Encoding]::UTF8)
            
            # Adicionar também o insert para Carboidrato disponível se for total
            if ($comp -eq "Carboidrato total") {
                $sqlNutDisp = "INSERT INTO alimento_nutriente (alimento_codigo, componente, unidades, valor_raw, valor_numerico) VALUES ('$code', 'Carboidrato disponível', '$unitEscaped', '$valRawEscaped', $valNumSql);"
                [System.IO.File]::AppendAllText($sqlOutputPath, $sqlNutDisp + "`r`n", [System.Text.Encoding]::UTF8)
            }
        }
        
        $foodOpt = [PSCustomObject]@{
            c = $code
            g = $currentCategory
            d = $col1
            f = "TACO"
            n = $nutDict
        }
        $unifiedFoodsList.Add($foodOpt)
        
    } else {
        # É uma linha de categoria
        if (-not [string]::IsNullOrEmpty($col0) -and [string]::IsNullOrEmpty($col1)) {
            $currentCategory = $col0
        }
    }
}
Write-Output "TACO Concluído! $tacoCount registros processados."

# Finalizar SQL
[System.IO.File]::AppendAllText($sqlOutputPath, "COMMIT;`r`n", [System.Text.Encoding]::UTF8)

# Salvar JSON Unificado
Write-Output "Salvando arquivo JSON unificado..."
$jsonOut = ConvertTo-Json -InputObject $unifiedFoodsList -Depth 5 -Compress
[System.IO.File]::WriteAllText($jsonOutputPath, $jsonOut, [System.Text.Encoding]::UTF8)

$totalCount = $tbcaCount + $tacoCount
Write-Output "Unificação Concluída com Sucesso!"
Write-Output "Total Alimentos: $totalCount (TBCA: $tbcaCount | TACO: $tacoCount)"
Write-Output "SQL unificado: $sqlOutputPath"
Write-Output "JSON unificado: $jsonOutputPath"

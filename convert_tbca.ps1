# Script para converter dados brutos da TBCA em SQL e JSON otimizado
$rawFilePath = "C:\Users\IRINEU\.gemini\antigravity\scratch\alimentos_raw.json"
$sqlOutputPath = "C:\Users\IRINEU\.gemini\antigravity\scratch\tbca-app\tbca.sql"
$jsonOutputPath = "C:\Users\IRINEU\.gemini\antigravity\scratch\tbca-app\alimentos.json"

Write-Output "Iniciando processamento da TBCA..."

# Criar pasta do projeto se não existir
$projectFolder = Split-Path $sqlOutputPath
if (-not (Test-Path $projectFolder)) {
    New-Item -ItemType Directory -Force -Path $projectFolder | Out-Null
}

# Inicializar o script SQL
$sqlHeader = @"
-- Script de Importação dos Dados da TBCA (Tabela Brasileira de Composição de Alimentos)
-- Gerado automaticamente em $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS alimento (
    codigo TEXT PRIMARY KEY,
    classe TEXT NOT NULL,
    descricao TEXT NOT NULL
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

# Lista para armazenar objetos JSON otimizados
$foodsList = [System.Collections.Generic.List[Object]]::new()

$lineCount = 0
$totalLines = (Get-Content $rawFilePath).Length
Write-Output "Total de registros a processar: $totalLines"

# Ler e processar linha por linha
Get-Content $rawFilePath | ForEach-Object {
    $line = $_.Trim()
    if ([string]::IsNullOrEmpty($line)) { return }
    
    $obj = ConvertFrom-Json $line
    $lineCount++
    
    if ($lineCount % 1000 -eq 0) {
        Write-Output "Processados $lineCount de $totalLines registros..."
    }
    
    # --- Gerar SQL ---
    $codigo = $obj.codigo.Replace("'", "''")
    $classe = $obj.classe.Replace("'", "''")
    $descricao = $obj.descricao.Replace("'", "''")
    
    $sqlFood = "INSERT INTO alimento (codigo, classe, descricao) VALUES ('$codigo', '$classe', '$descricao');"
    [System.IO.File]::AppendAllText($sqlOutputPath, $sqlFood + "`r`n", [System.Text.Encoding]::UTF8)
    
    # Dicionário de nutrientes para o JSON otimizado
    $nutDict = [System.Collections.Generic.Dictionary[string, object]]::new()
    
    foreach ($n in $obj.nutrientes) {
        $comp = $n.Componente
        $compEscaped = $comp.Replace("'", "''")
        $unit = $n.Unidades
        $unitEscaped = $unit.Replace("'", "''")
        $valRaw = $n.'Valor por 100g'
        $valRawEscaped = $valRaw.Replace("'", "''")
        
        # Tratar valor numérico para SQL
        $valNumSql = "NULL"
        $cleanVal = $valRaw.Replace(",", ".").Trim()
        if ($cleanVal -match '^-?[0-9]+(\.[0-9]+)?$') {
            $valNumSql = $cleanVal
            # Adicionar ao JSON otimizado como número
            $key = "$comp ($unit)"
            $nutDict[$key] = [double]$cleanVal
        } else {
            # Se for "tr" ou outro valor textual (excluindo "NA" para economizar espaço no JSON)
            if ($valRaw -ne "NA") {
                $key = "$comp ($unit)"
                $nutDict[$key] = $valRaw
            }
        }
        
        $sqlNut = "INSERT INTO alimento_nutriente (alimento_codigo, componente, unidades, valor_raw, valor_numerico) VALUES ('$codigo', '$compEscaped', '$unitEscaped', '$valRawEscaped', $valNumSql);"
        [System.IO.File]::AppendAllText($sqlOutputPath, $sqlNut + "`r`n", [System.Text.Encoding]::UTF8)
    }
    
    # --- Adicionar ao JSON otimizado ---
    $foodOpt = [PSCustomObject]@{
        c = $obj.codigo
        g = $obj.classe
        d = $obj.descricao
        n = $nutDict
    }
    $foodsList.Add($foodOpt)
}

# Finalizar a transação SQL
[System.IO.File]::AppendAllText($sqlOutputPath, "COMMIT;`r`n", [System.Text.Encoding]::UTF8)

# Escrever arquivo JSON compactado
Write-Output "Salvando arquivo JSON otimizado..."
$jsonOut = ConvertTo-Json -InputObject $foodsList -Depth 5 -Compress
[System.IO.File]::WriteAllText($jsonOutputPath, $jsonOut, [System.Text.Encoding]::UTF8)

Write-Output "Processamento concluído!"
Write-Output "SQL gerado em: $sqlOutputPath"
Write-Output "JSON gerado em: $jsonOutputPath"

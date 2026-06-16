# Servidor Web Simples em PowerShell para Hospedar a Aplicação Localmente
# Para evitar erros de CORS ao buscar o arquivo alimentos.json

$port = 8000
$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://localhost:$port/")

try {
    $listener.Start()
    Write-Output "=================================================="
    Write-Output " TBCA Explorer - Servidor Ativo!"
    Write-Output " Acesse no navegador: http://localhost:$port/"
    Write-Output " Pressione Ctrl+C neste terminal para encerrar."
    Write-Output "=================================================="
    
    while ($listener.IsListening) {
        $context = $listener.GetContext()
        $request = $context.Request
        $response = $context.Response
        
        $localPath = $request.Url.LocalPath.TrimStart('/')
        if ([string]::IsNullOrEmpty($localPath)) {
            $localPath = "index.html"
        }
        
        # Obter caminho absoluto do arquivo no diretório de trabalho do script
        $scriptPath = Split-Path $MyInvocation.MyCommand.Path -Parent
        $filePath = Join-Path $scriptPath $localPath
        
        if (Test-Path $filePath -PathType Leaf) {
            $bytes = [System.IO.File]::ReadAllBytes($filePath)
            $ext = [System.IO.Path]::GetExtension($filePath).ToLower()
            
            $contentType = switch ($ext) {
                ".html" { "text/html; charset=utf-8" }
                ".css"  { "text/css; charset=utf-8" }
                ".js"   { "application/javascript; charset=utf-8" }
                ".json" { "application/json; charset=utf-8" }
                ".svg"  { "image/svg+xml; charset=utf-8" }
                default { "application/octet-stream" }
            }
            
            $response.ContentType = $contentType
            $response.ContentLength64 = $bytes.Length
            $response.OutputStream.Write($bytes, 0, $bytes.Length)
        } else {
            # Arquivo não encontrado (404)
            $response.StatusCode = 404
            $errBytes = [System.Text.Encoding]::UTF8.GetBytes("404 - Arquivo nao encontrado")
            $response.ContentType = "text/plain; charset=utf-8"
            $response.ContentLength64 = $errBytes.Length
            $response.OutputStream.Write($errBytes, 0, $errBytes.Length)
        }
        $response.OutputStream.Close()
    }
}
catch {
    Write-Error "Ocorreu um erro no servidor: $_"
}
finally {
    $listener.Close()
}

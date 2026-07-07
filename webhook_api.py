"""
Servidor de API Exemplo para Webhooks do Mercado Pago
Este arquivo demonstra como expor um endpoint HTTP para receber os Webhooks do Mercado Pago
e integrá-lo com a lógica de créditos do Rotulei App.

Como rodar localmente:
1. Instale o FastAPI e Uvicorn:
   pip install fastapi uvicorn
2. Execute o servidor:
   uvicorn webhook_api:app --host 0.0.0.0 --port 8000
"""

import threading
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from utils.webhook_handler import process_mercado_pago_webhook

app = FastAPI(title="Rotulei App - Webhook API")

# Lock para sincronização de concorrência com o arquivo JSON
db_lock = threading.RLock()

def get_mercado_pago_access_token():
    import os
    import re
    # 1. Environment Variable
    token = os.environ.get("MERCADOPAGO_ACCESS_TOKEN")
    if token:
        return token
    # 2. .streamlit/secrets.toml
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        secrets_path = os.path.join(base_dir, ".streamlit", "secrets.toml")
        if os.path.exists(secrets_path):
            with open(secrets_path, "r", encoding="utf-8") as f:
                content = f.read()
            match = re.search(r'MERCADOPAGO_ACCESS_TOKEN\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                return match.group(1)
    except Exception:
        pass
    # 3. Streamlit secrets (if available)
    try:
        import streamlit as st
        token = st.secrets.get("MERCADOPAGO_ACCESS_TOKEN")
        if token:
            return token
    except Exception:
        pass
    return "TEST-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"

MERCADO_PAGO_ACCESS_TOKEN = get_mercado_pago_access_token()

@app.post("/webhooks/mercadopago")
async def mercado_pago_webhook(request: Request):
    """
    Recebe notificações de pagamento do Mercado Pago (Webhooks)
    """
    try:
        # 1. Obter o corpo da requisição em JSON
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Payload inválido")
    
    # 2. Processar a notificação usando o handler
    # O handler fará a busca na API do Mercado Pago usando o ACCESS_TOKEN para confirmar o status
    success, message = process_mercado_pago_webhook(
        webhook_payload=payload,
        db_lock=db_lock,
        access_token=MERCADO_PAGO_ACCESS_TOKEN
    )
    
    if success:
        return JSONResponse(status_code=200, content={"status": "success", "message": message})
    else:
        # Retornamos 200/202 para o Mercado Pago não ficar reenviando se for um erro de negócio normal
        # (como pagamento com outro status que não seja aprovado)
        return JSONResponse(status_code=200, content={"status": "ignored/failed", "message": message})

@app.get("/")
def read_root():
    return {"status": "running", "info": "Rotulei App Webhook Endpoint"}

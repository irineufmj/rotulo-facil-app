"""
Servidor de API Exemplo para Webhooks do Mercado Pago
Este arquivo demonstra como expor um endpoint HTTP para receber os Webhooks do Mercado Pago
e integrá-lo com a lógica de créditos do Rótulo Fácil.

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

app = FastAPI(title="Rótulo Fácil - Webhook API")

# Lock para sincronização de concorrência com o arquivo JSON
db_lock = threading.RLock()

# Defina seu ACCESS_TOKEN do Mercado Pago nas variáveis de ambiente ou substitua aqui
MERCADO_PAGO_ACCESS_TOKEN = "TEST-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"

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
    return {"status": "running", "info": "Rótulo Fácil Webhook Endpoint"}

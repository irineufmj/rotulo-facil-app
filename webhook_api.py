"""
Servidor de API para Webhooks do Mercado Pago - Rotulei App
Expõe um endpoint HTTP seguro para receber notificações de pagamento.

Como rodar localmente:
1. Instale o FastAPI e Uvicorn:
   pip install fastapi uvicorn
2. Configure a variável de ambiente:
   set MERCADOPAGO_ACCESS_TOKEN=APP_USR-...
3. Execute o servidor:
   uvicorn webhook_api:app --host 0.0.0.0 --port 8000
"""

import hmac
import hashlib
import threading
import logging
import os
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from typing import Optional
from utils.webhook_handler import process_mercado_pago_webhook

logger = logging.getLogger(__name__)

app = FastAPI(title="Rotulei App - Webhook API")

# Lock para sincronização de concorrência com o arquivo JSON/SQL
db_lock = threading.RLock()


def get_mercado_pago_access_token() -> str:
    """
    Carrega o Access Token do Mercado Pago de forma segura, sem fallback hardcoded.
    Fontes (em ordem de prioridade):
      1. Variável de ambiente MERCADOPAGO_ACCESS_TOKEN
      2. Streamlit Secrets (st.secrets)
      3. Arquivo .streamlit/secrets.toml (parse manual)
    Levanta ValueError se nenhuma fonte estiver configurada.
    """
    import re

    # 1. Variável de ambiente
    token = os.environ.get("MERCADOPAGO_ACCESS_TOKEN")
    if token and token.strip():
        return token.strip()

    # 2. Streamlit secrets
    try:
        import streamlit as st
        token = st.secrets.get("MERCADOPAGO_ACCESS_TOKEN")
        if token and str(token).strip():
            return str(token).strip()
    except Exception:
        pass

    # 3. Leitura direta do secrets.toml (ambiente não-Streamlit, ex: uvicorn local)
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        secrets_path = os.path.join(base_dir, ".streamlit", "secrets.toml")
        if os.path.exists(secrets_path):
            with open(secrets_path, "r", encoding="utf-8") as f:
                content = f.read()
            match = re.search(r'MERCADOPAGO_ACCESS_TOKEN\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                return match.group(1).strip()
    except Exception:
        pass

    # Nenhuma fonte configurada — falha explícita e segura
    raise ValueError(
        "MERCADOPAGO_ACCESS_TOKEN não configurado! "
        "Defina a variável de ambiente ou configure em st.secrets antes de iniciar o servidor."
    )


def get_mercado_pago_webhook_secret() -> str:
    """
    Carrega a chave secreta do webhook do Mercado Pago (usada para validação HMAC).
    Disponível no painel do MP: Webhooks > Chave Secreta.
    """
    secret = os.environ.get("MERCADOPAGO_WEBHOOK_SECRET")
    if secret and secret.strip():
        return secret.strip()
    try:
        import streamlit as st
        secret = st.secrets.get("MERCADOPAGO_WEBHOOK_SECRET")
        if secret and str(secret).strip():
            return str(secret).strip()
    except Exception:
        pass
    return ""  # Sem chave = assinatura ignorada com aviso (modo de compatibilidade)


def verify_mp_signature(
    request_id: str,
    payload_id: str,
    ts: str,
    v1_signature: str,
    webhook_secret: str
) -> bool:
    """
    Valida a assinatura HMAC-SHA256 enviada pelo Mercado Pago no header x-signature.

    O Mercado Pago assina as notificações com a fórmula:
      manifest = "id:{data.id};request-id:{x-request-id};ts:{ts};"
      signature = HMAC-SHA256(webhook_secret, manifest)

    Referência: https://www.mercadopago.com.br/developers/pt/docs/your-integrations/notifications/webhooks
    """
    if not webhook_secret:
        return False
    manifest = f"id:{payload_id};request-id:{request_id};ts:{ts};"
    computed = hmac.new(
        webhook_secret.encode("utf-8"),
        manifest.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, v1_signature)


def parse_x_signature(x_signature: str) -> dict:
    """
    Faz parse do header x-signature do Mercado Pago.
    Formato: 'ts=<timestamp>,v1=<hash>'
    Retorna dict com as chaves extraídas.
    """
    result = {}
    if not x_signature:
        return result
    for part in x_signature.split(","):
        part = part.strip()
        if "=" in part:
            key, _, value = part.partition("=")
            result[key.strip()] = value.strip()
    return result


# Carregar token na inicialização — levanta ValueError se não configurado
try:
    MERCADO_PAGO_ACCESS_TOKEN = get_mercado_pago_access_token()
    logger.info("Mercado Pago Access Token carregado com sucesso.")
except ValueError as e:
    logger.critical(str(e))
    # Re-raise para impedir que o servidor suba sem configuração
    raise


@app.post("/webhooks/mercadopago")
async def mercado_pago_webhook(
    request: Request,
    x_signature: Optional[str] = Header(None, alias="x-signature"),
    x_request_id: Optional[str] = Header(None, alias="x-request-id"),
):
    """
    Recebe e valida notificações de pagamento do Mercado Pago (Webhooks).

    Segurança:
    - Valida assinatura HMAC-SHA256 via header x-signature (quando MERCADOPAGO_WEBHOOK_SECRET estiver configurado).
    - Rejeita requisições com assinatura inválida com HTTP 401.
    - Consulta a API do Mercado Pago para confirmar o status real do pagamento.
    """
    # 1. Obter corpo da requisição
    try:
        body_bytes = await request.body()
        import json as _json
        payload = _json.loads(body_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Payload inválido ou não é JSON.")

    # 2. Validação de assinatura HMAC (se o secret estiver configurado)
    webhook_secret = get_mercado_pago_webhook_secret()
    if webhook_secret:
        if not x_signature:
            logger.warning("Webhook recebido sem header x-signature. Requisição bloqueada.")
            raise HTTPException(
                status_code=401,
                detail="Header x-signature ausente. Acesso não autorizado."
            )

        sig_parts = parse_x_signature(x_signature)
        ts = sig_parts.get("ts", "")
        v1 = sig_parts.get("v1", "")
        payload_id = str(payload.get("data", {}).get("id", ""))

        if not ts or not v1:
            logger.warning("Header x-signature malformado. Requisição bloqueada.")
            raise HTTPException(
                status_code=401,
                detail="Assinatura malformada. Acesso não autorizado."
            )

        is_valid = verify_mp_signature(
            request_id=x_request_id or "",
            payload_id=payload_id,
            ts=ts,
            v1_signature=v1,
            webhook_secret=webhook_secret
        )

        if not is_valid:
            logger.warning(
                f"Assinatura HMAC inválida para webhook payload_id={payload_id}. "
                "Possível tentativa de forjamento de pagamento bloqueada."
            )
            raise HTTPException(
                status_code=401,
                detail="Assinatura inválida. Acesso não autorizado."
            )
    else:
        # Modo de compatibilidade: sem secret configurado, apenas loga aviso
        logger.warning(
            "ATENÇÃO: MERCADOPAGO_WEBHOOK_SECRET não configurado. "
            "A validação HMAC está desabilitada. Configure o secret para segurança máxima."
        )

    # 3. Processar o webhook após validação
    success, message = process_mercado_pago_webhook(
        webhook_payload=payload,
        db_lock=db_lock,
        access_token=MERCADO_PAGO_ACCESS_TOKEN
    )

    if success:
        return JSONResponse(status_code=200, content={"status": "success", "message": message})
    else:
        # Retorna 200 para o Mercado Pago não reenviar em casos de negócio esperados
        # (ex: status "pending" ou pagamento já processado)
        return JSONResponse(status_code=200, content={"status": "ignored", "message": message})


@app.get("/")
def read_root():
    return {"status": "running", "info": "Rotulei App Webhook Endpoint — Seguro"}

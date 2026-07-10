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
import json as _json
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from typing import Optional
from utils.webhook_handler import process_mercado_pago_webhook

# Configuração básica de logging para o console
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("webhook_api")

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

    Nota de Segurança: data.id DEVE ser convertido para letras minúsculas (lowercase).
    """
    logger.info(
        f"[HMAC-Diag] Iniciando validacao: request_id='{request_id}', "
        f"payload_id='{payload_id}', ts='{ts}', v1='{v1_signature[:10]}...'"
    )
    if not webhook_secret:
        logger.warning("[HMAC-Diag] Webhook secret nao configurado!")
        return False
        
    # Conversão obrigatória do ID do recurso para letras minúsculas
    payload_id_lower = payload_id.lower()
    manifest = f"id:{payload_id_lower};request-id:{request_id};ts:{ts};"
    logger.info(f"[HMAC-Diag] Manifest reconstruido: '{manifest}'")
    
    computed = hmac.new(
        webhook_secret.encode("utf-8"),
        manifest.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    logger.info(f"[HMAC-Diag] HMAC local computado: '{computed[:10]}...'")
    
    is_valid = hmac.compare_digest(computed, v1_signature)
    logger.info(f"[HMAC-Diag] Resultado final da validacao: {is_valid}")
    return is_valid


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
@app.post("/webhooks/mercadopago/")
async def mercado_pago_webhook(
    request: Request,
    x_signature: Optional[str] = Header(None, alias="x-signature"),
    x_request_id: Optional[str] = Header(None, alias="x-request-id"),
):
    """
    Recebe e valida notificações de pagamento do Mercado Pago (Webhooks).

    Segurança:
    - Valida assinatura HMAC-SHA256 via header x-signature (quando MERCADOPAGO_WEBHOOK_SECRET estiver configurado).
    - Rejeita requisições com assinatura inválida com HTTP 401 (apenas para pagamentos legítimos).
    - Consulta a API do Mercado Pago para confirmar o status real do pagamento.
    """
    logger.info(f"[Webhook-API] Recebida notificacao. x-signature='{x_signature}', x-request-id='{x_request_id}'")

    # 1. Obter corpo da requisição de forma resiliente
    body_bytes = b""
    try:
        body_bytes = await request.body()
        payload = _json.loads(body_bytes)
        logger.info(f"[Webhook-API] Payload JSON decodificado com sucesso: {payload}")
    except Exception as e:
        logger.error(f"[Webhook-API] Erro ao decodificar payload JSON: {e}. Raw Bytes: {body_bytes}")
        raise HTTPException(status_code=400, detail=f"Payload inválido ou não é JSON: {e}")

    # Detectar se é uma notificação de pagamento legítima (para forçar validação de assinatura)
    is_payment = (
        payload.get("type") == "payment" 
        or payload.get("action", "").startswith("payment.")
        or "payment_id" in payload
    )

    # 2. Validação de assinatura HMAC (se o secret estiver configurado)
    webhook_secret = get_mercado_pago_webhook_secret()
    if webhook_secret:
        if not x_signature:
            if is_payment:
                logger.warning("[Webhook-API] Requisicao de pagamento bloqueada: Header x-signature ausente.")
                raise HTTPException(
                    status_code=401,
                    detail="Header x-signature ausente. Acesso não autorizado."
                )
            else:
                logger.info("[Webhook-API] Evento de teste/mp-connect recebido sem assinatura. Ignorado com sucesso.")
        else:
            sig_parts = parse_x_signature(x_signature)
            ts = sig_parts.get("ts", "")
            v1 = sig_parts.get("v1", "")

            # Fallback robusto para extração do ID de recurso no payload
            payload_id = ""
            if payload.get("data") and isinstance(payload.get("data"), dict):
                payload_id = str(payload.get("data", {}).get("id", ""))
            if not payload_id and payload.get("id"):
                payload_id = str(payload.get("id", ""))
            if not payload_id and payload.get("payment_id"):
                payload_id = str(payload.get("payment_id", ""))

            if not ts or not v1:
                if is_payment:
                    logger.warning("[Webhook-API] Requisicao de pagamento bloqueada: Header x-signature malformado.")
                    raise HTTPException(
                        status_code=401,
                        detail="Assinatura malformada. Acesso não autorizado."
                    )
                else:
                    logger.info("[Webhook-API] Assinatura malformada em evento de teste (ignorado com sucesso).")
            else:
                is_valid = verify_mp_signature(
                    request_id=x_request_id or "",
                    payload_id=payload_id,
                    ts=ts,
                    v1_signature=v1,
                    webhook_secret=webhook_secret
                )

                if not is_valid:
                    if is_payment:
                        logger.warning(
                            f"[Webhook-API] Assinatura HMAC invalida para webhook payload_id={payload_id}. "
                            "Tentativa de forjamento bloqueada com HTTP 401."
                        )
                        raise HTTPException(
                            status_code=401,
                            detail="Assinatura inválida. Acesso não autorizado."
                        )
                    else:
                        logger.info(
                            f"[Webhook-API] Assinatura HMAC invalida para evento de teste payload_id={payload_id} "
                            "(ignorado com sucesso para permitir testes do painel MP)."
                        )
    else:
        logger.warning(
            "[Webhook-API] MERCADOPAGO_WEBHOOK_SECRET nao configurado. "
            "A validacao HMAC esta desabilitada. Configure a chave secreta para seguranca maxima."
        )

    # 3. Processar o webhook após validação
    success, message = process_mercado_pago_webhook(
        webhook_payload=payload,
        db_lock=db_lock,
        access_token=MERCADO_PAGO_ACCESS_TOKEN
    )

    logger.info(f"[Webhook-API] Resultado do processamento: success={success}, msg='{message}'")

    if success:
        return JSONResponse(status_code=200, content={"status": "success", "message": message})
    else:
        # Retorna 200 para o Mercado Pago não reenviar em casos de negócio normais
        # (ex: status "pending", evento de teste ou pagamento já processado)
        return JSONResponse(status_code=200, content={"status": "ignored", "message": message})


@app.get("/")
def read_root():
    return {"status": "running", "info": "Rotulei App Webhook Endpoint — Seguro"}

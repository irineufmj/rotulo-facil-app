import os
import json
import logging
import urllib.request
from utils.auth import load_users, save_users

logger = logging.getLogger(__name__)

def process_mercado_pago_webhook(webhook_payload: dict, db_lock, access_token: str = None) -> tuple:
    """
    Processa o webhook enviado pelo Mercado Pago.
    
    Regras de Negócio:
    1. Extrai o ID do pagamento da notificação.
    2. Consulta os detalhes do pagamento na API do Mercado Pago (se o access_token estiver disponível)
       ou processa o payload direto (caso seja um payload completo/mockado de simulação).
    3. Identifica o usuário pelo e-mail do pagador ou external_reference.
    4. Verifica se a transação está 'approved'.
    5. Evita processamento duplicado registrando o ID do pagamento nas transações processadas do usuário.
    6. Adiciona a quantidade de créditos comprados.
    
    Retorna: (sucesso: bool, mensagem: str)
    """
    payment_id = None
    
    # Mercado Pago envia o ID de formas diferentes dependendo do tipo de notificação
    if webhook_payload.get("type") == "payment":
        payment_id = webhook_payload.get("data", {}).get("id")
    elif "id" in webhook_payload and webhook_payload.get("action", "").startswith("payment."):
        payment_id = webhook_payload.get("data", {}).get("id")
    elif "payment_id" in webhook_payload:
        # Fallback de parâmetros diretos de teste
        payment_id = webhook_payload.get("payment_id")
    
    if not payment_id:
        # Se for um payload completo de pagamento já consultado (ex: mock ou consulta manual)
        if webhook_payload.get("status") and webhook_payload.get("payer", {}).get("email"):
            payment_details = webhook_payload
            payment_id = str(payment_details.get("id"))
        else:
            return False, "ID do pagamento não encontrado no payload do webhook."
    else:
        payment_id = str(payment_id)
        payment_details = None

    # Se tivermos access_token e não tivermos os detalhes, fazemos a requisição HTTP
    if access_token and not payment_details:
        try:
            url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Bearer {access_token}"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    payment_details = json.loads(response.read().decode("utf-8"))
                else:
                    return False, f"Erro ao consultar Mercado Pago API: HTTP {response.status}"
        except Exception as e:
            logger.error(f"Erro ao consultar pagamento {payment_id} no Mercado Pago: {e}", exc_info=True)
            return False, f"Falha na comunicação com Mercado Pago: {e}"

    if not payment_details:
        return False, f"Não foi possível obter os detalhes do pagamento para o ID: {payment_id}"

    # Extrair informações cruciais
    status = payment_details.get("status")
    payer_email = payment_details.get("payer", {}).get("email")
    external_ref = payment_details.get("external_reference")
    
    # Identificar a quantidade de créditos comprados
    # 1. Tentar ler de metadata.credits_to_add
    # 2. Tentar ler de external_reference se tiver formato 'user@email.com:credits'
    # 3. Tentar inferir da descrição (Ex: "Pacote de 10 créditos")
    # 4. Fallback padrão: 10 créditos
    credits_to_add = 10
    
    metadata = payment_details.get("metadata", {})
    if isinstance(metadata, dict) and "credits" in metadata:
        try:
            credits_to_add = int(metadata["credits"])
        except ValueError:
            pass
    elif isinstance(metadata, dict) and "credits_to_add" in metadata:
        try:
            credits_to_add = int(metadata["credits_to_add"])
        except ValueError:
            pass
    elif external_ref and ":" in external_ref:
        parts = external_ref.split(":")
        if len(parts) == 2:
            try:
                credits_to_add = int(parts[1])
            except ValueError:
                pass
            
    # Procurar pelo usuário (por external_reference primeiro, senão por e-mail)
    target_user_identifier = None
    if external_ref:
        if ":" in external_ref:
            target_user_identifier = external_ref.split(":")[0].strip().lower()
        else:
            target_user_identifier = external_ref.strip().lower()
    else:
        target_user_identifier = payer_email.strip().lower() if payer_email else None

    if not target_user_identifier:
        return False, "Identificador do usuário (e-mail/external_reference) não encontrado."

    if status != "approved":
        return False, f"Pagamento {payment_id} está com status '{status}'. Créditos não liberados."

    # Atualizar o banco de dados de usuários de forma segura com lock
    with db_lock:
        users = load_users(db_lock)
        user_found = None
        
        # Tenta achar por username ou email
        for u in users:
            u_email = u.get("email", "").strip().lower()
            u_name = u["username"].strip().lower()
            if u_name == target_user_identifier or u_email == target_user_identifier or u_email == payer_email.strip().lower():
                user_found = u
                break
                
        if not user_found:
            return False, f"Usuário correspondente a '{target_user_identifier}' não foi encontrado no sistema."

        # Evitar processamento duplicado
        if "transacoes_processadas" not in user_found:
            user_found["transacoes_processadas"] = []
            
        if payment_id in user_found["transacoes_processadas"]:
            return True, f"Créditos do pagamento {payment_id} já haviam sido aplicados anteriormente para o usuário '{user_found['username']}'."

        # Incrementar créditos
        old_credits = user_found.get("creditos_disponiveis", 0)
        user_found["creditos_disponiveis"] = old_credits + credits_to_add
        user_found["transacoes_processadas"].append(payment_id)
        
        # Salva o id da última transação também para histórico simples
        user_found["id_transacao_pagamento"] = payment_id

        if save_users(users, db_lock):
            logger.info(f"Sucesso: Adicionados {credits_to_add} créditos para o usuário '{user_found['username']}' (Transação: {payment_id})")
            return True, f"Sucesso: Adicionados {credits_to_add} créditos para o usuário '{user_found['username']}'."
        else:
            return False, "Erro ao salvar alterações no banco de dados de usuários."

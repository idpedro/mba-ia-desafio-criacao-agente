"""API HTTP do assistente (contrato do desafio)."""

import logging
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import banco, config
from .assistente import Assistente, ConfirmacaoNaoPendente, SessaoNaoEncontrada


class NovaSessao(BaseModel):
    apartamento: str


class SessaoCriada(BaseModel):
    session_id: str


class Mensagem(BaseModel):
    texto: str = Field(min_length=1)


class RespostaConfirmacao(BaseModel):
    id: str
    confirmado: bool


class ConfirmacaoPendente(BaseModel):
    id: str
    acao: str
    detalhes: dict[str, Any]


class RespostaAssistente(BaseModel):
    resposta: str
    confirmacoes_pendentes: list[ConfirmacaoPendente]


class ReservaOut(BaseModel):
    codigo: str
    area: str
    data: str


class VisitanteOut(BaseModel):
    nome: str
    data: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.assistente = Assistente()
    yield
    await app.state.assistente.fechar()


app = FastAPI(title="Assistente do Residencial Aurora", lifespan=lifespan)


@app.exception_handler(SessaoNaoEncontrada)
async def _sessao_nao_encontrada(_: Request, exc: SessaoNaoEncontrada):
    return JSONResponse(status_code=404, content={"detail": "Sessão não encontrada."})


@app.exception_handler(ConfirmacaoNaoPendente)
async def _confirmacao_nao_pendente(_: Request, exc: ConfirmacaoNaoPendente):
    return JSONResponse(
        status_code=409,
        content={"detail": "Não existe confirmação pendente com esse id nesta sessão."},
    )


def _assistente(request: Request) -> Assistente:
    return request.app.state.assistente


@app.post("/sessoes", status_code=201, response_model=SessaoCriada)
async def criar_sessao(corpo: NovaSessao, request: Request):
    apartamento = corpo.apartamento.strip()
    if apartamento not in banco.APARTAMENTOS:
        raise HTTPException(status_code=422, detail="Apartamento inexistente.")
    session_id = await _assistente(request).criar_sessao(apartamento)
    return {"session_id": session_id}


@app.post("/sessoes/{session_id}/mensagens", response_model=RespostaAssistente)
async def enviar_mensagem(session_id: str, corpo: Mensagem, request: Request):
    return await _assistente(request).enviar_mensagem(session_id, corpo.texto)


@app.post("/sessoes/{session_id}/confirmacoes", response_model=RespostaAssistente)
async def responder_confirmacao(
    session_id: str, corpo: RespostaConfirmacao, request: Request
):
    return await _assistente(request).responder_confirmacao(
        session_id, corpo.id, corpo.confirmado
    )


@app.get("/sessoes/{session_id}/eventos")
async def listar_eventos(session_id: str, request: Request) -> list[dict[str, Any]]:
    return await _assistente(request).eventos(session_id)


# Rotas de verificação: leem o banco direto, sem passar pelo modelo.


@app.get("/apartamentos/{numero}/reservas", response_model=list[ReservaOut])
async def reservas_do_apartamento(numero: str):
    return await banco.reservas_do_apartamento(numero)


@app.get("/apartamentos/{numero}/visitantes", response_model=list[VisitanteOut])
async def visitantes_do_apartamento(numero: str):
    return await banco.visitantes_do_apartamento(numero)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT)

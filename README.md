# Residencial Aurora: assistente virtual com Google ADK

API em Python (FastAPI + Google ADK 2.13.0 + Gemini) para o assistente dos moradores do Residencial Aurora. Pelo chat, o morador reserva e cancela áreas comuns, autoriza visitantes e tira dúvidas sobre o regulamento. O modelo conduz a conversa. As regras que não podem ser quebradas ficam no código: tools, banco e API.

```
src/residencial_aurora/
├── api.py              # rotas HTTP (contrato do desafio)
├── assistente.py       # Runner, sessões persistidas, confirmações pendentes
├── agentes/            # um módulo por agente
│   ├── principal.py    # assistente_aurora
│   ├── reservas.py     # especialista_reservas
│   ├── visitantes.py   # especialista_visitantes
│   ├── regulamento.py  # especialista_regulamento
│   └── _comum.py       # modelo Gemini (com retry) e regras de conduta
├── tools/              # as únicas que leem e gravam reservas e visitantes
│   ├── sessao.py       # de onde vem o apartamento (Garantia 2)
│   ├── reservas.py     # agenda, reservar, cancelar
│   ├── visitantes.py   # autorizar, listar
│   ├── regulamento.py  # ler_capitulo
│   └── validacao.py    # validação de datas
├── banco.py            # SQLite dos dados do condomínio
├── regulamento.py      # divisão do regulamento em capítulos
├── restaurar.py        # comando de restauração
└── config.py           # caminhos e variáveis do .env
```

## Arquitetura

```
                    ┌──────────────────────────────┐
  morador ──API──▶  │ assistente_aurora (principal)│
                    └──┬───────────┬───────────┬───┘
       transfer_to_agent│           │transfer    │ AgentTool
                        ▼           ▼            ▼
        especialista_reservas  especialista_   especialista_regulamento
        (reservar, cancelar,   visitantes      (lê 1 capítulo por vez,
         agenda, listar)       (autorizar,      em sessão aninhada)
                               listar)
```

| Agente | Responsabilidade | Como é acionado | Por quê |
|---|---|---|---|
| `assistente_aurora` | Conversa com o morador, responde cumprimentos e distribui o trabalho. Não tem tools de dados nem o regulamento nas instruções. | É o `root_agent` do `App` e recebe toda mensagem nova. | Um ponto de entrada só, com uma instrução curta. |
| `especialista_reservas` | Áreas, disponibilidade, reservar, cancelar e listar reservas do apartamento. | Sub-agente (`sub_agents`), por `transfer_to_agent`. | `reservar_area` pede confirmação (área com taxa), e o ADK só retoma a confirmação no agente que a pediu. Com `AgentTool` a sessão aninhada é descartada e a confirmação não pode ser retomada (o próprio ADK avisa isso em `agent_tool.py`). Por transferência, o pedido de confirmação fica na sessão do morador, com o especialista como autor, e o Runner devolve a resposta para ele. |
| `especialista_visitantes` | Autorizar visitantes e listar os autorizados do apartamento. | Sub-agente, por `transfer_to_agent`. | Mesmo motivo: `autorizar_visitante` sempre pede confirmação. |
| `especialista_regulamento` | Responde dúvidas lendo um capítulo do regulamento com `ler_capitulo`. | `AgentTool` na lista de tools do principal. | Ele não precisa de confirmação, então pode rodar isolado. As leituras de capítulo acontecem na sessão aninhada do `AgentTool` e só a resposta final volta à sessão do morador. Assim o texto do regulamento não entra no histórico. |

Os dois especialistas transferíveis usam `disallow_transfer_to_parent=True`. Depois que um deles responde, a próxima mensagem do morador volta ao agente principal, que decide de novo para onde ela vai. Os dois podem transferir entre si quando o pedido mistura reservas e visitantes. O modelo de cada agente vem do `.env` (`AURORA_MODELO_PRINCIPAL` e `AURORA_MODELO_ESPECIALISTAS`; o padrão é `gemini-3.8-flash`). As chamadas usam `HttpRetryOptions` para aguentar 429/503 do free tier.

Armazenamento: dois arquivos SQLite em `var/` (fora do Git), que sobrevivem ao reinício.
- `var/condominio.db`: reservas, visitantes, códigos já emitidos e o vínculo sessão → apartamento (`banco.py`). Os arquivos de `dados/` não são alterados: o comando de restauração copia o conteúdo deles para cá.
- `var/sessoes.db`: sessões e eventos do ADK (`SqliteSessionService`).

Fluxo de confirmação na API (`assistente.py`):
1. A tool chama `tool_context.request_confirmation(...)`. O ADK grava um evento com a chamada `adk_request_confirmation` e a execução para.
2. `confirmacoes_pendentes(sessao)` lista as chamadas `adk_request_confirmation` da sessão que ainda não têm resposta. É isso que aparece em `confirmacoes_pendentes`, com o `payload` da tool em `detalhes`.
3. `POST /sessoes/{id}/confirmacoes` valida o `id` contra essa lista e envia ao Runner um `FunctionResponse(name="adk_request_confirmation", id=..., response={"confirmed": ...})`. O Runner encontra o evento com essa chamada, roteia para o especialista autor, e o ADK executa de novo a tool original com `tool_context.tool_confirmation` preenchido.

## Garantias

### Garantia 1: cobrança ou acesso só com confirmação

- `src/residencial_aurora/tools/reservas.py`, `reservar_area`: quando `tool_context.tool_confirmation is None` e a área tem taxa (`info.gera_cobranca`), a tool chama `tool_context.request_confirmation(hint=..., payload={"area", "data", "taxa", ...})` e retorna `aguardando_confirmacao` sem gravar nada. Ela só chega em `banco.criar_reserva` quando `confirmacao.confirmed` é verdadeiro. Se for negado, retorna `nao_confirmada`. A quadra (taxa 0) grava direto, sem pedir confirmação.
- `src/residencial_aurora/tools/visitantes.py`, `autorizar_visitante`: sempre pede confirmação (`payload={"nome", "data"}`) e só chama `banco.autorizar_visitante` com `confirmacao.confirmed`.
- `src/residencial_aurora/assistente.py`, `confirmacoes_pendentes` e `Assistente.responder_confirmacao`: o `id` precisa estar entre os pedidos sem resposta **nos eventos daquela sessão**. Senão a função levanta `ConfirmacaoNaoPendente` antes de chamar o Runner, e `api.py` (`_confirmacao_nao_pendente`) responde `409`. Uma confirmação já respondida tem `FunctionResponse` gravado e sai da lista, então o reenvio recebe 409 e a ação não roda de novo. Uma trava por sessão (`self._travas`) serializa as execuções da mesma sessão.

Por que não depende do modelo: `tool_confirmation` só é preenchido pelo ADK a partir de um `FunctionResponse` `adk_request_confirmation` enviado como mensagem do usuário, e a única coisa que monta essa mensagem é a rota de confirmações. A rota de mensagens só envia texto. Escrever "já estou confirmando aqui" não preenche `tool_confirmation`: a tool pede confirmação de novo.

### Garantia 2: cada sessão pertence a um apartamento

- `src/residencial_aurora/assistente.py`, `Assistente.criar_sessao`: o apartamento do `POST /sessoes` vira o `user_id` da sessão do ADK e `state["apartamento"]`, e o vínculo é gravado em `sessoes` (`banco.vincular_sessao`). Nenhuma rota ou tool muda esses valores depois.
- `src/residencial_aurora/tools/sessao.py`, `apartamento_da_sessao`: todas as tools que tocam dados de um apartamento usam essa função, que lê `tool_context.user_id` e exige que ele seja igual a `state["apartamento"]`. **Nenhuma tool tem parâmetro de apartamento**, então o modelo não tem como escolher outro.
- `src/residencial_aurora/banco.py`: as consultas e o cancelamento filtram pelo apartamento no próprio SQL (`_cancelar_reserva`: `WHERE codigo = ? AND apartamento = ? AND status = 'ativa'`). `cancelar_reserva` em `tools/reservas.py` procura o alvo só entre as reservas do apartamento da sessão. Para reserva de outra unidade, ele responde "não há reserva ativa do seu apartamento com esses dados", sem confirmar que ela existe.
- `consultar_disponibilidade` e o caso `indisponivel` de `reservar_area` devolvem só `livre`/`ocupada`. O dono da reserva e o código nunca saem do banco.

### Garantia 3: nada se perde no reinício

- `src/residencial_aurora/assistente.py`, `Assistente.__init__`: `SqliteSessionService(str(config.SESSOES_PATH))` guarda sessões, state e eventos em `var/sessoes.db`, e `Runner(app=App(...), session_service=...)` lê de lá a cada mensagem.
- `src/residencial_aurora/banco.py`: reservas e visitantes ficam em `var/condominio.db` (SQLite, WAL). Subir a API não restaura nada. Só `aurora-restaurar` faz isso.
- Uma confirmação pedida antes do reinício pode ser aprovada depois dele: a lista de pendências e o roteamento do Runner saem dos eventos persistidos.
- Códigos de reserva: `banco._criar_reserva` sorteia `RSV-XXXXXX` e grava o código em `codigos_emitidos` (chave primária) na mesma transação da reserva. Essa tabela nunca é limpa, nem pela restauração. Reservas canceladas também não são apagadas (`status = 'cancelada'`). Assim, um código nunca se repete.

### Garantia 4: o regulamento é consultado, não carregado

- `src/residencial_aurora/agentes/principal.py`, `criar_agente_principal`: a instrução do principal não tem o regulamento, só a orientação de chamar a tool `especialista_regulamento`.
- `src/residencial_aurora/agentes/regulamento.py`, `criar_especialista_regulamento`: o especialista recebe só o índice (`regulamento.indice()`, números e títulos) e lê **um capítulo por vez** com `ler_capitulo` (`src/residencial_aurora/tools/regulamento.py`, que usa `src/residencial_aurora/regulamento.py`).
- O especialista é um `AgentTool`. As chamadas a `ler_capitulo` e o texto do capítulo ficam na sessão aninhada em memória do `AgentTool`, que é descartada. Na sessão do morador entram só a chamada `especialista_regulamento` e a resposta curta. Por isso nenhum evento da sessão contém capítulos que tratam de outros assuntos, e o regulamento não vai junto nas mensagens seguintes.

### Garantia 5: dois moradores, uma reserva

- `src/residencial_aurora/banco.py`, `SCHEMA`:

  ```sql
  CREATE UNIQUE INDEX IF NOT EXISTS ux_reservas_area_data_ativa
      ON reservas (area, data) WHERE status = 'ativa';
  ```

- `src/residencial_aurora/banco.py`, `_criar_reserva`: o `INSERT` acontece dentro de `BEGIN IMMEDIATE`. Se outra reserva ativa para a mesma área e data já entrou, o SQLite recusa o próprio `INSERT` com `IntegrityError`. A função converte isso em `DataIndisponivel`, e `reservar_area` devolve `indisponivel`, que a API responde normalmente com `200`.

Por que não depende de uma conferência prévia: `reservar_area` também consulta a agenda antes de pedir confirmação, mas isso serve só para dar uma resposta melhor ao morador. Quem garante a exclusividade é o índice único parcial, avaliado no instante da gravação. Num teste com 64 threads gravando a mesma área e data ao mesmo tempo, exatamente uma venceu. Reservas canceladas saem do índice (`WHERE status = 'ativa'`), então a data volta a ficar livre.

## Como rodar

Pré-requisitos:
- Python 3.12+ e [uv](https://docs.astral.sh/uv/).
- Uma chave do Google AI Studio (https://aistudio.google.com/apikey).
- Nenhum serviço externo: o armazenamento é SQLite local em `var/`.

Variáveis do `.env` (copie de `.env.example`):

| Variável | Obrigatória | Descrição |
|---|---|---|
| `GOOGLE_API_KEY` | sim | Chave do Google AI Studio. |
| `GOOGLE_GENAI_USE_VERTEXAI` | não | Deixe vazio ou `FALSE` para usar o AI Studio. |
| `AURORA_MODELO_PRINCIPAL` | não | Modelo do agente principal. Padrão: `gemini-3.8-flash`. |
| `AURORA_MODELO_ESPECIALISTAS` | não | Modelo dos especialistas. Padrão: o mesmo do principal. |

Passo a passo:

```bash
cp .env.example .env        # e preencha GOOGLE_API_KEY
uv sync

# Restaura reservas e visitantes ao estado de dados/ (cria var/ se preciso)
uv run aurora-restaurar
# (opcional) restaura e também apaga sessões e eventos
uv run aurora-restaurar --sessoes

# Sobe a API em http://localhost:8000 (Ctrl+C para parar)
uv run aurora-api
```

Exemplo rápido:

```bash
curl -s -X POST localhost:8000/sessoes -H 'content-type: application/json' -d '{"apartamento": "101"}'
curl -s -X POST localhost:8000/sessoes/<session_id>/mensagens -H 'content-type: application/json' \
  -d '{"texto": "Reserve o salão de festas para 2030-04-20"}'
curl -s -X POST localhost:8000/sessoes/<session_id>/confirmacoes -H 'content-type: application/json' \
  -d '{"id": "<id da confirmação>", "confirmado": true}'
curl -s localhost:8000/apartamentos/101/reservas
```

Rotas:

| Método e caminho | Resposta |
|---|---|
| `POST /sessoes` | `201 {"session_id"}` (`422` para apartamento inexistente) |
| `POST /sessoes/{id}/mensagens` | `200 {"resposta", "confirmacoes_pendentes"}`, `404` |
| `POST /sessoes/{id}/confirmacoes` | `200` (mesmo formato), `409` se o `id` não está pendente nesta sessão, `404` |
| `GET /sessoes/{id}/eventos` | `200` lista completa de eventos, `404` |
| `GET /apartamentos/{n}/reservas` | `200 [{"codigo", "area", "data"}]` (reservas ativas) |
| `GET /apartamentos/{n}/visitantes` | `200 [{"nome", "data"}]` |

O diretório de dados pode ser trocado com `AURORA_VAR_DIR`, e a porta com `AURORA_PORT`.

# Arquitetura Desejada

## Objetivo

Este documento formaliza a arquitetura desejada para evoluir a POC atual em uma solucao mais sustentavel e utilizavel por clientes como um bot do Slack.

A direcao desejada e separar claramente:

- ingestao e indexacao
- armazenamento persistente de contexto
- consulta e geracao de resposta
- integracao com clientes externos

## Visao geral

O sistema deve possuir dois fluxos principais:

1. **Fluxo de indexacao**
   Responsavel por alimentar e atualizar a base de conhecimento.

2. **Fluxo de consulta**
   Responsavel por responder perguntas com base no contexto indexado.

## Arquitetura alvo

```text
Repositorios Git
    |
    | bootstrap / merge em main / mudancas estruturais
    v
Pipeline de ingestao
    |
    v
RDS Postgres + pgvector
    |
    | consulta estruturada
    v
API de impacto (FastAPI)
    |
    v
Bot do Slack / outros clientes
```

## 1. Camada de ingestao

### Responsabilidade

Essa camada sera responsavel por:

- fazer a ingestao inicial completa
- processar apenas os arquivos alterados em fluxos incrementais
- recalcular embeddings
- recalcular relacoes entre artefatos
- manter a base persistente no RDS consistente

### Tipos de ingestao

#### Ingestao inicial

Usada para bootstrap da base.

Objetivo:

- indexar todos os arquivos suportados
- popular `artifact_files`
- popular `artifact_chunks`
- popular `artifact_relations`

#### Ingestao incremental

Usada apos alteracoes no codigo.

Objetivo:

- detectar arquivos alterados
- reprocessar somente o delta
- remover arquivos deletados
- atualizar apenas os artefatos e relacoes impactados

### Gatilhos recomendados

#### Merge em `main`

Esse deve ser o gatilho principal da base oficial.

Motivo:

- a branch `main` representa o estado consolidado do sistema
- o indice oficial deve refletir o codigo que realmente esta valendo

#### Bootstrap manual

Executado quando:

- a base estiver vazia
- houver necessidade de reconstruir o indice
- houver mudancas grandes de esquema ou de estrategia de extração

#### Evolucao futura: PR analysis

Pode existir no futuro uma indexacao isolada por PR, mas isso nao e obrigatorio no primeiro momento.

Recomendacao:

- primeiro consolidar bem o indice oficial de `main`
- depois evoluir para analise de impacto de PR em escopo separado

## 2. Camada de armazenamento

### Tecnologia recomendada

- **RDS Postgres**
- extensao **pgvector**

### Motivo da escolha

Essa base deve ser persistente porque:

- o bot do Slack precisa responder rapidamente
- nao faz sentido reindexar tudo durante a pergunta
- o indice precisa estar pronto antes da consulta
- embeddings, chunks e relacoes devem permanecer vivos entre execucoes

### Estruturas atuais

O banco deve manter, no minimo:

- `artifact_files`
- `artifact_chunks`
- `artifact_relations`

### Papel de cada tabela

#### `artifact_files`

Controla o estado por arquivo.

Serve para:

- detectar mudanca por `content_hash`
- suportar indexacao incremental
- controlar arquivos deletados

#### `artifact_chunks`

Guarda os artefatos extraidos por bloco.

Serve para:

- busca vetorial
- busca lexical
- montagem de contexto
- explicacao de impacto por bloco

#### `artifact_relations`

Guarda dependencias entre artefatos.

Serve para:

- explicar propagacao de impacto
- responder quem consome o que
- expandir contexto com mais confianca

## 3. Camada de consulta

### Objetivo

Essa camada nao deve fazer ingestao.

Ela deve apenas:

- receber a pergunta
- buscar os artefatos mais relevantes
- expandir o contexto com relacoes
- montar o prompt/contexto
- chamar o LLM final
- devolver a resposta ao cliente

### Recomendacao de tecnologia

- **FastAPI**

### Motivos

- simples de operar
- excelente integracao com Python
- permite tipagem e validacao
- facil de documentar
- facil de integrar com Slack
- serve como interface padrao para qualquer cliente

## 4. API recomendada

### Objetivo da API

Encapsular a logica que hoje esta distribuida no `mcp_tool.py` e expor isso como servico reutilizavel.

### Endpoint minimo recomendado

#### `POST /impact/query`

Entrada:

```json
{
  "question": "Quem consome dados de usuários criados recentemente?"
}
```

Saida esperada:

```json
{
  "answer": "texto final",
  "teams_affected": ["application", "data", "etl"],
  "files_affected": ["..."],
  "artifacts": [],
  "relations_used": []
}
```

### Endpoints recomendados para evolucao

#### `GET /health`

Para monitoramento e readiness.

#### `POST /impact/query/debug`

Para retornar:

- chunks usados
- relacoes usadas
- sinais de busca
- contexto enviado ao LLM

Isso ajuda muito em observabilidade.

#### `POST /impact/pr`

Futuro endpoint para analise isolada de PR, caso seja implementado um escopo separado de indexacao.

## 5. Camada de cliente

### Cliente inicial desejado

- bot do Slack

### Papel do bot

O bot nao deve:

- falar com o banco diretamente
- executar ingestao
- ter logica de busca ou relacoes embutida

O bot deve apenas:

- receber a pergunta do usuario
- chamar a API de impacto
- receber a resposta
- apresentar a resposta no Slack

### Beneficios desse desenho

- desacopla UI da logica
- facilita troca de cliente no futuro
- permite testar a API independentemente do Slack
- evita acoplamento do bot com o pipeline de indexacao

## 6. Responsabilidades por camada

### Pipeline de ingestao

Responsavel por:

- ler o codigo
- extrair artefatos
- gerar embedding
- gerar relacoes
- persistir tudo no banco

### RDS

Responsavel por:

- persistir o indice
- permitir busca vetorial
- permitir recuperacao de relacoes

### API FastAPI

Responsavel por:

- consultar o indice
- montar contexto
- chamar o LLM final
- devolver a resposta

### Bot do Slack

Responsavel por:

- receber a interacao do usuario
- encaminhar para a API
- apresentar o resultado

## 7. Fluxo operacional desejado

### Fluxo de ingestao oficial

```text
1. Codigo mergeado em main
2. Workflow detecta arquivos alterados
3. ingest.py reindexa o delta
4. artifact_files e atualizado
5. artifact_chunks e atualizado
6. artifact_relations e recalculado
7. Base oficial permanece pronta para consultas
```

### Fluxo de consulta pelo Slack

```text
1. Usuario pergunta algo no Slack
2. Bot envia a pergunta para a API
3. API busca chunks e relacoes no RDS
4. API monta contexto
5. API chama o LLM final
6. API retorna a resposta
7. Bot responde no Slack
```

## 8. O que manter e o que evoluir

### O que a arquitetura atual ja atende bem

- ingestao incremental por arquivo
- persistencia de artefatos
- relacoes heuristicas entre artefatos
- base persistente em Postgres
- uso de embeddings locais

### O que deve evoluir

- transformar `mcp_tool.py` em servico reutilizavel
- expor essa logica via FastAPI
- desacoplar cada vez mais ingestao e consulta
- adicionar melhores relacoes e mais metadados estruturados
- melhorar observabilidade para uso operacional

## 9. Recomendacoes de implementacao

### Curto prazo

1. consolidar a indexacao oficial em `main`
2. manter o RDS como base persistente oficial
3. refatorar a logica de consulta para um servico
4. criar a API FastAPI
5. integrar o Slack com a API

### Medio prazo

1. enriquecer `artifact_relations`
2. adicionar metadados como `layer`, `operation`, `domain_entity`
3. oferecer modo debug das respostas
4. adicionar analise especifica por PR

### Longo prazo

1. suportar escopos de indexacao
2. suportar docs e contratos como fontes
3. evoluir relacoes para um mapa de dependencias mais rico

## 10. Decisoes recomendadas

### Recomendacao principal

**Usar ingestao inicial + incremental para alimentar um RDS persistente, e expor a consulta por uma API FastAPI consumida pelo bot do Slack.**

### Motivos

- separa responsabilidades de forma saudavel
- favorece desempenho na consulta
- simplifica integracao com clientes
- evita acoplamento do bot com banco ou pipeline
- prepara o sistema para uso real

## Resumo final

A arquitetura desejada e:

- `main` alimenta a base oficial
- o RDS guarda arquivos, chunks e relacoes
- a API consulta o indice e chama o LLM final
- o Slack bot consome a API

Essa e a forma mais sustentavel de evoluir a POC para algo utilizavel por outras interfaces sem perder a base tecnica que ja foi construida.

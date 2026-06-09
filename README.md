# POC: RAG de Contexto Estruturado para Analise de Impacto

## Objetivo

Este projeto implementa uma prova de conceito para responder perguntas de impacto tecnico a partir de:

- codigo fonte de multiplos repositorios e times
- indexacao estruturada de artefatos
- embeddings locais para busca semantica
- relacoes persistidas entre artefatos
- consolidacao de contexto para um LLM gerar a resposta final

A ideia central e conseguir responder perguntas como:

- se eu remover uma coluna, quem quebra?
- quais times consomem esse dado?
- quais jobs, pipelines e integracoes dependem desse artefato?
- o que mudou em um PR e qual o impacto tecnico disso?

## O que foi implementado

### 1. Estrutura multi-repo e multi-time

O dataset de exemplo foi reorganizado para o formato:

```text
sample_projects/<repo>/<team>/...
```

Exemplos atuais:

- `customer-api / application`
- `analytics-platform / data`
- `etl-orchestrator / etl`
- `billing-engine / finance`
- `notification-center / application`

Isso permite que a indexacao preserve contexto de ownership, fronteiras entre times e dependencias cruzadas entre sistemas.

### 2. Ingestao estruturada com LLM

O `ingest.py` faz a leitura dos arquivos suportados:

- `.js`
- `.ts`
- `.prisma`

Para cada arquivo, o pipeline pede ao modelo que extraia artefatos com:

- nome
- tipo
- linhas
- tabelas referenciadas
- colunas referenciadas
- resumo do bloco
- codigo exato do bloco

Esses artefatos sao persistidos na tabela `artifact_chunks`.

### 3. Embedding local

Em vez de depender de embedding remoto, o projeto usa `HashingVectorizer` com 384 dimensoes.

Isso traz duas vantagens:

- evita custo adicional de embedding por API
- mantem compatibilidade com `pgvector` no banco

### 4. Busca hibrida para recuperacao de contexto

O `mcp_tool.py` foi evoluido para usar:

- busca vetorial com `pgvector`
- busca lexical complementar por termos relevantes

Isso melhora o recall para perguntas em linguagem natural que podem nao bater diretamente com nomes exatos no codigo.

### 5. Relatorio final com OpenRouter

O relatorio de impacto nao depende mais de um `LLM_ENDPOINT` externo.

Hoje o `mcp_tool.py` chama o OpenRouter diretamente com:

- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL`

O LLM recebe:

- a pergunta do usuario
- contexto estruturado
- artefatos relevantes
- mapa de impacto consolidado

Se a chamada falhar, o sistema ainda possui fallback local.

### 6. Indexacao incremental por arquivo

O `ingest.py` nao faz mais apenas append cego.

Foi implementado um controle incremental com:

- tabela `artifact_files`
- `content_hash` por arquivo
- `status` (`active` ou `deleted`)
- `last_indexed_at`

Com isso:

- arquivos sem mudanca sao pulados
- arquivos alterados sao reprocessados
- chunks antigos do arquivo sao removidos e substituidos
- arquivos deletados podem ser removidos do indice

### 7. Fluxo orientado a PR

Foi criado o script `index_pr.py`, que:

- le o diff entre `base-ref` e `head-ref`
- identifica arquivos adicionados, modificados e deletados
- chama o `ingest.py` apenas para o delta relevante

Esse e o primeiro passo para integrar a indexacao com CI/CD ou comentarios automaticos em PR.

### 8. Relacionamentos entre artefatos

Foi criada a tabela `artifact_relations`.

Hoje o `ingest.py` ja gera relacoes automaticas simples, mas muito uteis:

- `imports`
- `shared_table`
- `shared_column`
- `derived_field`

Essas relacoes sao recalculadas quando um arquivo muda.

Isso permite sair do modelo "texto parecido" e aproximar a analise de um mapa de dependencias mais confiavel.

## Estrutura das tabelas

As tres tabelas principais existem para resolver problemas diferentes no pipeline.

- `artifact_files` responde: o arquivo mudou ou nao?
- `artifact_chunks` responde: quais artefatos existem dentro do arquivo?
- `artifact_relations` responde: com o que esses artefatos se conectam?

Pensando de forma simples:

- `artifact_files` controla o estado da indexacao por arquivo
- `artifact_chunks` guarda o conhecimento extraido por bloco de codigo
- `artifact_relations` monta o mapa de dependencias entre blocos

## Diagrama conceitual

```text
Arquivo do repo
    |
    v
artifact_files
    |
    | 1 arquivo pode gerar varios artefatos
    v
artifact_chunks
    |
    | 1 artefato pode se relacionar com varios outros
    v
artifact_relations
```

## Fluxo resumido

```text
1. Um arquivo entra ou muda no repo
2. O sistema calcula o hash e consulta artifact_files
3. Se mudou, o LLM extrai os artefatos do arquivo
4. Cada artefato vira um registro em artifact_chunks
5. O sistema recalcula relacoes desses artefatos em artifact_relations
6. O mcp_tool usa chunks + relations para responder perguntas de impacto
```

### `artifact_files`

Controla o estado da indexacao por arquivo.

O que ela representa:

- um registro por arquivo indexado
- o estado atual daquele arquivo no indice

Campos principais:

- `repo`
- `team`
- `path`
- `content_hash`
- `source_type`
- `status`
- `last_indexed_at`

O que cada campo faz:

- `repo`: identifica de qual repositorio o arquivo veio
- `team`: indica qual time e dono ou contexto principal daquele arquivo
- `path`: caminho do arquivo dentro de `sample_projects`
- `content_hash`: hash do conteudo atual do arquivo
- `source_type`: tipo da fonte, hoje `code`, mas no futuro pode ser `doc` ou `schema`
- `status`: informa se o arquivo esta `active` ou `deleted`
- `last_indexed_at`: diz quando esse arquivo foi indexado pela ultima vez

Por que ela existe:

- para saber se um arquivo mudou
- para pular arquivos que nao precisam ser reprocessados
- para lidar com arquivos deletados
- para suportar indexacao incremental e analise por PR

### `artifact_chunks`

Armazena os blocos extraidos de cada arquivo.

O que ela representa:

- um registro por artefato relevante encontrado no codigo
- um mesmo arquivo pode gerar varios chunks

Campos principais:

- `repo`
- `team`
- `path`
- `block_name`
- `block_type`
- `content`
- `tables_ref`
- `columns_ref`
- `summary`
- `embedding`
- `content_hash`
- `updated_at`

O que cada campo faz:

- `repo`, `team`, `path`: dizem de onde o artefato veio
- `block_name`: nome da funcao, classe ou model
- `block_type`: tipo do artefato
- `content`: guarda o codigo exato daquele bloco
- `tables_ref`: lista de tabelas usadas pelo bloco
- `columns_ref`: lista de colunas usadas pelo bloco
- `summary`: resumo do bloco em linguagem natural
- `embedding`: vetor usado para busca semantica
- `content_hash`: hash da versao do arquivo que originou esse chunk
- `updated_at`: data da ultima atualizacao do chunk

Por que ela existe:

- para indexar conhecimento em granularidade de bloco
- para permitir busca por similaridade
- para entregar contexto estruturado ao LLM
- para associar codigo com tabelas, colunas e impacto tecnico

### `artifact_relations`

Armazena dependencias entre artefatos.

O que ela representa:

- uma ligacao entre um artefato e outro artefato
- um passo em direcao a um grafo de dependencias

Campos principais:

- `artifact_id`
- `related_id`
- `relation_type`
- `confidence`
- `reason`
- `updated_at`

O que cada campo faz:

- `artifact_id`: artefato de origem
- `related_id`: artefato conectado ao artefato de origem
- `relation_type`: tipo da relacao, como `imports`, `shared_table`, `shared_column` ou `derived_field`
- `confidence`: nivel de confianca da relacao
- `reason`: explicacao textual do motivo da relacao
- `updated_at`: data da ultima recalculacao da relacao

Por que ela existe:

- para sair da logica de "texto parecido"
- para mapear dependencias reais entre arquivos e blocos
- para responder melhor quem consome, quem depende e quem sera impactado
- para permitir propagacao de impacto entre times e repositorios

## Como as tabelas se conectam

O fluxo entre elas e este:

- `artifact_files` detecta se o arquivo precisa ser reprocessado
- `artifact_chunks` guarda os artefatos extraidos daquele arquivo
- `artifact_relations` conecta esses artefatos com outros artefatos do ecossistema

Resumo mental:

- `artifact_files` = controle por arquivo
- `artifact_chunks` = conhecimento por bloco
- `artifact_relations` = mapa de dependencias

## Exemplo pratico

Considere este arquivo:

`customer-api/application/repositories/userRepository.js`

O pipeline faz o seguinte:

- em `artifact_files`
  - registra que esse arquivo existe
  - guarda o hash do conteudo
  - marca quando foi indexado

- em `artifact_chunks`
  - armazena blocos como `findUserByEmail`
  - armazena blocos como `listUsersCreatedAfter`
  - armazena blocos como `listUsersEligibleForBilling`

- em `artifact_relations`
  - conecta esse arquivo a jobs que o importam
  - conecta artefatos que compartilham tabelas e colunas
  - conecta transformacoes como `createdAt -> signupDate`

## Fluxo atual

### Ingestao completa

```bash
python ingest.py
```

### Reindexacao de arquivos especificos

```bash
python ingest.py --files sample_projects/customer-api/application/services/userService.js
```

### Remocao de arquivos deletados

```bash
python ingest.py --deleted-files sample_projects/customer-api/application/services/userService.js
```

### Reindexacao baseada em PR

```bash
python index_pr.py --base-ref origin/main --head-ref HEAD
```

### Pergunta de impacto

```bash
python mcp_tool.py --tool gerar_relatorio_impacto "Se eu remover createdAt, quais times e pipelines quebram?"
```

## O que isso agrega

### Para engenharia

- ajuda a entender impacto antes de mudar schema, contratos ou jobs
- reduz dependencia de conhecimento tribal
- melhora revisao tecnica de PR
- ajuda a localizar consumidores diretos e indiretos

### Para arquitetura

- comeca a formar um mapa de dependencias entre frentes
- evidencia acoplamentos entre aplicacao, dados, ETL e integracoes
- permite rastrear propagacao de mudancas de contrato

### Para operacao de desenvolvimento

- abre caminho para comentarios automaticos em PR
- permite reindexacao incremental
- facilita auditoria de mudancas estruturais

## Limitacoes atuais

Apesar de funcional, a POC ainda tem algumas limitacoes importantes:

- as relacoes ainda sao heuristicas e nao cobrem todos os tipos de dependencia
- ainda nao existe reconciliacao fina por artefato individual quando um bloco muda de identidade
- a qualidade da extração depende do modelo escolhido no OpenRouter
- contas free do OpenRouter possuem limite diario baixo
- a busca hibrida melhora o contexto, mas ainda nao substitui um grafo mais rico

## Evolucoes recomendadas

### Curto prazo

- adicionar mais tipos de relacao:
  - `calls`
  - `exports_to`
  - `consumes_event`
  - `owned_by_team`
  - `cross_team_dependency`
- melhorar a qualidade do contexto enviado ao LLM com relacoes diretas e indiretas
- enriquecer a indexacao com metadados como `layer`, `operation` e `domain_entity`

### Medio prazo

- comentar automaticamente em PR com o mapa de impacto
- versionar melhor a identidade dos artefatos
- recalcular relacoes tambem a partir de docs e contratos
- adicionar confianca por fonte:
  - regra deterministica
  - inferencia do modelo
  - combinacao das duas

### Longo prazo

- transformar `artifact_relations` em um grafo mais rico
- navegar impactos por multiplos hops
- suportar mais repositorios e frentes
- usar a base como catalogo vivo de dependencias tecnicas

## Requisitos de ambiente

Variaveis mais importantes:

- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL`
- `OPENROUTER_MAX_RETRIES`
- `OPENROUTER_RETRY_DELAY`
- `DB_CONN`

Banco:

- Postgres com extensao `pgvector`

## Resumo

O projeto deixou de ser apenas um script de ingestao e passou a ter:

- dataset multi-time e multi-repo
- indexacao incremental
- reprocessamento baseado em PR
- embeddings locais
- busca hibrida
- relacoes entre artefatos
- uso de LLM para resposta final

Isso ja permite testar uma abordagem realista de analise de impacto tecnico com evolucao clara para algo mais autonomo e sustentavel.

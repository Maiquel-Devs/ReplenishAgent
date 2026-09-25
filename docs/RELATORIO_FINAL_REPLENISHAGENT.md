# Relatório final do projeto ReplenishAgent

> Documento de encerramento, avaliação crítica e transferência de conhecimento.  
> Estado analisado: repositório e worktree em 25 de setembro de 2026.  
> Este documento não é um manual de instalação nem uma especificação de funcionalidades futuras.

## Sumário

1. [Escopo, método e grau de confiança](#1-escopo-método-e-grau-de-confiança)
2. [Origem e proposta do projeto](#2-origem-e-proposta-do-projeto)
3. [O que o sistema é hoje](#3-o-que-o-sistema-é-hoje)
4. [Funcionalidades por domínio](#4-funcionalidades-por-domínio)
5. [Motor determinístico](#5-motor-determinístico)
6. [Agent](#6-agent)
7. [Providers de IA](#7-providers-de-ia)
8. [Experimentos com modelos locais](#8-experimentos-com-modelos-locais)
9. [Segurança](#9-segurança)
10. [Testes e qualidade](#10-testes-e-qualidade)
11. [Arquitetura](#11-arquitetura)
12. [Evolução do projeto](#12-evolução-do-projeto)
13. [O que ficou bom](#13-o-que-ficou-bom)
14. [O que ficou fraco](#14-o-que-ficou-fraco)
15. [IA: necessária ou não?](#15-ia-necessária-ou-não)
16. [Quem usaria isso?](#16-quem-usaria-isso)
17. [Utilidade real](#17-utilidade-real)
18. [Complexidade versus valor](#18-complexidade-versus-valor)
19. [O que faríamos diferente](#19-o-que-faríamos-diferente)
20. [Lições para o próximo projeto](#20-lições-para-o-próximo-projeto)
21. [O que vale reutilizar](#21-o-que-vale-reutilizar)
22. [Estado final](#22-estado-final)
23. [Contexto para planejar um novo projeto](#23-contexto-para-planejar-um-novo-projeto)

## 1. Escopo, método e grau de confiança

Este relatório usa como fonte principal o código atual, inclusive as alterações locais ainda não commitadas. Foram examinados os modelos, serviços, cálculos, Agent, Tools, providers, autorização, auditoria, sanitização, views, forms, templates, migrations, testes, configuração Django, Docker, CI, documentação e histórico Git. A análise não executou o sistema nem fez chamadas de rede.

As classificações usadas são:

- **Implementado:** existe um caminho executável no código atual.
- **Implementado e validado offline:** há código e testes automatizados, mas isso não implica validação com um serviço externo real.
- **Em desenvolvimento:** está no worktree, ainda não commitado ou depende de validação real pendente.
- **Planejado/ideia antiga:** aparece em documentação ou no encadeamento das fases, mas não há implementação correspondente.
- **Não implementado:** não foi encontrado caminho funcional no código.
- **Abandonado/não concluído:** houve intenção ou infraestrutura parcial, mas o resultado não forma uma capacidade operacional completa.

Há documentação histórica defasada. `docs/ai-configuration.md` e `docs/security/access.md`, por exemplo, ainda afirmam em trechos que o chat usa apenas o provider falso e que a conexão com provider real seria uma fase futura. O código atual já usa a factory e um provider real configurado. Nesses conflitos, este relatório segue o código.

O histórico Git permite reconstruir bem a ordem técnica das entregas, mas não comprova pesquisa com usuários, demanda comercial, decisões de produto tomadas fora do repositório ou o motivo pessoal original do projeto. Também não existe no repositório um diário completo dos experimentos com modelos contendo prompts, respostas RAW e ambiente de cada execução. Por isso, conclusões sobre mercado e comportamento de modelos são explicitamente limitadas.

## 2. Origem e proposta do projeto

### Domínio e problema tentado

O ReplenishAgent está no domínio de controle de estoque e planejamento de compras. O problema que o código tenta resolver é: a partir de cadastro de produtos e fornecedores, saldo atual e histórico de saídas, identificar risco de falta, calcular quanto repor e preparar uma proposta para decisão humana.

O repositório comprova essa intenção por sua sequência de domínio:

- produto define SKU, estoque mínimo e condição ativa;
- fornecedor possui dados cadastrais;
- relação produto-fornecedor define preço, prazo de entrega e preferência;
- movimentações de entrada e saída mantêm o saldo;
- saídas históricas alimentam o consumo médio;
- consumo, saldo, estoque mínimo, prazo e horizonte alimentam o cálculo de reposição;
- o cálculo pode virar uma proposta de compra imutável e pendente;
- uma pessoa autorizada aprova ou rejeita a proposta;
- o Agent oferece uma interface em linguagem natural sobre essas operações.

### Papel de cada elemento

**Estoque** é o estado operacional: uma quantidade atual por produto, atualizada atomicamente a cada movimento. Sem saldo e movimentos confiáveis, toda recomendação posterior perde valor.

**Consumo** é inferido somente pelas movimentações `OUT` dentro de uma janela temporal. Não é previsão estatística: é uma média diária simples do total de saídas dividido pelo número de dias.

**Fornecedores** dão contexto econômico e operacional. A relação com o produto contém preço, lead time e um indicador de preferencial. O lead time influencia risco e ponto de reposição; o preço entra na proposta.

**Cálculos de reposição** transformam dados operacionais em cobertura, ponto de reposição, estoque-alvo, risco e quantidade recomendada. São implementados em Python e não pelo LLM.

**Propostas de compra** são snapshots da recomendação e do preço no momento da criação. Elas não são pedidos de compra enviados ao fornecedor. Permanecem `PENDING` até decisão humana e, uma vez decididas, seus dados relevantes ficam imutáveis.

**Agent** traduz pedidos em linguagem natural para chamadas de Tools. Ele pode consultar e calcular. Existe uma Tool de escrita para criar proposta, mas o fluxo web atual instancia o Agent com `allow_write=False`; portanto, no uso normal pelo chat, essa escrita fica bloqueada.

**Humano** cadastra os dados, registra movimentos, pode iniciar análise, pode criar proposta pelo fluxo web e, com permissão específica, aprova ou rejeita. A decisão final de compra não foi delegada ao modelo.

### Proposta atual em uma frase

**O ReplenishAgent é uma aplicação web demonstrativa que mantém um estoque simples, calcula reposição por regras determinísticas e permite preparar e revisar propostas de compra, oferecendo também um assistente de linguagem natural controlado por Tools.**

Não é possível comprovar pelo repositório qual segmento de mercado foi originalmente escolhido, se houve entrevistas com usuários ou qual ganho econômico mensurável motivou o produto.

## 3. O que o sistema é hoje

Uma pessoa utiliza o sistema para cadastrar produtos e fornecedores, associar condições de fornecimento, registrar entradas e saídas, visualizar saldo baixo, executar uma análise de reposição e, quando existe quantidade recomendada, criar uma proposta para revisão humana. Em paralelo, ela pode perguntar ao Agent sobre dados e análises disponíveis.

### Fluxo real

```text
CADASTRO
produto + fornecedor + relação (preço, lead time, preferência)
        ↓
OPERAÇÃO
movimentações IN/OUT → saldo atual
        ↓
ANÁLISE
saídas históricas → consumo médio
saldo + consumo + lead time + mínimo + horizonte
        ↓
RECOMENDAÇÃO
risco + cobertura + ponto de reposição + estoque-alvo + quantidade
        ↓
PROPOSTA
snapshot de produto, fornecedor, quantidade, preço, total e risco
        ↓
DECISÃO HUMANA
PENDING → APPROVED ou REJECTED
```

Todas essas etapas existem, com duas ressalvas importantes. Primeiro, a aprovação encerra o estado da proposta, mas não envia pedido ao fornecedor, não agenda recebimento e não gera entrada de estoque. Segundo, a análise depende de dados preenchidos manualmente; não há integração com vendas, ERP, e-commerce ou emissão fiscal.

O Agent não substitui o fluxo web. Ele é uma entrada alternativa para consulta e cálculo. Embora a página mostre um histórico de conversa na sessão, cada envio cria uma nova execução que recebe somente a mensagem atual, além do system prompt. O histórico visual anterior não é reenviado ao provider. Portanto, o chat parece conversacional, mas não mantém contexto semântico entre turnos.

## 4. Funcionalidades por domínio

### Produtos

Existe cadastro e edição de produto com nome, SKU único, descrição, estoque mínimo e situação ativa. Há listagem e detalhe, incluindo saldo e relações com fornecedores. Restrições garantem SKU único e estoque mínimo não negativo.

O produto é a unidade central das movimentações, inventário, análises e propostas. Não há categorias, unidade de medida configurável, variações, lote, validade, código de barras ou múltiplos depósitos.

### Fornecedores

Existe cadastro e edição com nome, CNPJ opcional, e-mail, telefone e situação ativa. A relação produto-fornecedor armazena preço positivo, lead time não negativo e preferência. A combinação produto-fornecedor é única.

O sistema não garante que exista exatamente um fornecedor preferencial por produto; mais de uma relação pode ser marcada como preferencial. Quando uma Tool escolhe automaticamente, ela ordena preferenciais primeiro e depois por nome/ID. Não há histórico de preços, condições de pagamento, pedido mínimo, desempenho de entrega ou homologação.

### Estoque

Cada produto pode ter um único registro de `Inventory`. Ausência de registro é tratada como saldo zero em consultas e análises. A aplicação mostra a lista de estoque e o dashboard sinaliza produtos ativos cujo saldo é menor ou igual ao estoque mínimo.

O saldo é armazenado, não recalculado integralmente a cada leitura. A consistência depende do serviço de movimentação ser o caminho de escrita. Não foi encontrado recurso de inventário físico, ajuste com motivo específico, reserva, localização ou reconciliação automática entre saldo e livro de movimentos.

### Movimentações

O usuário autorizado registra entrada ou saída, quantidade positiva, data e observação. O serviço valida o movimento, bloqueia concorrência com `select_for_update`, cria o saldo quando necessário e atualiza movimento e inventário na mesma transação. Saídas que tornariam o saldo negativo são recusadas.

As movimentações sustentam o cálculo de consumo. O formulário web usa o momento atual; o serviço aceita `occurred_at`, útil para domínio e testes. Não há edição ou exclusão no fluxo web, o que é coerente com um livro operacional simples, embora não exista um mecanismo formal de estorno.

### Reposição

O usuário escolhe produto, relação com fornecedor, janela de consumo e horizonte de planejamento. O sistema calcula e exibe saldo, consumo médio, cobertura, lead time, mínimo, ponto de reposição, estoque-alvo, quantidade e risco.

O motor é totalmente determinístico. A análise individual e a análise em lote compartilham as mesmas fórmulas. A versão em lote reduz consultas e suporta a Tool de produtos em risco.

### Propostas de compra

Uma proposta contém produto, fornecedor, quantidade inteira positiva, preço unitário, preço total, risco, status e dados da revisão. Produto, fornecedor, quantidade, preço e risco formam um snapshot imutável depois da criação. O banco também exige que total seja quantidade vezes preço.

O usuário com permissão de criação pode gerar uma proposta a partir da análise web. Um revisor com permissão própria pode aprovar ou rejeitar uma proposta pendente; uma proposta decidida não pode ser decidida novamente. Não existe pedido de compra posterior, envio, recebimento, cancelamento, aprovação em níveis, orçamento ou deduplicação explícita de propostas equivalentes pendentes.

### Agent

O chat aceita uma mensagem de até 2.000 caracteres, escolhe o provider pela configuração global, registra auditoria e executa o loop de Tool Calling. Usuários autenticados podem usar Tools `READ` e `COMPUTE`. `WRITE` exige tanto `allow_write=True` quanto permissão backend; no fluxo web, a primeira condição não é ativada. `CRITICAL` é sempre bloqueada pela policy atual.

### Configuração de IA

Existe uma configuração global singleton, não uma configuração por usuário ou organização. Os pares aceitos são somente `LOCAL/ollama` e `CLOUD/mistral`. Ela armazena integração, modelo, endpoint local, estado ativo e data de atualização. A chave Mistral não é armazenada.

Para Ollama, a página aceita endpoint local validado, modelo e teste de listagem de modelos. Para Mistral, o worktree atual mostra estado da credencial de ambiente e implementa teste de catálogo de modelos. Essa parte Cloud está validada por mocks offline, mas ainda não foi confirmada contra uma conta/API real.

### Administração

Há visão administrativa com propostas pendentes, execuções recentes e Tools problemáticas; telas de configuração da IA, revisão de propostas e auditoria. O Django Admin também está publicado em `/admin/` para usuários com as permissões padrão adequadas.

### Autenticação e papéis

O Django exige login globalmente, com exceções deliberadas como health check e rotas de autenticação. Há dois perfis de demonstração montados por permissões: operador e administrador. O operador mantém cadastros, movimentos e propostas; o administrador acrescenta escrita via Agent em nível de permissão, revisão, configuração da IA e auditoria. As contas demonstrativas usam senha conhecida e só podem ser sincronizadas com `DEBUG=True`; não são um modelo de provisionamento para produção.

### Auditoria

Cada execução do Agent registra usuário, provider, modelo, pedido, status, duração, resposta final e código de erro. Cada Tool registra ID da chamada, nome, nível, argumentos, resultado, status e duração. A combinação execução + `tool_call_id` é única e permite idempotência: repetir o mesmo ID devolve o resultado anterior; reutilizá-lo com dados diferentes gera conflito.

Há também histórico de alteração da configuração da IA, mas ele deliberadamente não grava o texto do modelo. Isso reduz exposição, porém impede reconstruir pelo log qual modelo foi selecionado em cada mudança; o modelo efetivo aparece nas execuções do Agent.

### Segurança

As proteções estão detalhadas na seção 9. Em termos funcionais, autenticação não equivale a autorização: ações de escrita e administração têm permissões específicas; Tools ainda passam por uma policy backend independente do LLM.

## 5. Motor determinístico

### Separação de responsabilidades

O dado vem do banco, o cálculo é feito por funções Python, e o LLM apenas decide qual Tool solicitar e como explicar o resultado. O modelo não calcula o saldo, não estima consumo por conta própria e não é autorizado a inventar risco ou quantidade.

```text
Produtos + relações + movimentos + saldo
                  ↓
        serviços determinísticos
                  ↓
 ReplenishmentAnalysis estruturada
                  ↓
       tela web ou resultado de Tool
                  ↓
          explicação do Agent
```

### Fórmulas reais

Considere:

- `S`: saldo atual;
- `C`: consumo médio diário;
- `L`: lead time do fornecedor em dias;
- `M`: estoque mínimo;
- `P`: horizonte de planejamento em dias.

**Consumo médio diário**

```text
C = soma das movimentações OUT em [data final - dias, data final) / dias
```

Dias sem saída dentro da janela continuam no denominador. Entradas não contam como consumo. O intervalo é semiaberto e exige data timezone-aware.

**Cobertura de estoque**

```text
cobertura = S / C
```

Quando `C = 0`, a cobertura é `None`, interpretada como ausência de consumo observado, não como estoque ausente ou infinito numérico.

**Ponto de reposição**

```text
ponto de reposição = C × L + M
```

**Estoque-alvo**

```text
estoque-alvo = C × P + M
```

**Quantidade recomendada**

```text
necessidade = estoque-alvo - S
quantidade = 0, se necessidade ≤ 0
quantidade = teto(necessidade), caso contrário
```

Existe tolerância numérica para preservar um valor praticamente inteiro antes do arredondamento para cima.

**Classificação de risco**

1. `CRITICAL` se o saldo é zero;
2. `LOW` se não houve consumo;
3. `HIGH` se a cobertura é menor ou igual ao lead time;
4. `MEDIUM` se o saldo é menor ou igual ao ponto de reposição;
5. `LOW` nos demais casos.

A ordem importa: saldo zero é crítico mesmo sem consumo. A regra é simples e explicável, mas não é um modelo de previsão. Não usa variabilidade da demanda, nível de serviço, estoque de segurança estatístico, sazonalidade, dias úteis, compras em trânsito, lote mínimo, embalagem ou capacidade financeira.

### Por que o LLM não é fonte de verdade

Os mesmos dados produzem o mesmo resultado; tipos, limites e invariantes são testáveis; fórmulas podem ser auditadas; e qualquer alteração de regra passa por código e testes. Já um LLM pode variar resposta, errar aritmética, selecionar a Tool errada ou inventar argumento. O system prompt reforça essa fronteira, mas a proteção principal é arquitetural: a Tool chama os serviços de domínio e devolve números calculados pelo backend.

O fluxo correto é, portanto, `dados → cálculo determinístico → Agent → explicação`, e não `dados → LLM → decisão numérica`.

## 6. Agent

### Responsabilidade

`ReplenishAgent` orquestra mensagens, provider, catálogo de Tools, autorização e auditoria. Ele não contém as fórmulas de reposição nem conhece o protocolo HTTP de Ollama ou Mistral.

### System prompt

O prompt instrui o modelo a:

- responder conversa genérica sem Tools;
- usar `READ` para dados e `COMPUTE` para cálculo;
- nunca inventar estoque, consumo, fornecedor, risco ou quantidade;
- usar `calcular_reposicao` para perguntas de necessidade de reposição;
- tratar resultados de Tool como fonte de verdade;
- não confundir cobertura, horizonte, mínimo e ponto de reposição;
- não inventar IDs nem enviar placeholders;
- usar `WRITE` somente com pedido explícito;
- manter propostas pendentes e decisão crítica com humano.

O prompt ficou longo e repetitivo, em parte como resposta a falhas observadas em modelos pequenos. Isso melhora guardrails comportamentais, mas também revela que seleção e fidelidade ainda dependem de instruções frágeis; o backend continua sendo a barreira real.

### Loop

1. Cria mensagens `system` e `user`.
2. Obtém todas as `ToolDefinition` do registro.
3. Chama `provider.generate`.
4. Se não vier `tool_calls`, conclui com o texto retornado.
5. Se vierem chamadas, anexa a mensagem `assistant` com as Tool Calls.
6. Para cada chamada, consulta o nível, audita e executa pelo registro.
7. Anexa uma mensagem `tool` com JSON, `tool_call_id` e nome.
8. Faz nova inferência até resposta final ou limite.

O limite padrão é oito iterações. Se a última ainda pedir Tool, a execução termina como `LIMIT_REACHED`. Múltiplas Tool Calls são preservadas na ordem recebida, mas são executadas sequencialmente; “parallel tool calls” do provider não viram concorrência no backend.

### Abstrações

`ToolDefinition` contém nome, descrição e JSON Schema imutável. `ToolCall` contém ID original, nome, argumentos estruturados e `index` opcional. `LLMResponse` contém texto opcional e uma tupla ordenada de chamadas. `LLMMessage` normaliza os quatro papéis (`system`, `user`, `assistant`, `tool`) e permite reconstruir a chamada do assistant e correlacionar o resultado.

Os schemas com identificadores alternativos usam `oneOf` para comunicar “exatamente um” ao modelo. O validador genérico do registro não interpreta `oneOf`, mas os handlers `_product_from_identity` e `calcular_reposicao` repetem e aplicam a regra no backend. Assim, a segurança semântica não depende de o modelo respeitar o schema.

### Tools reais

| Tool | Nível | Função real |
|---|---|---|
| `consultar_produto` | READ | Localiza por nome exato ou ID e retorna cadastro básico. |
| `consultar_estoque` | READ | Retorna saldo atual; ausência de inventário vira zero. |
| `consultar_movimentacoes` | READ | Lista movimentos recentes de um produto, com limite. |
| `consultar_fornecedores` | READ | Lista relações, preços, lead time e preferência. |
| `consultar_consumo` | COMPUTE | Calcula somente consumo médio em uma janela. |
| `calcular_reposicao` | COMPUTE | Executa a análise determinística completa. |
| `consultar_produtos_em_risco` | COMPUTE | Analisa em lote e lista riscos não baixos. |
| `criar_proposta_compra` | WRITE | Recalcula e cria uma proposta `PENDING`. |

Não existe Tool `CRITICAL` registrada. O nível existe na arquitetura e é sempre recusado pela policy atual.

### Autorização e humano no circuito

`READ` e `COMPUTE` são permitidas pela policy a qualquer contexto; na aplicação web, o middleware garante usuário autenticado. `WRITE` exige duas condições simultâneas: `allow_write=True` e a permissão Django `agent.execute_agent_write`. O LLM nunca concede essa permissão.

No caminho web atual, `run_agent` não passa uma policy com escrita habilitada; usa o padrão `allow_write=False`. Logo, até um administrador recebe bloqueio se o modelo pedir `criar_proposta_compra` pelo chat. A arquitetura suporta escrita controlada e os testes exercitam isso, mas a experiência operacional do Agent é hoje efetivamente somente leitura/cálculo.

Mesmo quando uma proposta é criada por outro fluxo, ela nasce `PENDING`. Aprovação e rejeição são serviços web humanos com permissão própria. Aprovação não é uma Tool do Agent.

### Erros e auditoria

Erros esperados de Tool viram resultados estruturados: Tool ausente, argumentos inválidos, recurso não encontrado, não autorizado e erro de domínio. Exceções inesperadas são ocultadas como `internal_error`. O Agent envia o resultado ao modelo para que ele explique ou tente corrigir; não há exposição de traceback.

Falhas do provider, limite e outras exceções marcam a execução. A camada web converte erros de configuração/provider/limite em mensagens genéricas amigáveis.

## 7. Providers de IA

### Interface e factory

Todos os providers implementam `generate(messages, tools) → LLMResponse`. A factory lê a configuração global ativa ou aceita override explícito de teste. O Agent conhece apenas essa interface.

Não existe fallback silencioso: `LOCAL/ollama` não tenta Cloud quando Ollama falha; `CLOUD/mistral` não tenta Local quando falta chave ou há erro. A constraint do modelo e a validação da factory limitam pares suportados.

### FakeLLMProvider

É um provider determinístico alimentado por sequência finita de respostas. Registra cada conjunto de mensagens e Tools recebido. Permite testar loop, autorização, reconstrução de histórico, auditoria e erros sem rede, custo ou comportamento probabilístico. É infraestrutura de teste, não opção configurável na interface.

### OllamaProvider

Usa `POST /api/chat`, `stream=false`, mensagens e Tools no formato do Ollama. Converte resposta em `LLMResponse`, aceita argumentos como objeto ou string JSON, preserva ID, nome, argumentos, ordem e `function.index`. Se uma versão do Ollama omitir ID, gera um ID interno; quando há ID original, ele é mantido. JSON parecido com Tool dentro de `message.content` permanece texto e nunca é promovido.

O teste de conexão usa `GET /api/tags`, limita tamanho e tempo de leitura, não segue redirects e não executa inferência. O cliente ignora proxies do ambiente. Timeout e indisponibilidade viram erros controlados.

### MistralProvider: estado real

O provider já existia e usava o SDK oficial. No worktree atual, ainda não commitado, ele foi ampliado e validado offline para:

- enviar system, user, assistant e tool;
- serializar Tools;
- receber uma ou várias Tool Calls, preservando ID, argumentos e ordem;
- reconstruir chamadas do assistant;
- enviar resultado com `role=tool`, `name` e `tool_call_id`;
- continuar a inferência após Tool;
- usar `stream=False` e timeout configurável;
- sanitizar categorias de erro de autenticação, timeout, HTTP, indisponibilidade e resposta inválida;
- listar modelos pela API do SDK como teste sem chat.

A factory exige `MISTRAL_API_KEY` exclusivamente no ambiente e `MISTRAL_TIMEOUT` opcional. A tela não recebe nem exibe a chave; mostra apenas configurada/não configurada.

**Classificação honesta:** a implementação Cloud está **em desenvolvimento, funcional nos testes offline e ainda não validada em chamada real**. Não se deve descrevê-la como integração operacional comprovada. A configuração persistida continuou Local/Ollama durante a fase anterior. A ausência de campo de chave no navegador é uma decisão de segurança, não uma lacuna a ser “corrigida”; o que permanece pendente é a validação real controlada.

### Troca de modelo e erros

O identificador do modelo é persistido e passado ao provider. Para Ollama, o endpoint também é persistido; para Mistral, endpoint e chave não são. Configuração ausente, inativa, inválida, timeout inválido, chave ausente e provider desconhecido falham explicitamente. A interface esconde detalhes técnicos e segredos.

## 8. Experimentos com modelos locais

### Qualidade da evidência

Os testes versionados comprovam contratos de provider e Agent, mas não o comportamento probabilístico de modelos reais. As respostas RAW dos experimentos recentes não foram encontradas como artefato versionado. A auditoria do banco poderia conter execuções do Agent, porém o experimento isolado foi feito diretamente contra Ollama e não passou pelo Agent; portanto, não deveria aparecer ali.

O que segue combina o registro da fase experimental anterior com o código de contrato criado a partir dela. É evidência limitada ao ambiente, versões, prompts e doze inferências daquele momento, não uma verdade universal.

### Experimento de schema

Na comparação direta entre schema simples e schema real de `consultar_estoque`, duas execuções por cenário:

- `llama3.2:3b` retornou Tool Call estruturada nas quatro execuções;
- `mistral:latest` retornou Tool Call estruturada nas duas execuções com schema simples e JSON textual em `content` nas duas com schema real; em uma execução simples houve chamada duplicada;
- `qwen2.5-coder:7b` colocou a chamada como JSON textual em `content` nas quatro execuções;
- o pequeno controle adicional com Mistral comparando `oneOf` e uma alternativa sem `oneOf` continuou textual em ambos os lados.

Logo, houve correlação entre schema real e falha do Mistral local naquele recorte, mas o controle não isolou `oneOf` como causa. O tamanho da amostra é insuficiente para causalidade.

### Aprendizados por modelo

**llama3.2:3b:** mostrou a melhor compatibilidade com o canal estruturado nesse experimento. Em usos anteriores houve instabilidade de seleção de Tool e argumentos inventados, o que motivou descrições e prompt mais explícitos. O repositório preserva essas defesas e testes, mas não um benchmark reproduzível que quantifique a falha.

**mistral:latest:** houve observação qualitativa de conversa genérica melhor, mas isso não está documentado por uma avaliação versionada. No experimento de schemas, sua emissão estruturada variou conforme o schema e chegou a duplicar chamada. Não se pode concluir que “Mistral não suporta Tools”; apenas que essa combinação local foi inconsistente.

**qwen2.5-coder:7b:** reconheceu a intenção de chamada, mas, no experimento citado, serializou JSON em `message.content` em vez de `message.tool_calls`. O sistema corretamente trata isso como texto e não executa. Essa fronteira evita que texto arbitrário ganhe autoridade de Tool.

### Conclusão experimental

A evidência é **moderada** de que o comportamento depende fortemente do modelo e **inconclusiva** para atribuir o problema à complexidade do schema em geral. Não há base para simplificar todas as Tools, trocar modelo automaticamente ou criar parser de JSON textual.

## 9. Segurança

### Controles existentes

**Autenticação e sessão.** O sistema usa autenticação de sessão Django e middleware que exige login por padrão. Logout é POST e passa por CSRF. O health check é deliberadamente público.

**Papéis e permissões.** Views de cadastro, movimentação, proposta, revisão, auditoria e configuração têm permissões distintas. Tentativas sem permissão resultam em `403`, não apenas em botão escondido.

**Proteção de login.** `django-axes` bloqueia após cinco falhas por combinação configurada, com cooldown de 15 minutos e resposta `429`/`Retry-After`. A documentação alerta para confiar em proxy apenas quando a infraestrutura for controlada.

**CSRF e XSS.** Forms mutáveis incluem token CSRF; templates usam autoescape. Existe roteiro de validação manual para CSRF, autorização e XSS armazenado, embora não seja pentest profissional.

**Autorização de Tools.** O nome e os argumentos vindos do modelo não são execução direta. A chamada precisa existir no registro, validar schema, passar policy e então invocar um handler explícito. Não há `eval`, import dinâmico ou roteamento arbitrário por nome de função.

**WRITE e CRITICAL.** WRITE requer flag da execução e permissão do usuário; o fluxo web mantém a flag desligada. CRITICAL é sempre negada. Decisão de proposta permanece fora do Agent.

**SSRF no Ollama.** Endpoint configurável aceita somente HTTP/HTTPS, origem sem caminho/credenciais/query, porta explícita e host local, nomes permitidos ou IP privado. O cliente não segue redirects e ignora proxy do ambiente. Ainda existe uma superfície controlada para alcançar serviços em rede privada; ela é restrita à permissão administrativa e deveria continuar sendo tratada como sensível.

**Auditoria e idempotência.** Execuções e chamadas têm status, tempos, IDs e resultados. Repetição de `tool_call_id` não duplica efeito. Isso é especialmente importante se WRITE for habilitada futuramente.

**Sanitização.** Dados de auditoria são convertidos para JSON seguro, limitados em profundidade, quantidade e tamanho, e chaves/valores com marcadores de secret são redigidos. Exceções internas e corpos de erro do provider não são mostrados ao usuário.

**Secrets.** `MISTRAL_API_KEY`, `SECRET_KEY` e credenciais de banco vêm do ambiente. A configuração persistida não contém chave Cloud, e a interface só exibe presença. A documentação e `.env.example` orientam o uso, mas a segurança operacional depende de o `.env` real continuar não versionado.

**Chain-of-thought.** O sistema armazena pedido, resposta final e eventos de Tool, não raciocínio oculto do modelo. Não solicita nem persiste chain-of-thought.

### Por que esses controles importam

O Agent transforma texto probabilístico em intenção de acesso a dados e, potencialmente, escrita. Sem autorização backend, um prompt mal formulado ou malicioso poderia criar registros. Sem idempotência, retries poderiam duplicá-los. Sem sanitização, prompts e erros poderiam levar secrets ao banco ou à tela. E sem decisão humana, uma recomendação estatisticamente simples poderia virar compromisso de compra.

### Limites

- A auditoria está no mesmo banco da aplicação e não é um log inviolável externo.
- Usuários autenticados podem fazer consultas e cálculos pelo Agent sem uma permissão específica de leitura do Agent.
- Mensagens e resultados auditados podem conter dados de negócio; sanitização de secrets não equivale a política de retenção ou privacidade.
- A página base carrega Bootstrap de CDN pública, criando dependência externa no navegador e uma consideração de privacidade/disponibilidade.
- A documentação de produção reconhece que proxy TLS, gestão de secrets, backup, observabilidade e operação definitiva ainda dependem de infraestrutura externa ao repositório.

## 10. Testes e qualidade

O último resultado validado na fase anterior, não reexecutado para este relatório, foi **501 testes passando** e **93% de branch coverage**. O limite configurado é **90%**, com `branch = True` e fontes `apps` e `config`.

### Cobertura de tipos de teste

- modelos de produto, fornecedor, inventário e proposta;
- constraints e invariantes de domínio;
- transações e concorrência de movimentação;
- fórmulas e serviços de reposição, individuais e em lote;
- criação e revisão humana de propostas;
- abstrações do Agent e fluxo completo com provider falso;
- schemas, argumentos, autorização, WRITE/CRITICAL e idempotência;
- auditoria e sanitização;
- endpoint local e proteções relacionadas a SSRF;
- contratos de Ollama, inclusive uma/múltiplas chamadas, repetição, argumentos objeto/string, ID/index e JSON textual;
- Mistral com mocks, incluindo texto, Tools, continuação, autenticação, timeout, HTTP e resposta inválida;
- factory, configuração Local/Cloud e ausência de fallback;
- views, formulários, navegação, autenticação, permissões e usuários de demonstração.

`FakeLLMProvider` é central para manter os testes do Agent offline e determinísticos. Os testes de providers usam fakes/mocks HTTP/SDK; a suíte não precisa consumir API real.

### Ferramentas de qualidade

- Ruff seleciona erros `E4`, `E7`, `E9` e `F`; é uma configuração útil, porém estreita, não um lint completo de estilo, complexidade ou segurança.
- `django check` e `makemigrations --check --dry-run` fazem parte da validação.
- `git diff --check` foi usado na fase anterior.
- A CI sobe PostgreSQL, verifica Django, migrations e Ruff, executa cobertura, constrói a imagem Docker e testa o health check em Compose.
- O Dockerfile usa usuário não-root e Gunicorn como comando padrão; o Compose de desenvolvimento sobrescreve para `runserver` e sincroniza usuários demo.

O conjunto de testes é um ponto forte real. O número e coverage, porém, medem comportamento codificado, não utilidade do produto nem qualidade das respostas de modelos reais.

## 11. Arquitetura

### Fluxo web determinístico

```text
USUÁRIO AUTENTICADO
        ↓
TEMPLATES + VIEWS + FORMS (Django)
        ↓
SERVIÇOS DE DOMÍNIO
  ├─ movimentação de estoque
  ├─ cálculo de reposição
  └─ propostas e revisão
        ↓
MODELS + CONSTRAINTS
        ↓
POSTGRESQL
```

### Fluxo do Agent

```text
USUÁRIO AUTENTICADO
        ↓
CHAT WEB
        ↓
ReplenishAgent
  ├─ prompt e loop
  ├─ policy/autorização
  └─ auditoria
        ↓
LLMProvider
  ├─ Fake (testes)
  ├─ Ollama (local)
  └─ Mistral (Cloud, offline validado)
        ↓  ToolCall normalizada
ToolRegistry
        ↓
HANDLER DA TOOL
        ↓
SERVIÇO/CÁLCULO DETERMINÍSTICO
        ↓
POSTGRESQL
        ↓
resultado estruturado → provider → resposta ao usuário
```

Django reúne apresentação, autenticação, autorização, ORM e serviços. PostgreSQL mantém estado e constraints. `apps/replenishment` não possui models/migrations: é o núcleo de cálculo. `apps/agent` contém abstrações, providers, Tools, configuração e auditoria. `apps/web` compõe os casos de uso para a interface.

A separação é, em geral, clara. Uma fragilidade é que o produto tem dois caminhos para capacidades próximas — telas determinísticas e Agent — o que multiplica testes e decisões de UX sem que o segundo caminho tenha demonstrado valor superior.

## 12. Evolução do projeto

O histórico de commits permite agrupar a evolução em grandes fases:

1. **Infraestrutura inicial:** Django, PostgreSQL, Docker e estrutura de apps.
2. **Domínio base:** produtos, fornecedores e relação produto-fornecedor.
3. **Operação de estoque:** inventário e movimentações transacionais.
4. **Inteligência determinística:** motor de reposição, risco e análise em lote.
5. **Compras:** propostas como snapshot e fluxo de aprovação/rejeição humana.
6. **Interface web:** dashboard, cadastros, estoque, análise e propostas.
7. **Abstração de IA:** interface comum de providers, Fake, Ollama e Mistral.
8. **Agent e Tools:** loop, catálogo, permissões, escrita controlada e auditoria.
9. **Segurança e qualidade:** hardening, autenticação, papéis, CI e ampliação de cobertura.
10. **UX e operação:** reorganização visual, navegação e usuários demo.
11. **IA real local:** chat conectado à configuração persistida e ao Ollama.
12. **Confiabilidade de Tool Calling:** prompt, schemas, identidade, índice e round-trip.
13. **Cloud/Mistral:** implementação offline e alternância Local/Cloud no worktree, ainda sem teste real.

O crescimento foi tecnicamente coerente, mas a complexidade subiu de um pequeno sistema de estoque para um sistema com segurança, auditoria, adapters, schemas, compatibilidade de modelos e UI administrativa antes de haver evidência registrada de adoção. Boa parte do esforço recente foi absorvida pela confiabilidade do canal LLM, não por ampliar o resultado operacional de compras.

## 13. O que ficou bom

### Pontos fortes de engenharia

**Regras determinísticas fora do LLM.** É a decisão estrutural mais forte. Números importantes são reproduzíveis, auditáveis e testáveis. O modelo não tem autoridade para redefinir o domínio.

**Invariantes em múltiplas camadas.** Validação de serviço, `full_clean`, transações, locks e constraints de banco protegem saldo, preço, total e estados de proposta. Isso reduz a dependência da interface “se comportar”.

**Human-in-the-loop real.** Propostas nascem pendentes, decisão é autorizada e imutável, e não existe aprovação pelo modelo. Para operações financeiras, essa fronteira é correta.

**Tool Registry explícito.** Tools são capacidades fechadas, com schema, nível e handler. Texto do modelo não vira código nem acesso arbitrário.

**Auditoria e idempotência.** A correlação por ID, registro de provider/modelo, status e resultados permite diagnosticar o Agent e evita duplicação em retries.

**Providers isolados.** O Agent não contém condicionais de protocolo. Diferenças de Ollama e Mistral ficam em adapters, enquanto testes usam Fake.

**Testes offline extensos.** 501 testes e 93% de branch coverage dão confiança na lógica codificada. Contratos de segurança e provider têm testes direcionados, não só caminhos felizes.

**Tratamento seguro de JSON textual.** Não promover conteúdo parecido com chamada para Tool é uma fronteira de segurança correta e generalizável.

**Falha explícita, sem fallback.** Trocar Cloud por Local silenciosamente mudaria privacidade, custo e comportamento. O sistema recusa configuração em vez de esconder a mudança.

### Pontos fortes como produto

**Explicabilidade do cálculo.** A tela mostra os componentes da recomendação, não apenas “compre X”. Isso ajuda um operador a conferir o resultado.

**Proposta como etapa intermediária.** Separar recomendação de decisão respeita a realidade de compras e oferece um registro revisável.

**Fluxo básico completo dentro do protótipo.** Cadastro → movimento → análise → proposta → decisão existe de ponta a ponta, mesmo sem integração externa.

**Baixo risco de automação autônoma.** O produto não promete comprar sozinho. Esse limite é positivo em uma versão inicial.

Esses méritos tornam o projeto um bom laboratório de engenharia de Agents. Não bastam, por si, para demonstrar um produto competitivo.

## 14. O que ficou fraco

### Problema e usuário pouco definidos

O código não fixa se o usuário é lojista, almoxarife, comprador industrial, restaurante ou equipe de TI. Esses contextos têm demanda, unidade, lead time, criticidade e integração muito diferentes. Como consequência, o domínio ficou genérico: suficiente para demonstração, insuficiente para uma dor vertical concreta.

Não há evidência de entrevistas, frequência do problema, custo de ruptura, custo de excesso, tamanho da operação ou métrica de sucesso. O projeto definiu bem “como calcular”, mas não “para quem isso muda uma decisão” nem “quanto valor gera”.

### Fluxo operacional incompleto

A proposta aprovada não vira pedido de compra, não é enviada, não é acompanhada e não volta como recebimento. O sistema termina exatamente onde uma operação real começaria a capturar valor. Também não importa vendas ou saldo de outra fonte, exigindo digitação duplicada.

Sem integração, a confiança nos cálculos depende de disciplina manual. Para operações pequenas, uma planilha pode ser mais rápida; para operações maiores, a ausência de ERP/e-commerce torna o sistema isolado.

### Cálculo simples apresentado em arquitetura sofisticada

A fórmula usa média móvel simples e estoque mínimo fixo. Isso pode ser adequado a um MVP, mas a aplicação construiu multi-provider, Tool Calling, auditoria detalhada e configuração dinâmica ao redor de uma regra que caberia em uma planilha. A sofisticação técnica não está equilibrada com a sofisticação ou alcance do valor operacional.

### Agent com utilidade marginal e UX inconsistente

As telas já executam as ações principais com parâmetros visíveis e resultados estruturados. O Agent adiciona ambiguidade na seleção de Tool, custo de latência e dependência de modelo para chegar às mesmas funções.

O chat mostra histórico, mas não o envia para a execução seguinte. Isso cria expectativa de memória que o produto não cumpre. O usuário pode dizer “e o segundo?” e o modelo não terá o turno anterior. O problema não é só técnico; é uma promessa de interface incoerente.

A Tool WRITE existe e o prompt sugere criação mediante pedido explícito, mas o Agent web sempre a bloqueia porque `allow_write` fica falso. A segurança é boa, porém a capacidade percebida e a capacidade real divergem.

### Complexidade movida por tecnologia

O histórico recente concentra esforço em diferenças de protocolo, schemas, IDs, índices, comportamento de três modelos e Cloud. Esses são problemas interessantes de engenharia, mas não melhoram diretamente saldo, previsão, pedido, recebimento ou decisão de compra. O nome e a arquitetura parecem ter puxado o projeto para “ter um Agent” antes de validar se linguagem natural era o gargalo do usuário.

### Configuração e operação superdimensionadas para o estágio

Configuração singleton, seleção Local/Cloud, descoberta de modelos, SSRF, SDK Cloud, timeout e status de credencial são razoáveis em uma plataforma madura. Aqui, vieram antes de evidência de que um segundo provider era necessário. Cada caminho duplica matriz de testes e suporte.

### Lacunas de domínio

- não há sazonalidade, tendência ou incerteza;
- estoque mínimo é um número manual, não um nível de serviço calculado;
- não há compras em trânsito nem demanda comprometida;
- não há lote mínimo, múltiplo de embalagem, desconto por volume ou orçamento;
- não há múltiplos locais de estoque;
- fornecedor preferencial não é único;
- não há histórico de preço ou desempenho;
- não há pedido, recebimento, estorno formal ou conciliação;
- não há alertas, tarefas ou fila de itens a decidir além das telas;
- não há importação/exportação e integrações;
- não há contexto de organização/tenant.

### Administração e auditoria ainda incompletas como produto

O log é tecnicamente rico, mas não há política de retenção, exportação, busca avançada ou armazenamento imutável. O histórico de configuração omite o modelo, portanto não reconstrói totalmente uma troca. A administração atende demonstração e diagnóstico, não governança operacional completa.

### Documentação divergente

Documentos ainda descrevem o Fake como provider do chat e configuração por ambiente, embora o código tenha avançado. Essa divergência aumenta risco de decisões erradas por novos colaboradores. O README é deliberadamente mínimo e não ajuda a explicar estado ou público.

### Síntese crítica

O projeto resolveu muito bem problemas que surgem **depois** da decisão de usar um Agent — contrato de Tools, providers, auditoria, autorização — mas não demonstrou que o Agent resolve o problema mais caro do usuário. Há mais evidência de maturidade da infraestrutura do que de adequação produto-mercado.

## 15. IA: necessária ou não?

Se removermos o Agent, quase todo o valor principal continua existindo: cadastro, saldo, histórico, cálculo, risco, proposta e revisão humana. O fluxo web é capaz de entregar a recomendação determinística sozinho.

### Onde o LLM pode ajudar

- consulta ad hoc em linguagem natural para usuários ocasionais;
- explicação acessível dos números calculados;
- composição de um resumo que cruza estoque, consumo e fornecedor;
- descoberta de funções quando o usuário não conhece a navegação;
- futuramente, resumo de exceções ou priorização explicada, desde que os dados venham de serviços confiáveis.

### Onde software comum é melhor

- cálculo e classificação de risco;
- validação de saldo e preço;
- criação transacional de proposta;
- aprovação e rejeição;
- listagem, filtros, alertas e dashboards;
- integrações com vendas, compras e recebimento;
- tarefas repetitivas com critérios conhecidos.

### Onde a IA não é essencial hoje

O Agent é uma interface alternativa, não o motor de valor. Não há tarefa não estruturada central — como interpretar documentos variados, negociar texto complexo ou sintetizar grande volume de informação heterogênea — que exija LLM. A maior parte das perguntas previstas mapeia diretamente para poucas consultas e fórmulas.

### Complexidade adicionada

Providers, modelos, prompts, schemas, Tool Calling, retries, limites, auditoria específica, privacidade Cloud e testes de compatibilidade são custos permanentes. Modelos pequenos ainda erram seleção/argumentos, e modelos podem representar chamadas como texto. Para o produto atual, o ganho de conveniência não está comprovado como proporcional.

Conclusão: a IA é **útil como camada opcional de interação e explicação**, mas **não necessária ao valor central**. Ela só deveria ganhar prioridade após comprovar que usuários têm dificuldade real com a interface estruturada ou precisam fazer perguntas variadas que filtros comuns não atendem.

## 16. Quem usaria isso?

### Responsável por estoque de pequena operação

Problema plausível: acompanha poucos produtos manualmente e percebe faltas tarde. O sistema ajuda a centralizar movimentos, saldo e uma regra simples de reposição. Ainda é insuficiente se as vendas já vivem em outro sistema, porque exige novo lançamento manual e não suporta múltiplos locais ou código de barras.

### Comprador ou dono de pequena empresa

Problema plausível: precisa transformar consumo em uma lista de compras e revisar custo. O sistema mostra fornecedor, quantidade, preço total e proposta pendente. Ainda falta orçamento, consolidação por fornecedor, envio do pedido, condições comerciais e acompanhamento.

### Administrador da aplicação

Problema plausível: controlar acesso, provider e investigar ações do Agent. O sistema oferece configuração, auditoria e permissões. Esse é um perfil de operação técnica, não o comprador do valor principal.

### Operação de demonstração/estudo

O produto é particularmente adequado como laboratório educacional de Django, domínio transacional e Agent seguro. Nesse perfil, a amplitude técnica é uma vantagem. Isso não equivale a utilidade comercial.

Não há base no repositório para afirmar um mercado específico, volume ideal, disposição a pagar ou aderência a um setor regulado.

## 17. Utilidade real

### Em comparação com uma planilha

Vantagens atuais: constraints, concorrência transacional, controle de acesso, histórico de movimento, fórmula centralizada, propostas imutáveis, revisão e auditoria do Agent. Uma planilha comum dificilmente combina tudo isso com segurança.

Desvantagens: implantação e manutenção muito maiores; entrada ainda manual; pouca flexibilidade para alterar colunas; nenhuma importação; e o cálculo principal é simples o bastante para ser reproduzido. Para cinco ou dezenas de itens e uma pessoa, a planilha provavelmente vence em custo e velocidade.

### Em comparação com cálculo manual

O sistema reduz erro aritmético, aplica a mesma fórmula e deixa trilha. Isso é valor real quando há recorrência e mais de um usuário. Mas não reduz a coleta manual de dados nem garante que a fórmula represente a demanda futura.

### Em comparação com ERP ou ferramenta de compras

O ReplenishAgent é menor, compreensível e pode ser adaptado. Em contrapartida, não cobre integração, pedido, recebimento, fiscal, financeiro, múltiplos depósitos, catálogo amplo ou suporte operacional. Uma empresa que já usa ERP teria pouco motivo para duplicar dados aqui.

### O que tornaria a escolha convincente

Seria necessário escolher um nicho e entregar um resultado superior e mensurável, por exemplo:

- integrar automaticamente a fonte real de vendas/estoque;
- reduzir rupturas ou excesso com métrica antes/depois;
- produzir uma fila diária confiável de decisões;
- incorporar restrições reais do nicho;
- fechar o ciclo até pedido e recebimento, ou integrar-se ao sistema que o fecha;
- provar que a interface por linguagem natural economiza tempo em tarefas observadas;
- oferecer onboarding/importação simples e confiabilidade operacional.

Hoje, a vantagem mais sólida é engenharia segura e explicável, não uma proposta de valor claramente superior.

## 18. Complexidade versus valor

| Quadrante | Componentes | Justificativa |
|---|---|---|
| **Alto valor / baixa complexidade** | cadastro essencial; saldo; movimentos; validação de estoque negativo; fórmula simples de reposição; dashboard básico | São pré-requisitos compreensíveis, resolvem erros concretos e podem ser validados cedo. |
| **Alto valor / alta complexidade** | propostas com revisão humana; autorização; auditoria de escritas; integração automática futura | Protegem decisões e criam fluxo de trabalho. Integração teria alto valor, embora não exista hoje. |
| **Baixo valor / baixa complexidade** | conversa genérica; escolha manual de identificador de modelo; histórico visual sem contexto real | Acrescentam acabamento ou flexibilidade, mas pouco mudam a decisão de estoque. |
| **Baixo valor / alta complexidade** | multi-provider precoce; configuração dinâmica Local/Cloud; compatibilidade de Tool Calling entre modelos; Cloud antes de validação do uso; prompt extenso para compensar modelos | Consomem grande esforço e aumentam risco sem evidência de ganho proporcional para o usuário atual. |

Alguns componentes mudam de quadrante conforme o risco:

- **Segurança básica** é alto valor e complexidade moderada desde o início quando há autenticação e escrita. Hardening avançado sem usuários reais pode ser faseado.
- **Auditoria** é alto valor para ação financeira; para Agent somente leitura e protótipo individual, parte do detalhamento é prematura.
- **Tool Calling** é justificável se linguagem natural for validada como interface importante; sem essa validação, cai em baixo valor/alta complexidade.
- **Agent** não é intrinsecamente baixo valor. No escopo atual, ele é; em um problema com grande variedade de intenção e dados não estruturados, poderia migrar para alto valor.

## 19. O que faríamos diferente

### Definir primeiro

1. Um usuário primário concreto e seu contexto operacional.
2. A decisão recorrente que hoje custa tempo ou dinheiro.
3. As fontes reais dos dados e quem as mantém.
4. A métrica de sucesso: rupturas, excesso, tempo de compra, erro ou capital parado.
5. As restrições que realmente mudam a decisão no nicho.

### Construir primeiro

Um “walking skeleton” sem LLM: importar ou registrar poucos dados reais, gerar uma recomendação transparente e permitir ao usuário aceitá-la, alterá-la ou recusá-la. Medir uso e discordância. Se a entrada manual impedir teste, integração mínima vem antes de Agent.

Depois, fechar o ciclo que produz valor: fila de itens, proposta, consolidação e exportação/envio para o processo já usado. O objetivo não seria “ter cadastro”, mas completar uma decisão real.

### Deixar para depois

- Cloud e segundo provider;
- configuração dinâmica de modelos;
- Tool Calling paralelo;
- catálogo amplo de Tools;
- auditoria fina de interações somente de leitura;
- otimizações de prompt para vários modelos pequenos;
- UI administrativa de infraestrutura.

### Talvez não construir

Um Agent autônomo para um fluxo com cinco comandos previsíveis. Filtros, atalhos, formulários pré-preenchidos e alertas podem ser mais rápidos, baratos e confiáveis. Multi-provider talvez nunca seja necessário se a IA for auxiliar e um provider satisfizer requisitos de custo e privacidade.

### Quando introduzir IA

Somente após observar perguntas ou tarefas difíceis de expressar em interface tradicional. Primeiro como leitura/explicação, com métricas de sucesso e fallback visível. Escrita viria depois, sempre com preview, confirmação e idempotência.

### Como validar antes de arquitetar

- entrevistar poucos usuários do mesmo perfil;
- acompanhar o processo real e registrar decisões;
- prototipar com planilha ou tela única;
- rodar recomendações em sombra, sem executar compras;
- comparar com decisão humana e medir falsos positivos/negativos;
- testar disposição de usar semanalmente, não apenas opinião;
- definir critérios de abandono antes de investir em abstrações.

## 20. Lições para o próximo projeto

1. **Escreva a decisão do usuário antes da arquitetura.** “Quem decide o quê, com quais dados, com que frequência e qual custo do erro?” deve caber em um parágrafo.
2. **Valide a fonte dos dados cedo.** Um cálculo elegante sobre dados que ninguém manterá não vira produto.
3. **Construa o menor ciclo completo de valor.** Cadastro isolado não é MVP; entrada → decisão → consequência verificável é.
4. **Use regra determinística sempre que a regra é conhecida.** LLM pode explicar ou escolher uma capacidade, não deve substituir fórmula auditável.
5. **Adicione Agent somente para variabilidade real.** Se cinco botões cobrem o fluxo, Tool Calling provavelmente é custo, não vantagem.
6. **Não confunda naturalidade com confiabilidade.** Uma resposta fluente pode selecionar a Tool errada ou inventar argumentos. Autoridade permanece no backend.
7. **Texto nunca deve ganhar poder por parecer comando.** Apenas canais estruturados, schemas, autorização e handlers explícitos podem executar ações.
8. **Toda escrita de Agent precisa de dupla autorização.** Intenção explícita do usuário e permissão backend; ações de alto impacto exigem confirmação humana.
9. **Idempotência nasce junto com efeitos.** Retries e chamadas duplicadas são normais em integrações e Agents.
10. **Fake provider é investimento barato.** Permite desenvolver loop e segurança sem custo, rede ou flutuação.
11. **Um provider primeiro.** Crie uma interface mínima para não acoplar o domínio, mas só implemente um segundo adapter quando houver requisito concreto.
12. **Configuração dinâmica é produto.** Ela exige UI, validação, segurança, suporte e testes; não é apenas um dropdown.
13. **Coverage não valida utilidade.** Testes dizem que o sistema faz o que foi especificado, não que alguém precisa disso.
14. **Registre experimentos reproduzíveis.** Prompt, modelo, versão, configuração, RAW e critério devem virar artefato; memória de sessão não é evidência durável.
15. **Documentação precisa de dono e estado.** Marque documentos históricos ou atualize-os quando a arquitetura muda.
16. **Mostre limites na UX.** Um chat sem memória não deve parecer lembrar; uma proposta aprovada não deve parecer pedido enviado.
17. **Segurança acompanha o risco, não o entusiasmo técnico.** Autenticação, autorização, CSRF e invariantes precisam nascer com escrita; controles mais caros podem seguir o risco real.
18. **Meça complexidade total.** Cada provider ou modo adiciona código, testes, documentação, suporte, privacidade e matriz de falhas.
19. **Evite corrigir modelo com prompt indefinidamente.** Quando a tarefa é estruturada, melhore a interface ou remova o LLM do caminho crítico.
20. **Defina o que não será construído.** Limites explícitos evitam que uma prova de conceito se transforme em plataforma antes de encontrar uso.

## 21. O que vale reutilizar

**Separação LLM/domínio.** Reutilizar sempre que IA interagir com dinheiro, permissões, dados ou cálculos. O modelo propõe; o domínio valida e executa.

**Human-in-the-loop.** Útil em compras, pagamentos, publicação, exclusão, comunicação externa, decisões legais ou qualquer efeito difícil de reverter.

**Níveis de Tool.** READ/COMPUTE/WRITE/CRITICAL ajudam a expressar risco e aplicar políticas comuns. Faz sentido quando há várias capacidades e perfis; para duas funções simples, pode ser excesso.

**Registry fechado.** Adequado quando entrada não confiável escolhe operações. Evita despacho dinâmico e torna catálogo auditável.

**Fake provider e testes offline.** Reutilizáveis em qualquer integração probabilística ou paga. Separam correção do orquestrador de qualidade do modelo.

**Adapters de provider.** A ideia de uma interface pequena é valiosa; a lição é abstrair sem necessariamente implementar várias integrações cedo.

**Correlação por ID e idempotência.** Essencial para filas, webhooks, pagamentos, automações e Agents com retries.

**Validação determinística redundante.** Schema orienta o modelo, mas backend reafirma invariantes. Esse padrão vale para qualquer cliente externo.

**Auditoria sanitizada.** Útil quando é preciso explicar quem solicitou, qual capacidade rodou e qual resultado ocorreu. Deve vir com política de retenção e acesso.

**Falha sem fallback silencioso.** Reutilizar quando alternativas mudam custo, privacidade, segurança ou semântica.

**Snapshots imutáveis.** Propostas e decisões que dependem de preço ou regra no tempo devem preservar o contexto original.

**Transações e locks no saldo.** Generalizam para qualquer contador ou recurso concorrente que não pode ficar negativo.

## 22. Estado final

### Implementado e estável

- modelos e regras básicas de produto, fornecedor e relação;
- saldo e movimentos atômicos sem estoque negativo;
- cálculo determinístico de consumo, cobertura, ponto, alvo, risco e quantidade;
- análise web e em lote;
- criação manual de proposta a partir da análise;
- proposta pendente, snapshot e revisão humana irreversível;
- autenticação, permissões, CSRF e proteção de login;
- abstrações `LLMProvider`, `LLMMessage`, `LLMResponse`, `ToolDefinition` e `ToolCall`;
- FakeLLMProvider;
- OllamaProvider e contratos de Tool Calling, inclusive ID/index e fronteira de JSON textual;
- Tool Registry, policy, autorização, auditoria, sanitização e idempotência;
- configuração persistida Local/Ollama e chat conectado ao provider escolhido;
- suíte offline, coverage mínimo e CI.

“Estável” aqui significa coberto e validado no escopo do projeto, não operação produtiva em escala.

### Implementado, mas precisa melhorar

- UX de cadastro e navegação, ainda básica;
- dashboard, que usa apenas saldo versus mínimo e não toda a análise de risco;
- chat, cujo histórico é visual mas não contextual;
- seleção de fornecedor preferencial sem unicidade;
- motor de reposição, correto para a fórmula simples mas limitado para demanda real;
- fluxo de proposta, que termina na decisão e não fecha compra/recebimento;
- auditoria, sem retenção, busca robusta ou armazenamento imutável;
- documentação, com trechos desatualizados;
- lint Ruff com conjunto estreito de regras;
- readiness de produção, dependente de infraestrutura não incluída.

### Em desenvolvimento

- MistralProvider endurecido no worktree e testado offline;
- factory `CLOUD/mistral` e ausência de fallback;
- status de credencial por ambiente na UI;
- teste de conexão Mistral por catálogo de modelos;
- alternância Local/Cloud no código e testes.

Esses itens não foram commitados nem validados contra API Mistral real. A configuração persistida não foi trocada para Cloud.

### Não implementado

- chamada real e validação operacional da Mistral Cloud;
- entrada de API key pelo navegador — deliberadamente não desejada;
- memória conversacional real entre mensagens;
- pedido de compra, envio ao fornecedor e recebimento;
- integração com ERP, PDV, e-commerce ou fiscal;
- importação/exportação operacional;
- previsão com sazonalidade/incerteza;
- múltiplos depósitos, reservas, lotes e validade;
- orçamento, aprovação em níveis e condições comerciais;
- notificações e automações agendadas;
- multiempresa/tenant;
- Tool CRITICAL concreta;
- execução concorrente de Tool Calls paralelas;
- política completa de privacidade e retenção Cloud.

### Ideias e próximos passos antigos

- documentos antigos tratam conexão com provider real como futura; isso já foi parcialmente superado pelo Ollama;
- Cloud/Mistral era a fase corrente, mas foi interrompida antes de teste real;
- experimentos de compatibilidade sugeriram investigar modelo/schema, sem justificar redesign;
- hardening de produção, proxy TLS e operação continuam dependentes de ambiente;
- não há evidência de roadmap validado por usuário, apenas sequência técnica.

### Abandonado ou não concluído

Não há feature explicitamente marcada como abandonada no Git. O que está incompleto é o salto de proposta aprovada para processo real de compra, a conversa multi-turno e a validação Cloud. Eles devem ser chamados de não concluídos, não presumidos como roadmap ativo.

## 23. Contexto para planejar um novo projeto

O ReplenishAgent foi construído como uma aplicação web de estoque e reposição. A ideia central era usar dados de produto, fornecedor, saldo e consumo para identificar risco de ruptura, calcular uma quantidade de reposição e preparar uma proposta de compra. O humano continuaria responsável por aprovar ou rejeitar. Uma camada de Agent permitiria acessar essas capacidades em linguagem natural, usando modelos locais ou Cloud.

O projeto chegou a um fluxo demonstrável. Produtos e fornecedores são cadastrados; cada relação contém preço, lead time e preferência. Entradas e saídas mantêm saldo com transação e proteção contra negativo. Saídas recentes geram consumo médio. Um motor Python calcula cobertura, ponto de reposição, estoque-alvo, risco e quantidade. A análise pode gerar uma proposta `PENDING`, imutável em seus dados econômicos, que um usuário autorizado aprova ou rejeita.

O principal acerto foi não entregar a matemática ao LLM. O modelo pode escolher uma Tool e explicar seu resultado, mas saldo, consumo, risco e quantidade vêm de código determinístico. A mesma filosofia aparece na segurança: Tools formam um catálogo fechado; READ, COMPUTE, WRITE e CRITICAL têm policies; escrita exige permissão backend; ações críticas são bloqueadas; propostas exigem decisão humana. Auditoria, sanitização, correlação por ID e idempotência completam uma base tecnicamente sólida.

O Agent usa uma interface comum de providers. Há um Fake determinístico para testes, Ollama local operacional e um adapter Mistral Cloud implementado e testado offline no worktree, mas ainda não validado em API real. O OllamaProvider preserva Tool Calls estruturadas e não promove JSON textual a comando. A suíte chegou a 501 testes e 93% de branch coverage, com domínio, web, segurança, Agent e providers cobertos.

Como engenharia, o projeto ensina bons padrões. Como produto, ele não encontrou ainda uma justificativa equivalente para toda essa estrutura. O repositório não identifica claramente o usuário primário, o nicho, a dor quantificada ou uma métrica de sucesso. A fórmula de reposição é simples e o dado precisa ser digitado manualmente. Uma proposta aprovada não vira pedido, não é enviada e não gera recebimento. Portanto, o sistema termina antes de fechar o ciclo econômico que justificaria seu uso.

Sem o Agent, quase todo o valor principal permanece. As telas já calculam, mostram e criam propostas. A IA melhora potencialmente a consulta e a explicação, mas hoje é uma interface alternativa para um conjunto pequeno de ações estruturadas. Em troca, trouxe providers, schemas, prompts, diferenças de protocolo, instabilidade de modelos, privacidade Cloud e grande matriz de testes. Os experimentos locais mostraram que modelos diferentes usam o canal estruturado de maneiras diferentes; também mostraram que não se deve confundir JSON textual com autorização para agir. Não provaram que schema complexo é a causa geral, nem que um modelo é universalmente melhor.

O maior erro de sequência foi aprofundar a arquitetura de Agent e multi-provider antes de validar utilidade. A equipe resolveu problemas sofisticados que só existem depois que se decide usar LLM, enquanto problemas mais próximos do valor — integração de dados, fila diária de decisões, pedido, recebimento, restrições comerciais e aderência a um nicho — ficaram ausentes. O produto é mais convincente como laboratório de engenharia segura do que como alternativa atual a uma planilha ou ERP.

Para um próximo projeto, a ordem deve ser invertida. Primeiro definir uma pessoa específica, uma decisão recorrente, a fonte dos dados, o custo do erro e a métrica de sucesso. Depois construir o menor ciclo completo que produz resultado observável, mesmo que seja uma tela ou planilha. Validar com uso real antes de generalizar. Regras conhecidas devem continuar determinísticas. IA deve entrar apenas onde existe linguagem, ambiguidade ou volume não estruturado que uma interface comum não resolve bem.

Se IA entrar, começar com leitura e explicação. Medir se economiza tempo e se os usuários confiam. Só depois permitir efeitos, sempre com preview, autorização, idempotência e humano no circuito. Uma abstração pequena pode evitar acoplamento ao primeiro provider, mas um segundo provider só deve ser implementado quando privacidade, custo, disponibilidade ou qualidade criarem uma necessidade real.

Os princípios que devem orientar o próximo projeto são:

- problema e usuário antes da stack;
- fonte de dados antes do algoritmo;
- ciclo completo de valor antes da plataforma;
- métrica de resultado antes de coverage como símbolo de sucesso;
- regra determinística antes de LLM;
- interface simples antes de Agent;
- um provider antes de multi-provider;
- segurança proporcional desde o primeiro efeito real;
- experimentos reproduzíveis antes de conclusões sobre modelos;
- limites explícitos para impedir que curiosidade técnica substitua validação de produto.

O ReplenishAgent não deve ser lido como fracasso. Ele demonstrou uma arquitetura cuidadosa e produziu aprendizados concretos sobre domínio, transações, Human-in-the-loop e Tool Calling. O encerramento honesto é que a engenharia amadureceu mais do que a proposta de valor. O próximo projeto deve preservar essa disciplina técnica, mas investir primeiro na clareza do problema e na prova de utilidade.

---

## Fontes examinadas e limitações históricas

Foram usados: models e migrations dos apps de produtos, fornecedores, inventário, compras e Agent; serviços de inventário, reposição e propostas; cálculos; Agent, Tools, providers, factory, configuração, autorização, auditoria e sanitização; views, forms, URLs, templates e navegação; configuração Django, Docker/Compose, requirements, coverage, Ruff e CI; testes de domínio, Agent, providers, segurança e web; README; documentos de configuração e segurança; e histórico de commits desde a infraestrutura inicial até os ajustes de Tool Calling.

As limitações principais são: ausência de pesquisa de usuário versionada; ausência de métricas de uso; ausência de artefatos RAW versionados para todos os experimentos; documentação histórica parcialmente desatualizada; mudanças Mistral ainda não commitadas; e nenhuma validação de produção ou Cloud real usada nesta análise.

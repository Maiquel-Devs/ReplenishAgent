# Configuração da IA (Fase 14.5.3, correção do endpoint)

A seleção global fica em `AIConfiguration` (linha de chave 1). O banco é a fonte de verdade para tipo, integração, modelo e endpoint local. Para LOCAL/Ollama, o endpoint é obrigatório; para CLOUD/Mistral, deve estar vazio. A migration 0004 adiciona o campo sem alterar registros anteriores. Se uma configuração LOCAL anterior existir, o administrador precisa informar seu endpoint antes de usá-la.

## Política de endpoint local

`normalize_local_endpoint` centraliza a validação. Aceita apenas origens HTTP/HTTPS com porta explícita, sem usuário, senha, caminho adicional, query ou fragmento. As portas aceitas são 1024–65535 e HTTPS/443. Os únicos nomes DNS aceitos são `localhost` e `host.docker.internal`; também são aceitos IPs literais de loopback, RFC1918 e IPv6 ULA. Endereços públicos, link-local, metadados de nuvem, nomes arbitrários e formatos alternativos de IP são rejeitados.

Esta política permite acesso a serviços nas redes privadas a partir do servidor: conceda `agent.configure_ai` somente a administradores confiáveis. A aplicação não faz uma consulta DNS de validação seguida de outra resolução HTTP, que seria vulnerável a rebinding. Os dois nomes fixos dependem do mapeamento local/Docker administrado pela plataforma. O cliente HTTP ignora proxies do ambiente e não segue redirecionamentos. Uma implantação com DNS/hosts comprometidos continua fora desta fronteira de confiança.

## Fonte de verdade e teste

A factory usa o endpoint salvo para a seleção persistida, sem fallback para `OLLAMA_BASE_URL`. Essa variável permanece apenas para chamadas explícitas da factory em testes/desenvolvimento. `OLLAMA_TIMEOUT` continua técnico. `LLM_PROVIDER`, `OLLAMA_MODEL` e `MISTRAL_MODEL` continuam legados e ignorados pela seleção padrão. `MISTRAL_API_KEY` permanece somente no ambiente.

O botão **Testar conexão** envia POST com CSRF, valida LOCAL/Ollama e o endpoint, e chama `GET /api/tags` da [API oficial do Ollama](https://docs.ollama.com/api/tags), sem prompt ou inferência. A resposta fornece nomes para sugestões no campo Modelo; testar não salva a configuração nem cria auditoria. GET normal não acessa a rede. Respostas inválidas, redirecionamentos, falha de conexão e timeout exibem mensagem genérica. O identificador salvo do modelo permanece no campo mesmo se não aparecer na descoberta. Salvar continua gerando `AIConfigurationChange`, que não inclui endpoint, modelo nem credencial.

O chat atual continua uma prévia offline com FakeLLMProvider explícito. Conectar a seleção persistida ao fluxo real do Agent e validar capacidade de tool calling ficam para a 14.5.4.

No ambiente Docker/Windows observado nesta correção, o container não resolve `host.docker.internal` e o Ollama escuta somente em `127.0.0.1:11434` no host. A aplicação não altera DNS, firewall ou bind do runtime automaticamente. Para o teste real funcionar, a implantação precisa fornecer uma rota de host confiável e expor o Ollama apenas à rede necessária, com restrição de firewall. A configuração global anterior foi preservada, mas está incompleta até que o administrador salve um endpoint alcançável.

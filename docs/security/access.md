# Autenticação, lockout e acesso ao Agent

## Fluxo de autenticação

O ReplenishAgent usa as sessões, o formulário de autenticação e as views de
login/logout do Django. A interface é própria, mas a validação de credenciais e
o redirecionamento seguro do parâmetro `next` permanecem sob responsabilidade
do framework.

`LoginRequiredMiddleware` protege a aplicação por padrão. O health check é
marcado explicitamente como público. Assim, novas views ficam protegidas a
menos que recebam uma decisão explícita em contrário.

O logout aceita somente POST e mantém proteção CSRF.

## Proteção contra brute force

O projeto usa `django-axes` 8.x com o handler de banco de dados. As tentativas
e o estado de lockout são compartilhados pelos workers através do PostgreSQL.

Configuração padrão:

~~~dotenv
DJANGO_LOGIN_FAILURE_LIMIT=5
DJANGO_LOGIN_COOLOFF_MINUTES=15
~~~

Ambos os valores precisam ser inteiros maiores que zero. Valores inválidos
impedem a inicialização da aplicação.

O lockout combina usuário e endereço do peer TCP em `REMOTE_ADDR`. Headers
como `X-Forwarded-For` não são usados, pois podem ser forjados se o proxy não
os sobrescrever corretamente. Atrás de proxy, `REMOTE_ADDR` representa o
proxy que abriu a conexão com o Django; portanto, o limite continua separado
por usuário e pelo peer confiável observado pelo servidor.

Essa configuração deve ser revista junto da topologia do proxy no futuro
deploy, sem trocar para headers encaminhados antes de garantir que o proxy
remova valores enviados pelo cliente.

O bloqueio retorna HTTP 429 e inclui `Retry-After`. A mensagem é genérica tanto
para usuários existentes quanto inexistentes. O Axes também mascara usuário,
IP e password nos próprios logs.

Para desbloqueio operacional antecipado, use os comandos oficiais do Axes,
por exemplo:

~~~text
python manage.py axes_reset_username nome-do-usuario
~~~

## Interface do Agent

A rota `/agent/` exige autenticação e usa Django Templates + Bootstrap. O
histórico curto da conversa fica na sessão do usuário.

Nesta etapa, cada envio passa pelo `ReplenishAgent` existente com:

- `FakeLLMProvider` determinístico;
- registry real de Tools;
- política padrão sem escrita;
- contexto de autorização do usuário;
- auditoria sanitizada em banco.

Nenhum provider real é criado e nenhuma chamada externa é realizada.

## Administração de IA

A seção “Configuração da IA” usa a permissão dedicada
`agent.configure_ai`. Ocultar o link é apenas UX; o endpoint também verifica
a permissão no backend.

A tela apresenta:

- providers preparados: Ollama e Mistral;
- provider selecionado por `LLM_PROVIDER`;
- modelo correspondente configurado no ambiente.

A tela é somente informativa nesta fase. Ela não exibe nem recebe API keys,
não persiste uma segunda configuração no banco e não instancia providers.
Essa decisão evita conflito entre banco e ambiente antes de existir um fluxo
completo e seguro para ativação de credenciais.

## Privacidade e auditoria

Credenciais de login não são enviadas à auditoria do Agent. Passwords não são
registrados nos logs de autenticação. Mensagens da conversa continuam sujeitas
à sanitização de auditoria introduzida no hardening da Fase 14.

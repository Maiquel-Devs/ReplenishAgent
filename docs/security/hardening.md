# Hardening e configuração de produção

Este documento descreve a base de segurança preparada na Fase 14. Ele não é
um guia de deploy e não substitui a definição da infraestrutura de produção.

## Desenvolvimento local

Copie `.env.example` para `.env` e troque os valores de desenvolvimento. O
arquivo `.env` é ignorado pelo Git.

O desenvolvimento HTTP local deve manter:

~~~dotenv
DJANGO_DEBUG=True
DJANGO_HTTPS_ENABLED=False
DJANGO_TRUST_PROXY_SSL_HEADER=False
DJANGO_SECURE_HSTS_SECONDS=0
~~~

O Compose usa `runserver` para preservar recarga automática e um fluxo local
simples. O PostgreSQL não publica a porta 5432 no host.

## Base para produção

Em produção, forneça todas as credenciais pelo ambiente ou pelo mecanismo de
segredos da plataforma. Nunca reutilize os exemplos:

~~~dotenv
DJANGO_SECRET_KEY=<valor-longo-aleatório-e-exclusivo>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=app.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://app.example.com
DJANGO_HTTPS_ENABLED=True
DJANGO_TRUST_PROXY_SSL_HEADER=True
DJANGO_SECURE_HSTS_SECONDS=3600
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=False
DJANGO_SECURE_HSTS_PRELOAD=False
~~~

Com `DJANGO_HTTPS_ENABLED=True`, cookies de sessão e CSRF recebem o atributo
`Secure`, requisições HTTP são redirecionadas para HTTPS e HSTS começa com uma
hora. Os controles podem ser ajustados individualmente com:

- `DJANGO_SESSION_COOKIE_SECURE`;
- `DJANGO_CSRF_COOKIE_SECURE`;
- `DJANGO_SECURE_SSL_REDIRECT`;
- `DJANGO_SECURE_HSTS_SECONDS`;
- `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS`;
- `DJANGO_SECURE_HSTS_PRELOAD`.

Não desligue cookies seguros nem o redirecionamento em uma implantação HTTPS.
Inclua em `DJANGO_CSRF_TRUSTED_ORIGINS` apenas origens confiáveis completas,
com esquema, separadas por vírgula.

## Proxy reverso e HTTPS

`DJANGO_TRUST_PROXY_SSL_HEADER=True` configura:

~~~python
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
~~~

Ative essa opção somente quando:

1. o proxy sobrescrever, e não apenas repassar, `X-Forwarded-Proto`;
2. o Gunicorn não estiver acessível diretamente por clientes externos;
3. o proxy for o único caminho de entrada da aplicação.

Sem essas garantias, um cliente pode forjar o header. Quando a opção estiver
ativa, o proxy deve enviar `X-Forwarded-Proto: https` para evitar loops no
redirecionamento SSL.

O proxy futuro também deve terminar TLS, ocultar headers de identificação do
servidor quando necessário, definir limites de requisição e servir os arquivos
estáticos. Nenhum proxy foi adicionado nesta fase.

## HSTS

HSTS fica desligado no HTTP local. Em produção, comece com um período curto,
valide todos os fluxos por HTTPS e aumente progressivamente até:

~~~dotenv
DJANGO_SECURE_HSTS_SECONDS=31536000
~~~

Habilite `INCLUDE_SUBDOMAINS` somente quando todos os subdomínios suportarem
HTTPS. Habilite `PRELOAD` somente após cumprir os requisitos da lista de
preload e aceitar que a reversão pode demorar. Essas opções não devem ser
ativadas apenas para eliminar warnings.

## Servidor de aplicação

A imagem usa Gunicorn como comando padrão e executa com usuário não-root:

~~~text
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 30
~~~

O `compose.yaml` sobrescreve esse comando com `runserver` exclusivamente para
desenvolvimento. A escolha de quantidade de workers deve ser revisada com
dados da infraestrutura futura.

## Verificação

Execute o check de deploy com configuração equivalente à produção:

~~~text
DJANGO_DEBUG=False
DJANGO_HTTPS_ENABLED=True
DJANGO_SECURE_HSTS_SECONDS=31536000
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=True
DJANGO_SECURE_HSTS_PRELOAD=True
python manage.py check --deploy
~~~

Use valores não secretos de validação para `DJANGO_SECRET_KEY`,
`DJANGO_ALLOWED_HOSTS` e banco. Um check limpo não substitui revisão da
topologia, TLS, proxy, armazenamento de segredos, backups e observabilidade.

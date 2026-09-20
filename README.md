# ReplenishAgent

Agente inteligente para automatizar a análise de estoque, identificar riscos de ruptura e planejar reposições e compras utilizando LLMs locais ou em nuvem.

## Segurança

- [Validação básica de segurança](docs/security/pentest.md)
- [Hardening e configuração de produção](docs/security/hardening.md)
- [Autenticação, lockout e acesso ao Agent](docs/security/access.md)

O Compose do repositório é voltado ao desenvolvimento local. Ele mantém o
PostgreSQL sem porta publicada e sobrescreve o comando da imagem para usar o
servidor de desenvolvimento do Django.

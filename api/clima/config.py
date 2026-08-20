"""Configuração por ambiente.

Convenção de nomes no projeto: campos técnicos e temporais em inglês
(``fetched_at``, ``http_status``, ``tenant_id``), campos de domínio em português
(``redistribuicao``, ``resultado``, ``atribuicao_exigida``). É deliberado — o
domínio é brasileiro, a infraestrutura é convenção da linguagem.
"""

from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Tenant que possui o pipeline compartilhado de ingestão. Fixo e conhecido: uma
# coleta do USGS serve todos os clientes, não faz sentido duplicá-la por tenant.
# Ver api/README.md, seção "Multi-tenancy".
TENANT_SISTEMA = UUID("00000000-0000-0000-0000-000000000001")


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = Field(
        default="postgresql+psycopg://clima_app:clima@localhost:5432/clima",
        description=(
            "DSN da aplicação. Precisa ser um papel NOSUPERUSER/NOBYPASSRLS — "
            "superusuário ignora RLS e torna o isolamento entre tenants inócuo."
        ),
    )
    database_url_admin: str | None = Field(
        default=None,
        description=(
            "DSN do dono do esquema, usado só por migrations. Se ausente, "
            "as migrations caem em database_url."
        ),
    )
    redis_url: str = "redis://localhost:6379"

    # Identidade enviada às fontes públicas. Várias pedem contato no User-Agent;
    # o USGS pode bloquear cliente anônimo em volume.
    user_agent: str = "ClimaGlobal/0.1 (+contato@exemplo.com.br)"
    http_timeout_seg: float = 20.0

    # Lacuna de coleta a partir da qual soa o alarme. Ver §10 do plano.
    lacuna_alarme_seg: int = 300

    # Meses de partição criados à frente do mês corrente.
    particoes_futuras: int = 2

    log_json: bool = True

    # Escritas administrativas (como revisão humana) ficam fechadas por padrão.
    # A API pública de leitura continua disponível sem credencial.
    admin_api_key: str | None = None
    rate_limit_por_minuto: int = Field(default=120, ge=1, le=100_000)
    alert_webhook_url: str | None = None

    @property
    def database_url_async(self) -> str:
        return self.database_url

    @property
    def database_url_migracao(self) -> str:
        return self.database_url_admin or self.database_url


@lru_cache
def config() -> Config:
    return Config()

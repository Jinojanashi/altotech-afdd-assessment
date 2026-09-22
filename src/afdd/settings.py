from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://afdd:afdd-local-only@db:5432/afdd"
    redpanda_brokers: str = "redpanda:9092"
    telemetry_topic: str = "telemetry.raw.v1"
    afdd_evaluation_topic: str = "telemetry.accepted.v1"
    simulator_source_dir: str = "/app/data/candidate-starter-pack/sample-telemetry"
    seed_source_dir: str = "/app/data/candidate-starter-pack/building-and-equipment"
    simulator_interval_seconds: int = 60
    simulator_acceleration_factor: float = 60.0

    @property
    def broker_list(self) -> list[str]:
        return [broker.strip() for broker in self.redpanda_brokers.split(",") if broker.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

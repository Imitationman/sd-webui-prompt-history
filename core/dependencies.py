# from pydantic_settings import BaseSettings
from pydantic import Field, BaseModel


class Settings(BaseModel):
    MODULE_PATH: str = Field(default="", env="MODULE_PATH")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()

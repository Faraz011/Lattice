"""Turn a configured model string into a Pydantic AI model (R10, KTD1).

`google:...` uses the Gemini key from settings, `anthropic:...` the Anthropic key, `test` the
deterministic test model, `scripted` a fixed offline policy (see `scripted.py`), and any other
provider Pydantic AI knows reads its own environment.
"""

from pydantic import SecretStr
from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider

from lattice.agents.scripted import SCRIPTED, scripted_model
from lattice.config import Settings


def _secret(value: SecretStr | None) -> str | None:
    return value.get_secret_value() or None if value else None


def build_model(model: str, settings: Settings) -> Model:
    if model == "test":
        return TestModel()
    if model == SCRIPTED:
        return scripted_model()
    provider, _, name = model.partition(":")
    if provider == "google":
        return GoogleModel(name, provider=GoogleProvider(api_key=_secret(settings.gemini_api_key)))
    if provider == "anthropic":
        return AnthropicModel(
            name, provider=AnthropicProvider(api_key=_secret(settings.anthropic_api_key))
        )
    return infer_model(model)


def model_for_role(role: str, settings: Settings) -> str:
    return settings.role_models.get(role, settings.model)

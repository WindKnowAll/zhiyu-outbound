import pytest

from zhiyu.config import load_settings
from zhiyu.providers.base import ProviderError
from zhiyu.providers.factory import create_language_model, create_recognizer, create_synthesizer


def test_factory_refuses_to_build_providers_without_a_key():
    settings = load_settings({})
    with pytest.raises(ProviderError, match="DASHSCOPE_API_KEY"):
        create_recognizer(settings)
    with pytest.raises(ProviderError, match="DASHSCOPE_API_KEY"):
        create_language_model(settings)
    with pytest.raises(ProviderError, match="DASHSCOPE_API_KEY"):
        create_synthesizer(settings)

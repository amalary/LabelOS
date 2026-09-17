"""Deterministic test adapter, never registered by production code; no I/O."""

from labelos_api.publishing.providers import (
    ProviderCapabilities,
    ProviderOutcome,
    ProviderResult,
)


class FakePublishingAdapter:
    def __init__(self, *results, reconcile=True, publish=True, rejection=None):
        self.capabilities = ProviderCapabilities(publish=publish, reconcile=reconcile)
        self.results = list(results)
        self.rejection = rejection
        self.validations = []
        self.publications = []
        self.observations = []

    def validate(self, request):
        self.validations.append(request)
        if isinstance(self.rejection, Exception):
            raise self.rejection
        return self.rejection

    def _next(self):
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    async def publish(self, request):
        self.publications.append(request)
        return self._next()

    async def reconcile(self, request):
        self.observations.append(request)
        if not self.capabilities.reconcile:
            return ProviderResult(outcome=ProviderOutcome.unsupported)
        return self._next()

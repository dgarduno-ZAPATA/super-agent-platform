from __future__ import annotations

import os

import httpx

_METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/" "service-accounts/default/token"
)


class VertexEmbeddingAdapter:
    """Genera embeddings de Vertex AI para documentos y queries."""

    MODEL = "text-embedding-004"

    def __init__(
        self,
        project_id: str,
        region: str = "us-central1",
        model_name: str = MODEL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._project_id = project_id
        self._region = region
        self._model_name = model_name
        self._client = client or httpx.AsyncClient(timeout=30.0)

    async def embed(self, text: str) -> list[float]:
        return await self._embed_one(text=text, task_type="RETRIEVAL_DOCUMENT")

    async def embed_query(self, text: str) -> list[float]:
        return await self._embed_one(text=text, task_type="RETRIEVAL_QUERY")

    async def _embed_one(self, text: str, task_type: str) -> list[float]:
        access_token = await self._resolve_access_token()
        endpoint = (
            f"https://{self._region}-aiplatform.googleapis.com/v1/projects/"
            f"{self._project_id}/locations/{self._region}/publishers/google/models/"
            f"{self._model_name}:predict"
        )
        payload = {
            "instances": [{"content": text, "taskType": task_type}],
        }
        response = await self._client.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()

        body = response.json()
        predictions = body.get("predictions")
        if not isinstance(predictions, list) or not predictions:
            raise RuntimeError("vertex embeddings response missing predictions")

        first = predictions[0]
        if not isinstance(first, dict):
            raise RuntimeError("vertex embeddings response format is invalid")

        embeddings = first.get("embeddings")
        values = embeddings.get("values") if isinstance(embeddings, dict) else None
        if not isinstance(values, list):
            raise RuntimeError("vertex embeddings response missing embedding values")

        vector: list[float] = []
        for value in values:
            if isinstance(value, int | float):
                vector.append(float(value))
            else:
                raise RuntimeError("vertex embeddings response contains non-numeric values")
        return vector

    async def _resolve_access_token(self) -> str:
        env_token = os.environ.get("GOOGLE_OAUTH_ACCESS_TOKEN")
        if env_token is not None and env_token.strip():
            return env_token.strip()

        response = await self._client.get(
            _METADATA_TOKEN_URL,
            headers={"Metadata-Flavor": "Google"},
        )
        response.raise_for_status()
        body = response.json()
        token = body.get("access_token") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise RuntimeError("unable to resolve ADC access token from metadata server")
        return token

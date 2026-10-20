from pydantic_ai import models

# No test reaches a real model; the `live` test turns this back on for itself.
models.ALLOW_MODEL_REQUESTS = False

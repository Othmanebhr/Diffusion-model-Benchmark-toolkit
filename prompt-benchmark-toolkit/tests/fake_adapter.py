from __future__ import annotations

import base64


PNG_1X1 = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
)


def generate(request):
    return {
        'image_bytes': PNG_1X1,
        'extension': '.png',
        'metadata': {'fake': True, 'variant_id': request['variant_id']},
    }


"""Print the public enrolment material for Daily SIG Systems administrators."""
from __future__ import annotations

import json

from app.adapters.browser_local.identity import DeviceIdentityStore
from app.infrastructure.config import get_settings


def main() -> None:
    settings = get_settings()
    identity = DeviceIdentityStore(settings.browser_local_data_dir).load_or_create()
    print(json.dumps(identity.enrollment_payload(), indent=2))


if __name__ == "__main__":
    main()

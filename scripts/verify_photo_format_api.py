"""Run after verify_photo_format_browser.mjs; only an isolated test database is used."""

from pathlib import Path

import respx
from tests.conftest import client as client
from tests.conftest import test_settings as test_settings
from tests.merchant_applyments.test_applyments import FIELDS, PNG
from tests.merchant_applyments.test_applyments import draft as draft
from tests.merchant_applyments.test_applyments import keys as keys


async def test_browser_prepared_photos_save_and_clear_attachment_blockers(client, draft):
    root = Path(__file__).resolve().parents[1] / ".data/photo-format-fixtures"
    cases = {
        "store_front": "webp-as-jpg",
        "store_inside": "jpeg-with-trailer",
        "mini_program_1": "png-as-jpg",
    }
    assert all((root / (name + ".bin")).is_file() for name in cases.values()), (
        "Run verify_photo_format_browser.mjs first to generate synthetic photos"
    )
    headers, row = draft
    path = "/api/v1/merchant-applyments/" + row["id"]
    with respx.mock(assert_all_called=False) as provider:
        response = await client.put(
            path, headers=headers, json={"version": row["version"], "fields": FIELDS}
        )
        assert response.status_code == 200
        row = response.json()
        for kind in ["license", "id_front", "id_back"]:
            response = await client.post(
                path + f"/attachments/{kind}?version={row['version']}", headers=headers, content=PNG
            )
            assert response.status_code == 200
            row = response.json()
        for kind, name in cases.items():
            data = (root / (name + ".bin")).read_bytes()
            response = await client.post(
                path + f"/attachments/{kind}?version={row['version']}",
                headers=headers,
                content=data,
            )
            assert response.status_code == 200, response.text
            row = response.json()
        saved = (await client.get(path, headers=headers)).json()
        assert saved["issues"] == []
        assert len(saved["attachments"]) == 6
        assert saved["state"] == "draft" and saved["applyment_id"] is None
        assert not provider.calls

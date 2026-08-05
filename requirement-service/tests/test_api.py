"""Flask test-client requirement API tests."""
from uuid import uuid4

from requirement_service.app import create_app


def test_create_is_idempotent_and_cross_project_is_404():
    client = create_app().test_client()
    project, actor = uuid4(), uuid4()
    payload = {"title":"Checkout","type":"user_story","owner_id":str(uuid4()),"release_version_id":str(uuid4()),"acceptance_criteria":[{"id":"a","given":"g","when":"w","then":"t"}]}
    headers = {"Idempotency-Key":"once","X-Actor-Id":str(actor)}
    first = client.post(f"/api/v1/projects/{project}/requirements", json=payload, headers=headers)
    replay = client.post(f"/api/v1/projects/{project}/requirements", json=payload, headers=headers)
    assert first.status_code == replay.status_code == 201
    item_id = first.json["data"]["id"]
    assert client.get(f"/api/v1/projects/{uuid4()}/requirements/{item_id}").status_code == 404
    conflict = client.post(f"/api/v1/projects/{project}/requirements", json={**payload,"title":"Changed"}, headers=headers)
    assert conflict.status_code == 409

"""
syngen_client.py
----------------
HTTP client for the syngen-api synthetic data service.
All methods return parsed JSON responses or raise SyngenError on failure.
"""

import json
import logging
import requests
import urllib3

# Suppress InsecureRequestWarning for self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger("syngen_client")
log.setLevel(logging.DEBUG)
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s"))
    log.addHandler(_h)


class SyngenError(Exception):
    """Raised when a syngen-api call fails."""
    def __init__(self, message: str, status_code: int = None, detail: str = None):
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)


class SyngenClient:
    """Thin wrapper around syngen-api REST endpoints."""

    def __init__(self, base_url: str, api_key: str):
        self.base = base_url.rstrip("/") + "/dct/v3"
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update({
            "Authorization": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        log.debug("SyngenClient initialized: base_url=%s", self.base)

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base}{path}"
        body = kwargs.get("json")
        log.debug(">>> %s %s", method, url)
        if body:
            log.debug(">>> body: %s", json.dumps(body, indent=2))

        resp = self.session.request(method, url, **kwargs)
        log.debug("<<< %s %s -> %d", method, url, resp.status_code)
        log.debug("<<< response: %s", resp.text[:1000] if resp.text else "(empty)")

        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("message", resp.text)
            except Exception:
                detail = resp.text
            log.error("API error: %s %s -> %d: %s", method, path, resp.status_code, detail)
            raise SyngenError(
                f"syngen-api {method} {path} returned {resp.status_code}: {detail}",
                status_code=resp.status_code,
                detail=detail,
            )
        if resp.status_code == 204 or not resp.text:
            return {}
        return resp.json()

    # ── Applications ─────────────────────────────────────────

    def search_applications(self, name: str) -> list[dict]:
        log.debug("Searching for application: name=%s", name)
        body = {"filter_expression": f"name eq '{name}'"}
        resp = self._request("POST", "/synthetic/applications/search", json=body)
        items = resp.get("items", [])
        log.debug("Found %d application(s)", len(items))
        return items

    def create_application(self, name: str, description: str = "") -> dict:
        log.debug("Creating application: name=%s", name)
        body = {"name": name, "description": description}
        resp = self._request("POST", "/synthetic/applications", json=body)
        log.debug("Application created: id=%s", resp.get("id"))
        return resp

    def get_application(self, app_id: str) -> dict:
        log.debug("Getting application: id=%s", app_id)
        resp = self._request("GET", f"/synthetic/applications/{app_id}")
        log.debug("Application sync_status=%s", resp.get("sync_status"))
        return resp

    def sync_application(self, app_id: str) -> dict:
        log.debug("Syncing application: id=%s", app_id)
        return self._request("POST", f"/synthetic/applications/{app_id}/sync")

    def search_structures(self, app_id: str) -> list[dict]:
        log.debug("Searching structures for application: id=%s", app_id)
        body = {}
        resp = self._request(
            "POST", f"/synthetic/applications/{app_id}/structures/search", json=body
        )
        items = resp.get("items", [])
        log.debug("Found %d structure(s): %s", len(items), [s.get("name") for s in items])
        return items

    # ── Connectors ───────────────────────────────────────────

    def search_connectors(self, app_id: str) -> list[dict]:
        log.debug("Searching connectors for application: id=%s", app_id)
        body = {"filter_expression": f"application_id eq '{app_id}'"}
        resp = self._request("POST", "/synthetic/connectors/search", json=body)
        items = resp.get("items", [])
        log.debug("Found %d connector(s)", len(items))
        return items

    def create_connector(
        self,
        name: str,
        app_id: str,
        jdbc_driver_id: str,
        host: str,
        port: int,
        username: str,
        password: str,
        database_name: str,
        schema_name: str,
    ) -> dict:
        log.debug("Creating connector: name=%s, app_id=%s, host=%s:%d, db=%s, schema=%s",
                   name, app_id, host, port, database_name, schema_name)
        body = {
            "name": name,
            "application_id": app_id,
            "connector_type": "DATABASE",
            "connector_subtype": "EXTENDED",
            "jdbc_driver_id": jdbc_driver_id,
            "is_reference": True,
            "is_target": True,
            "database_config": {
                "host": host,
                "port": port,
                "authentication_type": "USERNAME_PASSWORD",
                "username": username,
                "password": password,
                "database_name": database_name,
                "schema_name": schema_name,
                "jdbc_url": f"jdbc:postgresql://{host}:{port}/{database_name}",
            },
        }
        resp = self._request("POST", "/synthetic/connectors", json=body)
        log.debug("Connector created: id=%s", resp.get("id"))
        return resp

    def test_connector(self, connector_id: str) -> dict:
        log.debug("Testing connector: id=%s", connector_id)
        return self._request("POST", f"/synthetic/connectors/{connector_id}/test")

    # ── JDBC Drivers ─────────────────────────────────────────

    def search_jdbc_drivers(self) -> list[dict]:
        log.debug("Searching JDBC drivers")
        resp = self._request("POST", "/synthetic/jdbc-drivers/search", json={})
        items = resp.get("items", [])
        log.debug("Found %d driver(s): %s", len(items), [d.get("name") for d in items])
        return items

    def register_jdbc_driver(
        self, name: str, driver_class_name: str, file_upload_id: str
    ) -> dict:
        log.debug("Registering JDBC driver: name=%s, class=%s, file_id=%s",
                   name, driver_class_name, file_upload_id)
        body = {
            "name": name,
            "driver_class_name": driver_class_name,
            "file_upload_id": file_upload_id,
            "metadata_queries": [
                {
                    "query_type": "IDENTITY_COLUMNS",
                    "sql_query": (
                        "SELECT c.column_name, c.identity_generation AS generation_type, "
                        "CONCAT('START WITH: ', c.identity_start, ', INCREMENT BY: ', c.identity_increment) AS identity_options, "
                        "c.is_nullable AS default_on_null "
                        "FROM information_schema.columns c "
                        "WHERE c.table_schema = :schema AND c.table_name = :table AND c.is_identity = 'YES'"
                    ),
                    "description": "Metadata query for identity columns",
                },
                {
                    "query_type": "CHECK_CONSTRAINTS",
                    "sql_query": (
                        "SELECT tc.constraint_name, ccu.column_name, cc.check_clause AS search_condition, "
                        "CASE WHEN tc.is_deferrable = 'NO' THEN 'ENABLED' ELSE 'DISABLED' END AS status, "
                        "'VALIDATED' AS validated, tc.is_deferrable AS deferrable "
                        "FROM information_schema.table_constraints tc "
                        "LEFT JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name "
                        "AND ccu.table_schema = tc.constraint_schema AND ccu.table_name = tc.table_name "
                        "LEFT JOIN information_schema.check_constraints cc ON cc.constraint_name = tc.constraint_name "
                        "AND cc.constraint_schema = tc.constraint_schema "
                        "WHERE tc.constraint_schema = :schema AND tc.table_name = :table "
                        "AND tc.constraint_type = 'CHECK' AND cc.check_clause NOT LIKE '%%IS NOT NULL%%'"
                    ),
                    "description": "Metadata query for check constraints",
                },
                {
                    "query_type": "TRUNCATE_TABLE",
                    "sql_query": "TRUNCATE TABLE :table CASCADE",
                    "description": "Metadata query to truncate table",
                },
            ],
        }
        resp = self._request("POST", "/synthetic/jdbc-drivers", json=body)
        log.debug("JDBC driver registered: id=%s", resp.get("id"))
        return resp

    # ── Datasets ─────────────────────────────────────────────

    def create_dataset(self, name: str, app_id: str, description: str = "") -> dict:
        log.debug("Creating dataset: name=%s, app_id=%s", name, app_id)
        body = {"name": name, "application_id": app_id, "description": description}
        resp = self._request("POST", "/synthetic/datasets", json=body)
        log.debug("Dataset created: id=%s", resp.get("id"))
        return resp

    def pull_structures(
        self, dataset_id: str, structure_ids: list[str], include_dependents: bool = True
    ) -> dict:
        log.debug("Pulling structures into dataset: dataset_id=%s, structure_ids=%s, include_dependents=%s",
                   dataset_id, structure_ids, include_dependents)
        body = {
            "structure_ids": structure_ids,
            "include_dependent_structures": include_dependents,
        }
        return self._request(
            "POST", f"/synthetic/datasets/{dataset_id}/pull", json=body
        )

    def update_records_count(
        self, dataset_id: str, overrides: list[dict]
    ) -> dict:
        log.debug("Updating records count: dataset_id=%s, overrides=%s", dataset_id, overrides)
        body = {"structure_overrides": overrides}
        return self._request(
            "PATCH", f"/synthetic/datasets/{dataset_id}/records-count", json=body
        )

    def get_dataset_structures(self, dataset_id: str) -> list[dict]:
        log.debug("Getting dataset structures: dataset_id=%s", dataset_id)
        resp = self._request(
            "POST", f"/synthetic/datasets/{dataset_id}/structures/search", json={}
        )
        items = resp.get("items", [])
        log.debug("Found %d dataset structure(s)", len(items))
        return items

    # ── Jobs ─────────────────────────────────────────────────

    def create_job(
        self, name: str, dataset_id: str, target_connector_ids: list[str]
    ) -> dict:
        log.debug("Creating job: name=%s, dataset_id=%s, targets=%s", name, dataset_id, target_connector_ids)
        body = {
            "name": name,
            "dataset_id": dataset_id,
            "target_connector_ids": target_connector_ids,
        }
        resp = self._request("POST", "/synthetic/jobs", json=body)
        log.debug("Job created: id=%s", resp.get("id"))
        return resp

    # ── Executions ───────────────────────────────────────────

    def create_execution(self, job_id: str) -> dict:
        log.debug("Creating execution: job_id=%s", job_id)
        body = {"job_id": job_id}
        resp = self._request("POST", "/synthetic/executions", json=body)
        log.debug("Execution created: id=%s, status=%s", resp.get("id"), resp.get("status"))
        return resp

    def get_execution(self, execution_id: str) -> dict:
        log.debug("Getting execution: id=%s", execution_id)
        resp = self._request("GET", f"/synthetic/executions/{execution_id}")
        log.debug("Execution status=%s, progress=%s", resp.get("status"), resp.get("progress"))
        return resp

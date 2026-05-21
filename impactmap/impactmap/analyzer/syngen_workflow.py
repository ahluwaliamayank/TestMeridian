"""
syngen_workflow.py
------------------
Orchestrates the end-to-end synthetic data generation workflow.

Calls SyngenClient methods in sequence and reports progress
via a callback function for each step.
"""

import time
from datetime import datetime
from typing import Callable

from syngen_client import SyngenClient, SyngenError

# Status constants
RUNNING = "running"
DONE = "done"
ERROR = "error"


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def run_syngen_workflow(
    client: SyngenClient,
    jdbc_driver_id: str,
    db_host: str,
    db_port: int,
    db_user: str,
    db_password: str,
    db_name: str,
    db_schema: str,
    tables: list[str],
    on_message: Callable[[str, str], None],
):
    """
    Execute the full synthetic data generation workflow.

    Args:
        client: Configured SyngenClient instance.
        jdbc_driver_id: ID of the pre-uploaded PostgreSQL JDBC driver file.
        db_host: Hostname for the proxy-app database (as seen by syngen-api).
        db_port: Port for the proxy-app database.
        db_user: Database username.
        db_password: Database password.
        db_name: Database name.
        db_schema: Database schema name.
        tables: List of table names to generate data for.
        on_message: Callback(text, status) to report progress.
    """

    try:
        # ── Step 1: Search for application ───────────────────
        on_message(f"[{_ts()}] Searching for Amazone application...", RUNNING)
        apps = client.search_applications("Amazone")
        if apps:
            app_id = apps[0]["id"]
            on_message(f"[{_ts()}] ✓ Application found (id: {app_id[:8]}...)", DONE)
        else:
            # ── Step 2: Create application ───────────────────
            on_message(f"[{_ts()}] Application not found. Creating...", RUNNING)
            resp = client.create_application(
                "Amazone", "TestMeridian proxy e-commerce app"
            )
            app_id = resp["id"]
            on_message(f"[{_ts()}] ✓ Application created (id: {app_id[:8]}...)", DONE)

        # ── Step 3: Search for connector ─────────────────────
        on_message(f"[{_ts()}] Checking for existing connector...", RUNNING)
        connectors = client.search_connectors(app_id)
        ref_connectors = [c for c in connectors if c.get("is_reference")]
        if ref_connectors:
            connector_id = ref_connectors[0]["id"]
            on_message(
                f"[{_ts()}] ✓ Connector found ({ref_connectors[0].get('name', connector_id[:8])})",
                DONE,
            )
        else:
            # ── Step 4: Register JDBC driver if needed ───────
            on_message(f"[{_ts()}] Checking for PostgreSQL JDBC driver...", RUNNING)
            drivers = client.search_jdbc_drivers()
            pg_drivers = [
                d for d in drivers
                if "postgresql" in (d.get("name", "") + d.get("driver_class_name", "")).lower()
            ]
            if pg_drivers:
                driver_id = pg_drivers[0]["id"]
                on_message(f"[{_ts()}] ✓ JDBC driver found (id: {driver_id[:8]}...)", DONE)
            else:
                on_message(f"[{_ts()}] Registering PostgreSQL JDBC driver...", RUNNING)
                driver_resp = client.register_jdbc_driver(
                    name="PostgreSQL JDBC Driver",
                    driver_class_name="org.postgresql.Driver",
                    file_upload_id=jdbc_driver_id,
                )
                driver_id = driver_resp["id"]
                on_message(f"[{_ts()}] ✓ JDBC driver registered (id: {driver_id[:8]}...)", DONE)

            # ── Step 5: Create connector ─────────────────────
            on_message(f"[{_ts()}] Creating connector to proxy-app database...", RUNNING)
            conn_resp = client.create_connector(
                name="Amazone-DB",
                app_id=app_id,
                jdbc_driver_id=driver_id,
                host=db_host,
                port=db_port,
                username=db_user,
                password=db_password,
                database_name=db_name,
                schema_name=db_schema,
            )
            connector_id = conn_resp["id"]
            on_message(f"[{_ts()}] ✓ Connector created (id: {connector_id[:8]}...)", DONE)

        # ── Step 6: Sync application ─────────────────────────
        on_message(f"[{_ts()}] Triggering schema discovery...", RUNNING)
        client.sync_application(app_id)

        # ── Step 7: Poll sync status ─────────────────────────
        on_message(f"[{_ts()}] ⏳ Discovering schema...", RUNNING)
        for _ in range(60):  # max 3 minutes
            time.sleep(3)
            app = client.get_application(app_id)
            status = app.get("sync_status", "")
            if status == "ACTIVE":
                on_message(f"[{_ts()}] ✓ Discovery complete.", DONE)
                break
            elif status == "ERROR":
                raise SyngenError("Schema discovery failed. Check syngen-api logs.")
        else:
            raise SyngenError("Schema discovery timed out after 3 minutes.")

        # ── Step 8: Find structure IDs for required tables ───
        table_list = ", ".join(tables)
        on_message(f"[{_ts()}] Finding structures for tables: {table_list}", RUNNING)
        all_structures = client.search_structures(app_id)
        matched = [
            s for s in all_structures
            if s.get("name", "").lower() in {t.lower() for t in tables}
        ]
        if not matched:
            raise SyngenError(f"No structures found matching tables: {table_list}")
        matched_names = [s["name"] for s in matched]
        structure_ids = [s["id"] for s in matched]
        on_message(
            f"[{_ts()}] ✓ Found {len(matched)} structures: {', '.join(matched_names)}",
            DONE,
        )

        # ── Step 9: Create dataset ───────────────────────────
        dataset_name = f"TestData-{int(time.time())}"
        on_message(f"[{_ts()}] Creating dataset '{dataset_name}'...", RUNNING)
        ds_resp = client.create_dataset(
            name=dataset_name,
            app_id=app_id,
            description=f"Synthetic test data for tables: {table_list}",
        )
        dataset_id = ds_resp["id"]
        on_message(f"[{_ts()}] ✓ Dataset created", DONE)

        # ── Step 10: Pull structures into dataset ────────────
        on_message(f"[{_ts()}] Pulling table structures into dataset...", RUNNING)
        client.pull_structures(dataset_id, structure_ids, include_dependents=True)
        on_message(f"[{_ts()}] ✓ Structures pulled (including dependents)", DONE)

        # ── Step 11: Set records count to 1 ──────────────────
        on_message(f"[{_ts()}] Setting record count to 1 per table...", RUNNING)
        ds_structures = client.get_dataset_structures(dataset_id)
        overrides = [
            {"structure_id": s["id"], "records_count": 1} for s in ds_structures
        ]
        if overrides:
            client.update_records_count(dataset_id, overrides)
        on_message(f"[{_ts()}] ✓ Record counts set", DONE)

        # ── Step 12: Create job ──────────────────────────────
        job_name = f"TestData-Gen-{int(time.time())}"
        on_message(f"[{_ts()}] Creating synthetic data job...", RUNNING)
        job_resp = client.create_job(
            name=job_name,
            dataset_id=dataset_id,
            target_connector_ids=[connector_id],
        )
        job_id = job_resp["id"]
        on_message(f"[{_ts()}] ✓ Job created", DONE)

        # ── Step 13: Execute job ─────────────────────────────
        on_message(f"[{_ts()}] Executing job...", RUNNING)
        exec_resp = client.create_execution(job_id)
        execution_id = exec_resp["id"]

        # ── Step 14: Poll execution status ───────────────────
        on_message(f"[{_ts()}] ⏳ Generating synthetic data...", RUNNING)
        for _ in range(120):  # max 6 minutes
            time.sleep(3)
            ex = client.get_execution(execution_id)
            ex_status = ex.get("status", "")
            progress = ex.get("progress", 0)
            if ex_status == "SUCCESS":
                on_message(
                    f"[{_ts()}] ✓ Synthetic data generated successfully!\n"
                    f"           1 record created in: {table_list}",
                    DONE,
                )
                return
            elif ex_status in ("FAILURE", "CANCELLED"):
                raise SyngenError(f"Job execution {ex_status.lower()}.")
            else:
                on_message(
                    f"[{_ts()}] ⏳ Generating... ({progress}% complete)",
                    RUNNING,
                )
        raise SyngenError("Job execution timed out after 6 minutes.")

    except SyngenError as e:
        on_message(f"[{_ts()}] ✗ Error: {e}", ERROR)
    except Exception as e:
        on_message(f"[{_ts()}] ✗ Unexpected error: {e}", ERROR)
